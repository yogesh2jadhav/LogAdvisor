"""Command-line interface for the AI-Ready Logging Advisor."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from . import __version__
from .analyzer import AdvisorError, run_scan
from .config import Config
from .db.database import Database
from .llm.ollama_client import OllamaClient
from .report import write_html_report, write_json_report, write_markdown_report


def _log(msg: str) -> None:
    print(f"  {msg}", file=sys.stderr)


def _quiet(_msg: str) -> None:
    pass


class _ProgressBar:
    """Single-line \\r progress bar on stderr. No-op unless stderr is a TTY."""

    WIDTH = 24

    def __init__(self, enabled: Optional[bool] = None):
        self.enabled = sys.stderr.isatty() if enabled is None else enabled
        self._active = False

    def __call__(self, done: int, total: int, label: str = "") -> None:
        if not self.enabled or total <= 0:
            return
        done = min(done, total)
        filled = int(self.WIDTH * done / total)
        bar = "█" * filled + "░" * (self.WIDTH - filled)
        pct = int(100 * done / total)
        sys.stderr.write(f"\r  {label:<16} {bar} {pct:3d}%  {done}/{total}   ")
        sys.stderr.flush()
        self._active = True
        if done >= total:
            self.finish()

    def finish(self) -> None:
        if self.enabled and self._active:
            sys.stderr.write("\n")
            sys.stderr.flush()
            self._active = False


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
        parser=getattr(args, "parser", None),
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
    # progress bar only when not in verbose mode (verbose prints its own lines)
    bar = _ProgressBar(enabled=False if args.verbose else None)
    try:
        result = run_scan(args.project, cfg, use_llm=use_llm, log=log, progress=bar)
    except (AdvisorError, ValueError) as exc:
        bar.finish()
        print(f"\n{exc}", file=sys.stderr)
        return 2
    bar.finish()

    db = Database(cfg.database["path"])
    scan_id = db.save_scan(result)
    db.close()

    out_dir = cfg.output["dir"]
    md = write_markdown_report(result, out_dir)
    js = write_json_report(result, out_dir)
    html = write_html_report(result, out_dir)

    from .scanner.java_parser import active_backend

    print(f"\nProject:            {result.project.project_name}")
    print(f"Parser:             {active_backend()}")
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
    print(f"         {html}   (open in a browser for the tree view)")
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
        res = client.generate(model, 'Return the JSON {"ok": true} and nothing else.',
                              temperature=0.0, json_format=True)
        import json as _json
        parsed = _json.loads(res.text)
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
    cfg = _load_config(args)
    db = Database(cfg.database["path"])
    scan_id = args.scan or db.latest_scan_id()
    if scan_id is None:
        print("No scans in the database.", file=sys.stderr)
        db.close()
        return 1
    result = db.load_scan_result(scan_id)
    db.close()
    if result is None:
        print(f"Scan {scan_id} not found.", file=sys.stderr)
        return 1
    out_dir = args.output or cfg.output["dir"]
    md = write_markdown_report(result, out_dir)
    js = write_json_report(result, out_dir)
    html = write_html_report(result, out_dir)
    print(f"Regenerated reports for scan {scan_id} ({result.project.project_name}, "
          f"score {result.scores.overall_score}/100):")
    print(f"  {md}\n  {js}\n  {html}")
    return 0


def cmd_benchmark(args) -> int:
    from .llm.benchmark import run_benchmark

    cfg = _load_config(args)
    models = [m for chunk in args.models for m in chunk.split(",") if m.strip()]
    if not models:
        print("Pass --models qwen3-coder:8b,qwen3-coder:30b", file=sys.stderr)
        return 2
    log = _log if args.verbose else _quiet
    print(f"Benchmarking {len(models)} model(s) on {args.project}\n")
    try:
        rows = run_benchmark(args.project, cfg, models,
                             min_priority=args.llm_priority or cfg.llm["priority"],
                             limit=args.llm_limit if args.llm_limit is not None else cfg.llm["limit"],
                             log=log)
    except (AdvisorError, ValueError) as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2

    hdr = f"{'MODEL':<22}{'OK':>5}{'FAIL':>6}{'STRUCT%':>9}{'AVG ms':>9}{'TOTAL s':>9}{'OUT tok':>9}{'RECS':>6}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        if not r.get("available"):
            print(f"{r['model']:<22}{'— not available —':>46}")
            continue
        print(f"{r['model']:<22}{r['ok']:>5}{r['failed']:>6}"
              f"{r['structured_output_rate']*100:>8.0f}%{r['avg_response_ms']:>9.0f}"
              f"{r['total_analysis_s']:>9.1f}{r['output_tokens']:>9}{r['recommendation_count']:>6}")
    print("\nRecommendation quality still needs manual review — this measures "
          "mechanical reliability only.")
    return 0


def cmd_eval(args) -> int:
    from .llm.eval_set import run_eval

    cfg = _load_config(args)
    model = args.model or cfg.llm["model"]
    log = _log if args.verbose else _quiet
    print(f"Evaluating recommendation quality: {model}\n")
    try:
        res = run_eval(cfg, model, log=log)
    except (RuntimeError, ValueError) as exc:
        print(f"{exc}", file=sys.stderr)
        return 2

    print(f"{'CASE':<16}{'CATEGORY':<16}{'RESULT'}")
    print("-" * 70)
    for r in res["cases"]:
        if r["failed"]:
            verdict = "FAIL — " + ", ".join(r["failed"])
        elif not r["passed"]:
            verdict = "no finding detected"
        else:
            verdict = f"pass ({len(r['passed'])} checks)"
        print(f"{r['id']:<16}{r['category']:<16}{verdict}")
    s = res["summary"]
    print(f"\nClean cases: {s['clean_cases']}/{s['cases']}   "
          f"Checks passed: {s['checks_passed']}/{s['checks_run']} ({s['pass_rate']*100:.0f}%)")
    return 0 if s["clean_cases"] == s["cases"] else 1


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
    if args.action == "show":
        f = db.get_finding(args.id)
        db.close()
        if not f:
            print(f"Finding {args.id} not found.")
            return 1
        print(f"Finding #{f['id']}  [{f['priority']}]  {f['category']}  ({f['status']})")
        print(f"  {f['file_path'] or '?'}:{f['line']}   {f['class_name'] or '?'}.{f['method_name'] or '?'}")
        print(f"  rule: {f['rule_id']}   existing logging: {bool(f['existing_logging'])} "
              f"({f['logging_quality']})   LLM: {f['llm_status']}")
        req = json.loads(f["required_fields"] or "[]")
        print(f"  required fields: {', '.join(req) or '—'}")
        if f["snippet"]:
            print(f"  snippet: {f['snippet']}")
        r = f.get("recommendation")
        if r:
            print(f"\n  Recommendation ({r['model'] or '?'}): {r['reason']}")
            print(f"    fields:     {', '.join(json.loads(r['recommended_fields'] or '[]'))}")
            print(f"    do NOT log: {', '.join(json.loads(r['do_not_log'] or '[]'))}")
            print(f"    AI value:   {r['ai_usefulness']}  {', '.join(json.loads(r['ai_use_cases'] or '[]'))}")
        run = f.get("llm_run")
        if run and run.get("duration_ms"):
            print(f"\n  LLM run: {run['status']} in {run['duration_ms']} ms, "
                  f"{run['input_tokens']}→{run['output_tokens']} tokens"
                  f"{' (cache hit)' if run['cache_hit'] else ''}")
        return 0

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
    sp.add_argument("--parser", choices=["auto", "treesitter", "regex"],
                    help="Java parser backend (default: auto — tree-sitter if installed)")
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

    sp = sub.add_parser("report", help="(re)generate reports for a scan from the database")
    sp.add_argument("--scan", type=int, help="scan id (default: latest)")
    sp.add_argument("--output")
    add_common(sp)
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("eval", help="score a model against the built-in recommendation eval set")
    sp.add_argument("--verbose", "-v", action="store_true")
    add_common(sp)
    sp.set_defaults(func=cmd_eval)

    sp = sub.add_parser("benchmark", help="compare local models on one project")
    sp.add_argument("--project", required=True)
    sp.add_argument("--models", action="append", required=True,
                    help="comma-separated, e.g. --models qwen3-coder:8b,qwen3-coder:30b")
    sp.add_argument("--llm-priority", choices=["high", "medium", "low"])
    sp.add_argument("--llm-limit", type=int)
    sp.add_argument("--verbose", "-v", action="store_true")
    add_common(sp)
    sp.set_defaults(func=cmd_benchmark)

    sp = sub.add_parser("findings", help="list findings")
    sp.add_argument("--scan", type=int)
    sp.add_argument("--priority", choices=["HIGH", "MEDIUM", "LOW", "high", "medium", "low"])
    add_common(sp)
    sp.set_defaults(func=cmd_findings)

    sp = sub.add_parser("finding", help="show or update a single finding")
    sp.add_argument("action", choices=["show", "accept", "reject", "implemented",
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
