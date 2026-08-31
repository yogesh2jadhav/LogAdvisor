# AI-Ready Logging Advisor

A standalone, **local-only** developer tool that scans an existing **Java + Apache
Spark** repository and recommends where structured logging should be added so the
application becomes *AI-ready* for monitoring, anomaly detection, troubleshooting
and root-cause analysis.

The advisor is **read-only** against the target project. It never modifies source
code, never uploads code, and never reads data files (parquet/csv/json contents).

## How it works — two passes

```
Pass 1  (deterministic, always runs)
  project discovery → Java structural parse → Spark op / logging / exception
  detection → configurable rule engine → findings → AI-observability score

Pass 2  (optional, --no-llm to skip)
  select important findings → build minimal per-finding context → local Ollama
  (Qwen3-Coder) → validate structured JSON → recommendation
```

Static analysis discovers *facts*. The local LLM only explains, prioritises and
screens recommendations — it is never responsible for parsing, counting or
scoring. The score is 100% deterministic.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

Requires Python 3.11+. Runtime deps: `PyYAML`, `pydantic`.

## Set up the local model (for pass 2)

```bash
# 1. install Ollama            https://ollama.com
# 2. start it                  (ollama serve / the app)
# 3. pull the coding model
ollama pull qwen3-coder:30b
# 4. verify
java-log-advisor doctor
```

On limited hardware use a smaller model — code is identical, only config changes:

```bash
java-log-advisor doctor --model qwen3-coder:8b
java-log-advisor scan --project ./my-project --model qwen3-coder:8b
```

## Usage

```bash
# deterministic only (no Ollama needed) — great for testing the scanner
java-log-advisor scan --project /path/to/java-spark-project --no-llm

# full run with local LLM
java-log-advisor scan --project /path/to/java-spark-project

# limit LLM work
java-log-advisor scan --project ./p --llm-priority high --llm-limit 50
```

Reports are written to `logging-report/`:

* `logging_advisory_report.md` — human-readable
* `logging_advisory_report.json` — enriched, UI-ready (schema v1): flat `findings[]`
  **plus** a full `files → classes → methods` tree with per-method `detected`
  matrix, spark ops, existing logs, `finding_ids`, and per-file/method
  readiness + risk rollups, plus the rule contract
* `logging_advisory_report.html` — self-contained interactive viewer (tree +
  dashboard + findings table + logging contract). No network / no assets — just
  open it in a browser.

### Other commands

| Command | Purpose |
| --- | --- |
| `doctor` | check Ollama reachability, model availability, structured output |
| `init` | create the local SQLite database |
| `history` | list past scans (score / findings / model) |
| `compare --scan A --scan B` | diff two scans (score + priority counts) |
| `report [--scan N] [--output DIR]` | regenerate md/json/html reports for a scan **from the database** (no re-scan; defaults to the latest scan) |
| `findings [--priority HIGH]` | list findings from the latest (or `--scan`) run |
| `finding show <id>` | full detail for one finding: location, rule, required fields, LLM recommendation, run metrics |
| `finding accept\|reject\|implemented\|false-positive\|reviewed <id>` | update a finding's lifecycle status (carried forward to future scans by fingerprint) |
| `benchmark --project P --models a,b` | run the LLM pass for several local models and compare reliability / latency / tokens (quality still needs manual review) |

### Key options

```
--project     target repo (required for scan)
--output      report directory              (default: logging-report)
--model       Ollama model                  (default: qwen3-coder:30b)
--host        Ollama host                   (default: http://localhost:11434)
--config      YAML config file
--database    SQLite path                   (default: .ai-ready-log-advisor/advisor.db)
--include / --exclude   extra scan globs / ignored dirs
--no-llm      deterministic scan only
--llm-priority / --llm-limit    control which & how many findings reach the LLM
-v / --verbose
```

## Configuration

See [`config/application.yaml`](config/application.yaml). Highlights:

```yaml
llm:
  model: qwen3-coder:30b
  temperature: 0.1
  priority: high        # min finding priority sent to the LLM
privacy:
  allow_external_llm: false   # non-local Ollama host -> LLM analysis refused
  mask_secrets: true
```

The logging contract lives in
[`logadvisor/rules/logging_rules.yaml`](logadvisor/rules/logging_rules.yaml) and
is fully configurable. Its `version` is part of the LLM cache key.

## Privacy & safety

* Default to local Ollama; refuses non-local endpoints unless
  `privacy.allow_external_llm: true`.
* Never calls external LLM APIs, never uploads source.
* Masks obvious secrets (passwords, API keys, tokens, JDBC creds) before any
  code is sent to the LLM.
* Screens both existing logs and generated recommendations for PHI/PII fields
  (patient identifiers, clinical values, credentials …) and replaces them with
  metadata-oriented fields.
* The SQLite database stores **code-analysis metadata only** — no patient data,
  no source dumps — and is git-ignored.

## AI Observability Score (deterministic, 0–100)

| Category | Weight |
| --- | ---: |
| Job lifecycle | 15 |
| Input visibility | 15 |
| Transformation visibility | 15 |
| Join visibility | 15 |
| Output visibility | 15 |
| Exception visibility | 10 |
| Structured logging | 10 |
| Trace / run correlation | 5 |

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

Test fixture: [`tests/fixtures/sample-spark-project`](tests/fixtures/sample-spark-project).

## Project layout

```
logadvisor/
  scanner/     project discovery + Java/Spark/logging/exception detection
  rules/       logging_rules.yaml + deterministic rule engine
  llm/         provider interface, ollama client, prompt builder, response validation, cache, analyzer, benchmark
  db/          SQLite persistence + migrations
  report/      markdown + enriched-json + self-contained HTML viewer; tree.py builds the schema-v1 doc
  models.py    shared dataclasses
  scoring.py   deterministic AI-observability score
  analyzer.py  two-pass orchestration
  cli.py       command-line interface
```

## Not in this version

Vector/graph DBs, RAG, agents, patient-data analysis, automatic source
modification, git commit/push, cloud LLMs. See `Plan.md` §45.

The Java parser is a pragmatic literal-masking + brace-matching implementation
(no regex for body semantics). A tree-sitter backend is the intended upgrade.
