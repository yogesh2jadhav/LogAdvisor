"""Command-line interface for the AI-Ready Logging Advisor."""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from . import __version__
from .analyzer import AdvisorError, run_scan
from .config import Config
from .db.database import Database
from .llm.ollama_client import OllamaClient
from .report import write_json_report, write_markdown_report


def _log(msg: str) -> None:
    print(f"  {msg}", file=sys.stderr)


def _quiet(_msg: str) -> None:
    pass


def _load_config(args) -> Config:
    cfg = Config.load(getattr(args, "config", None))
    cfg.apply_overrides(
        model=getattr(args, "model", None),
        host=getattr(args, "host", None),
        no_llm=getattr(args, "no_llm", False),
        output=getattr(args, "output", None),
        database=getattr(args, "database", None),
        llm_priority=getattr(args, "llm_priority", None),
        llm_limit=getattr(args, "llm_limit", None),
        include=getattr(args, "include", None),
        exclude=getattr(args, "exclude", None),
    )
    return cfg


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_scan(args) -> int:
    cfg = _load_config(args)
    log = _log if args.verbose else _quiet
    use_llm = not args.no_llm

    print("AI-Ready Logging Advisor")
    print("────────────────────────")
    try:
        result = run_scan(args.project, cfg, use_llm=use_llm, log=log)
    except (AdvisorError, ValueError) as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2

    db = Database(cfg.database["path"])
    scan_id = db.save_scan(result)
    db.close()

    out_dir = cfg.output["dir"]
    md = write_markdown_report(result, out_dir)
    js = write_json_report(result, out_dir)

    print(f"\nProject:            {result.project.project_name}")
    print(f"Files:              {result.files_scanned}")
    print(f"Methods:            {result.methods_scanned}")
    print(f"Spark operations:   {result.spark_operations}")
    print(f"Existing logs:      {result.existing_logs}")
    print(f"Findings:           {len(result.findings)}")
    if result.llm_enabled:
        print(f"LLM:               {result.llm_model} "
              f"(calls={result.llm_calls}, failures={result.llm_failures}, "
              f"cache_hits={result.cache_hits})")
    else:
        print("LLM:               disabled (--no-llm)")
    print(f"\nAI Observability Score: {result.scores.overall_score}/100")
    print(f"  HIGH:   {len(result.by_priority('HIGH'))}")
    print(f"  MEDIUM: {len(result.by_priority('MEDIUM'))}")
    print(f"  LOW:    {len(result.by_priority('LOW'))}")
    print(f"\nScan id: {scan_id}")
    print(f"Report:  {md}")
    print(f"         {js}")
    return 0


def cmd_doctor(args) -> int:
    cfg = _load_config(args)
    print("AI-Ready Logging Advisor Diagnostics\n")
    try:
        cfg.validate_llm_endpoint()
    except ValueError as exc:
        print(f"Config:\n    ✗ {exc}")
        return 1
    client = OllamaClient(cfg.llm["host"], cfg.llm["timeout_seconds"])

    ok = client.is_available()
    print(f"Ollama ({cfg.llm['host']}):\n    {'✓ Connected' if ok else '✗ Not reachable'}")
    if not ok:
        print("\nStart Ollama and retry, or run `scan --no-llm`.")
        return 1

    model = cfg.llm["model"]
    has = client.has_model(model)
    print(f"\nModel:\n    {model}\n    {'✓ Available' if has else '✗ Not pulled (ollama pull ' + model + ')'}")
    if not has:
        return 1

    try:
        raw = client.generate(model, 'Return the JSON {"ok": true} and nothing else.',
                              temperature=0.0, json_format=True)
        import json as _json
        parsed = _json.loads(raw)
        gen_ok = isinstance(parsed, dict)
    except Exception as exc:  # noqa: BLE001
        print(f"\nTest generation:\n    ✗ {exc}")
        return 1
    print(f"\nTest generation:\n    ✓ Passed")
    print(f"\nStructured output:\n    {'✓ Passed' if gen_ok else '✗ Failed'}")
    print("\nReady for analysis." if gen_ok else "")
    return 0 if gen_ok else 1


def cmd_init(args) -> int:
    cfg = _load_config(args)
    db = Database(cfg.database["path"])
    db.close()
    print(f"Initialized database at {cfg.database['path']}")
    return 0


def cmd_history(args) -> int:
    cfg = _load_config(args)
    db = Database(cfg.database["path"])
    rows = db.history(args.limit)
    db.close()
    if not rows:
        print("No scans recorded yet.")
        return 0
    print(f"{'ID':<5}{'Date (UTC)':<21}{'Score':<8}{'Findings':<10}{'Model':<20}{'Project'}")
    print("-" * 90)
    for r in rows:
        print(f"{r['id']:<5}{(r['started_at'] or '')[:19].replace('T', ' '):<21}"
              f"{str(r['score'] if r['score'] is not None else '-'):<8}"
              f"{str(r['findings_count']):<10}{(r['llm_model'] or '-'):<20}{r['project']}")
    return 0


def cmd_compare(args) -> int:
    cfg = _load_config(args)
    db = Database(cfg.database["path"])
    a, b = db.scan_row(args.scan[0]), db.scan_row(args.scan[1])
    if not a or not b:
        print("One or both scan ids not found.")
        db.close()
        return 1
    ca, cb = db.priority_counts(a["id"]), db.priority_counts(b["id"])
    db.close()
    sa = a["ai_observability_score"] or 0
    sb = b["ai_observability_score"] or 0
    print("AI Observability Comparison")
    print("───────────────────────────")
    print(f"Scan {a['id']} ({a['started_at']}): {sa}")
    print(f"Scan {b['id']} ({b['started_at']}): {sb}")
    print(f"Improvement: {round(sb - sa, 1):+}")
    print()
    for p in ("HIGH", "MEDIUM", "LOW"):
        print(f"{p:<8} {ca.get(p, 0)} -> {cb.get(p, 0)}")
    return 0


def cmd_report(args) -> int:
    print("Report regeneration from the database is not yet implemented; "
          "re-run `scan` to refresh reports.", file=sys.stderr)
    return 1


def cmd_findings(args) -> int:
    cfg = _load_config(args)
    db = Database(cfg.database["path"])
    rows = db.list_findings(getattr(args, "scan", None), getattr(args, "priority", None))
    db.close()
    if not rows:
        print("No findings.")
        return 0
    print(f"{'ID':<6}{'PRIO':<8}{'STATUS':<14}{'CATEGORY':<16}{'LOCATION'}")
    print("-" * 90)
    for r in rows:
        loc = f"{r['file_path'] or '?'}:{r['line']}"
        print(f"{r['id']:<6}{r['priority']:<8}{r['status']:<14}{r['category']:<16}{loc}")
    return 0


def cmd_finding(args) -> int:
    cfg = _load_config(args)
    db = Database(cfg.database["path"])
    status_map = {
        "accept": "ACCEPTED", "reject": "REJECTED",
        "implemented": "IMPLEMENTED", "false-positive": "FALSE_POSITIVE",
        "reviewed": "REVIEWED",
    }
    status = status_map[args.action]
    ok = db.set_finding_status(args.id, status)
    db.close()
    print(f"Finding {args.id} -> {status}" if ok else f"Finding {args.id} not found.")
    return 0 if ok else 1


# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="java-log-advisor",
                                description="AI-Ready Logging Advisor for Java + Apache Spark.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp):
        sp.add_argument("--config")
        sp.add_argument("--database")
        sp.add_argument("--model")
        sp.add_argument("--host")

    sp = sub.add_parser("scan", help="scan a project and write reports")
    sp.add_argument("--project", required=True)
    sp.add_argument("--output")
    sp.add_argument("--include", action="append")
    sp.add_argument("--exclude", action="append")
    sp.add_argument("--no-llm", action="store_true", help="deterministic scan only")
    sp.add_argument("--llm-priority", choices=["high", "medium", "low"])
    sp.add_argument("--llm-limit", type=int)
    sp.add_argument("--verbose", "-v", action="store_true")
    add_common(sp)
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("doctor", help="check Ollama / model availability")
    add_common(sp)
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("init", help="create the local database")
    add_common(sp)
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("history", help="show scan history")
    sp.add_argument("--limit", type=int, default=50)
    add_common(sp)
    sp.set_defaults(func=cmd_history)

    sp = sub.add_parser("compare", help="compare two scans")
    sp.add_argument("--scan", type=int, action="append", required=True,
                    help="pass twice: --scan 2 --scan 3")
    add_common(sp)
    sp.set_defaults(func=cmd_compare)

    sp = sub.add_parser("report", help="(re)generate a report for a scan")
    sp.add_argument("--scan", type=int, required=True)
    add_common(sp)
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("findings", help="list findings")
    sp.add_argument("--scan", type=int)
    sp.add_argument("--priority", choices=["HIGH", "MEDIUM", "LOW", "high", "medium", "low"])
    add_common(sp)
    sp.set_defaults(func=cmd_findings)

    sp = sub.add_parser("finding", help="update a finding's lifecycle status")
    sp.add_argument("action", choices=["accept", "reject", "implemented",
                                       "false-positive", "reviewed"])
    sp.add_argument("id", type=int)
    add_common(sp)
    sp.set_defaults(func=cmd_finding)

    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "scan", None) and args.command == "compare" and len(args.scan) != 2:
        print("compare needs exactly two --scan values", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
