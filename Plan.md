# LOCAL LLM AI-READY LOGGING ADVISOR

## Detailed Implementation Plan — Java + Apache Spark

**Version:** 1.0
**Target:** Existing Java + Apache Spark project
**LLM Runtime:** Local LLM through Ollama
**Primary Model:** Qwen (configurable)
**Purpose:** Analyze an existing Java + Spark codebase and recommend where structured logging should be added so that the application becomes AI-ready for future monitoring, anomaly detection, troubleshooting, root-cause analysis, and GenAI-assisted operations.

---

# 1. PROJECT OBJECTIVE

Build a standalone developer tool called:

`AI-Ready Logging Advisor`

The tool scans an existing Java + Spark repository and produces actionable recommendations for improving logging.

The tool MUST NOT initially modify the user's source code.

The first version is an advisory system:

```text
Existing Java + Spark Code
        ↓
Static Code Analysis
        ↓
Detect Spark operations / execution boundaries
        ↓
Detect existing logging
        ↓
Apply deterministic logging rules
        ↓
Send relevant findings + code context to Local LLM
        ↓
LLM prioritizes and explains recommendations
        ↓
Generate Markdown/JSON report
```

The system should eventually support:

```text
Codebase
   ↓
Logging Advisor
   ↓
Logging recommendations
   ↓
Developer review
   ↓
Logging implementation
   ↓
Structured logs
   ↓
Future AI Pipeline Assistant
```

---

# 2. IMPORTANT DESIGN PRINCIPLES

Claude MUST follow these principles.

## 2.1 Do not build an LLM-only scanner

Do NOT send the entire repository to the LLM.

Use deterministic/static analysis first.

The LLM is responsible for:

* understanding context
* explaining why a logging point matters
* prioritizing recommendations
* identifying potential observability gaps
* suggesting useful fields
* identifying AI/RCA value

Static analysis is responsible for:

* discovering Java files
* discovering classes/methods
* detecting Spark APIs
* detecting logging statements
* detecting exceptions
* detecting input/output operations
* identifying candidate logging points

---

## 2.2 Do not introduce RAG in MVP

Do NOT build:

* vector database
* embeddings
* Graph RAG
* autonomous agent
* multi-agent architecture
* knowledge graph

for version 1.

These may be considered later.

The initial system should work with:

```text
Code Scanner
+
Rules
+
Local LLM
```

---

## 2.3 Do not process clinical patient data

The tool is a CODE ANALYZER.

It must analyze source code and configuration required to understand the application.

It must NOT read:

* patient records
* production Parquet contents
* PHI
* PII
* clinical records

unless explicitly enabled in a future version.

The system should actively avoid recommending logs containing:

* patient name
* patient ID
* address
* phone
* email
* diagnosis details
* medication details
* clinical notes
* authentication credentials
* access tokens
* passwords
* secrets

---

# 3. EXPECTED INPUT

The tool accepts:

```bash
java-log-advisor --project /path/to/project
```

Optional:

```bash
java-log-advisor \
  --project /path/to/project \
  --output ./logging-report \
  --model qwen
```

The project may contain:

```text
src/
pom.xml
build.gradle
application.properties
application.yml
README.md
Java source files
Spark code
SQL
configuration
tests
```

The scanner should recursively inspect source files while ignoring:

```text
.git/
target/
build/
.idea/
.vscode/
node_modules/
.venv/
logs/
generated/
```

Make ignored directories configurable.

---

# 4. HIGH-LEVEL ARCHITECTURE

Implement these components:

```text
ai-ready-log-advisor/
│
├── scanner/
│   ├── project_scanner
│   ├── java_scanner
│   ├── spark_detector
│   ├── logging_detector
│   ├── exception_detector
│   └── io_detector
│
├── rules/
│   ├── logging_rules.yaml
│   └── rule_engine
│
├── llm/
│   ├── ollama_client
│   ├── prompt_builder
│   ├── response_parser
│   └── llm_analyzer
│
├── model/
│   ├── code_file
│   ├── method
│   ├── spark_operation
│   ├── logging_statement
│   ├── finding
│   └── recommendation
│
├── report/
│   ├── markdown_report
│   └── json_report
│
├── config/
│   └── application.yaml
│
├── tests/
│
└── README.md
```

The exact package/module structure can be adjusted to the chosen implementation language.

---

# 5. TECHNOLOGY RECOMMENDATION

Prefer implementing the advisor itself in Python unless there is a strong reason to implement it in Java.

Reason:

* easier Ollama integration
* easier text processing
* easier report generation
* easier experimentation with LLM prompts
* easier static-analysis orchestration

The TARGET codebase remains Java + Spark.

The advisor is a separate developer tool.

Recommended stack:

```text
Python 3.11+
Ollama
Qwen local model
Tree-sitter or another Java parser
PyYAML
Pydantic
pytest
```

Use a proper Java parser/AST approach where practical.

Do not rely exclusively on regular expressions for Java syntax.

Regex may be used as a fallback for simple detection, but AST-based analysis should be preferred.

---

# 6. PHASE 1 — PROJECT DISCOVERY

Implement a project scanner.

Input:

```text
/path/to/project
```

Output:

```json
{
  "project_name": "...",
  "language": "Java",
  "frameworks": ["Apache Spark"],
  "build_system": "Maven",
  "java_files": 327,
  "test_files": 84
}
```

Detect:

* Maven
* Gradle
* Java version
* Spark dependencies
* Spark SQL dependencies
* logging frameworks

Recognize common logging frameworks:

```text
SLF4J
Log4j
Log4j2
java.util.logging
```

---

# 7. PHASE 2 — JAVA SOURCE ANALYSIS

For every Java source file, extract:

```text
file path
package
imports
classes
interfaces
methods
constructors
method parameters
method return types
annotations
try/catch blocks
throw statements
logging statements
method calls
```

Represent each method internally as:

```json
{
  "file": "src/.../PatientProcessor.java",
  "class": "PatientProcessor",
  "method": "processPatients",
  "start_line": 100,
  "end_line": 180,
  "parameters": ["Dataset<Row> patients"],
  "return_type": "Dataset<Row>"
}
```

---

# 8. PHASE 3 — SPARK OPERATION DETECTION

Detect common Spark operations.

## Spark initialization

Detect:

```text
SparkSession.builder()
SparkContext
JavaSparkContext
```

Recommendation candidate:

```text
JOB_START
```

---

## Spark input

Detect:

```java
spark.read()
spark.read().format(...)
spark.read().parquet(...)
spark.read().csv(...)
spark.read().json(...)
spark.table(...)
```

Also detect:

```text
Dataset<Row>
DataFrameReader
```

Recommendation:

```text
DATASET_READ
```

Potential fields:

```text
run_id
source
dataset
format
record_count
schema_identifier
```

Do NOT automatically recommend logging actual patient records.

---

# 9. PHASE 4 — TRANSFORMATION DETECTION

Detect:

```text
filter()
where()
select()
selectExpr()
withColumn()
drop()
dropDuplicates()
distinct()
join()
groupBy()
agg()
map()
flatMap()
mapPartitions()
union()
repartition()
coalesce()
sort()
orderBy()
```

Each operation becomes a candidate observability point.

However, do NOT recommend logging every transformation.

The rule engine should classify operations:

```text
HIGH
MEDIUM
LOW
```

Example:

```text
JOIN          HIGH
FILTER        HIGH
GROUP BY      HIGH
DEDUPLICATION HIGH
INPUT READ    HIGH
OUTPUT WRITE  HIGH
simple select LOW
simple rename LOW
```

---

# 10. PHASE 5 — SPARK ACTION DETECTION

Detect Spark actions such as:

```text
count()
collect()
save()
saveAsTextFile()
saveAsParquetFile()
write()
```

These are important because Spark is lazily evaluated.

The advisor should understand:

```text
Transformation definition
        ≠
Actual execution
```

For example:

```java
Dataset<Row> result = input
    .filter(...)
    .join(...)
    .select(...);

result.write().parquet(path);
```

The advisor should recognize that the write/action causes execution and therefore is an important boundary for logging.

---

# 11. PHASE 6 — PARQUET OUTPUT DETECTION

Detect:

```text
.parquet
DataFrameWriter
write.parquet()
format("parquet")
save()
```

For each output candidate recommend:

```text
DATASET_WRITE
```

Potential fields:

```text
run_id
processing_name
output_dataset
output_path
record_count
file_count
duration
status
```

The report must explicitly warn against logging sensitive data values.

---

# 12. PHASE 7 — JOIN ANALYSIS

JOIN is a high-priority observability point.

Detect:

```java
left.join(right, ...)
```

Recommend considering:

```text
left_record_count
right_record_count
output_record_count
join_type
join_key_identifier
unmatched_count
```

Do not log actual join key values if those values can contain patient identifiers.

Use metadata about the key instead.

Example:

```text
join_key = "patient_id"
```

may itself require governance depending on the environment.

Prefer:

```text
join_key_type = "PATIENT_IDENTIFIER"
```

if such classification is available.

---

# 13. PHASE 8 — FILTER ANALYSIS

Detect filters.

Example:

```java
df.filter(col("status").equalTo("ACTIVE"))
```

Recommend:

```text
records_before
records_after
records_removed
filter_name
```

Do not log:

```text
patient_id
patient_name
diagnosis
```

The purpose is to understand dataset flow, not individual records.

---

# 14. PHASE 9 — EXCEPTION ANALYSIS

Detect:

```text
try
catch
throw
throws
```

For each important exception boundary determine whether there is:

```text
logger.error(...)
```

If not, recommend logging.

Recommended context:

```text
run_id
job_name
processing_stage
operation
exception_type
error_message
duration
```

Do not recommend logging secrets or sensitive payloads.

---

# 15. PHASE 10 — EXISTING LOGGING DETECTION

Detect:

```text
logger.info()
logger.warn()
logger.error()
logger.debug()
log.info()
log.warn()
log.error()
```

Extract:

```text
log level
message
line number
method
variables
```

Example:

```java
logger.info("Starting patient processing");
```

Record:

```json
{
  "level": "INFO",
  "line": 42,
  "message": "Starting patient processing"
}
```

Evaluate whether the existing log contains useful structured context.

---

# 16. PHASE 11 — STRUCTURED LOGGING DETECTION

Detect whether logs use structured fields.

For example:

```java
logger.info(
    "Processing completed runId={} records={}",
    runId,
    recordCount
);
```

This is better than:

```java
logger.info("Processing completed");
```

The advisor should classify logging quality:

```text
GOOD
PARTIAL
WEAK
MISSING
```

---

# 17. PHASE 12 — LOGGING CONTRACT

Create:

`rules/logging_rules.yaml`

Example:

```yaml
job:
  start:
    priority: high
    fields:
      - run_id
      - job_name
      - start_time

  completion:
    priority: high
    fields:
      - run_id
      - status
      - duration

input:
  priority: high
  fields:
    - run_id
    - source
    - dataset
    - record_count

join:
  priority: high
  fields:
    - run_id
    - left_count
    - right_count
    - output_count
    - join_type
    - duration

filter:
  priority: medium
  fields:
    - run_id
    - input_count
    - output_count
    - removed_count

output:
  priority: high
  fields:
    - run_id
    - dataset
    - output_path
    - record_count
    - duration
    - status

exception:
  priority: high
  fields:
    - run_id
    - stage
    - operation
    - exception_type
    - error_message
```

The rule file must be configurable.

---

# 18. PHASE 13 — FINDINGS ENGINE

The deterministic analyzer should produce findings.

Example:

```json
{
  "type": "JOIN",
  "file": "PatientProcessor.java",
  "method": "processPatients",
  "line": 143,
  "existing_logging": false,
  "priority": "HIGH",
  "required_fields": [
    "run_id",
    "left_count",
    "right_count",
    "output_count",
    "join_type"
  ]
}
```

Another:

```json
{
  "type": "PARQUET_WRITE",
  "file": "PatientProcessor.java",
  "line": 189,
  "existing_logging": false,
  "priority": "HIGH"
}
```

---

# 19. PHASE 14 — LOCAL LLM INTEGRATION

Use Ollama.

The model name must be configurable:

```yaml
llm:
  provider: ollama
  model: qwen
  host: http://localhost:11434
  temperature: 0.1
```

Do not hard-code a specific Qwen version.

---

# 20. LLM INPUT

Do NOT send the entire project.

For each finding, send:

```text
Project information
+
File information
+
Method information
+
Relevant code snippet
+
Detected Spark operations
+
Existing logging
+
Applicable logging rule
```

Example prompt context:

```text
Project:
ClinicalSparkPipeline

Technology:
Java + Apache Spark

File:
PatientProcessor.java

Method:
processPatients()

Detected operations:
- JOIN
- FILTER
- PARQUET_WRITE

Existing logging:
- INFO at line 120
- no logging around JOIN
- no logging around FILTER
- no logging around output

Logging standard:
JOIN requires:
- run_id
- left_count
- right_count
- output_count
- join_type
- duration
```

---

# 21. LLM ROLE

The LLM should answer:

1. Is the candidate logging point important?
2. Why is it important?
3. What should be logged?
4. What should NOT be logged?
5. What is the expected AI/RCA usefulness?
6. What priority should the recommendation receive?
7. Is the deterministic recommendation reasonable?

The LLM should NOT invent facts about runtime behavior.

Use language such as:

```text
"Potentially"
"Recommended"
"Could help detect"
```

rather than claiming something happens at runtime unless demonstrated by code.

---

# 22. FORCE STRUCTURED LLM OUTPUT

The LLM response should conform to a schema.

Example:

```json
{
  "recommendation": true,
  "priority": "HIGH",
  "category": "JOIN",
  "reason": "...",
  "recommended_fields": [
    "run_id",
    "left_count",
    "right_count",
    "output_count",
    "join_type",
    "duration"
  ],
  "do_not_log": [
    "patient identifiers",
    "clinical values",
    "credentials",
    "secrets"
  ],
  "ai_usefulness": "HIGH",
  "ai_use_cases": [
    "anomaly_detection",
    "root_cause_analysis",
    "pipeline_monitoring"
  ]
}
```

Validate the response using Pydantic or equivalent schema validation.

If the LLM returns invalid JSON:

1. attempt controlled repair
2. retry once with a correction prompt
3. if still invalid, mark the result as `LLM_ANALYSIS_FAILED`

Never crash the complete scan because of one bad LLM response.

---

# 23. PHI/PII SAFETY CHECK

Implement a basic source-code safety layer.

Before sending code to the LLM:

* remove comments containing obvious secrets
* mask API keys
* mask passwords
* mask tokens
* mask connection strings where possible

The system should also inspect generated recommendations for dangerous fields.

Reject or flag recommendations such as:

```text
log patient name
log patient diagnosis
log full patient object
log request body
log medical history
log access token
log password
```

Replace with metadata-oriented logging.

---

# 24. AI-READINESS SCORING

Create a score from 0–100.

Suggested categories:

```text
Job lifecycle        15
Input visibility     15
Transformation       15
Join visibility      15
Output visibility    15
Exception visibility 10
Structured logging   10
Trace/run correlation 5
```

Example:

```text
AI Observability Score: 58/100
```

The score should be deterministic, not generated by the LLM.

---

# 25. REPORT FORMAT

Generate:

```text
reports/
    logging_advisory_report.md
    logging_advisory_report.json
```

Markdown report structure:

```text
# AI-Ready Logging Advisory Report

## Executive Summary

## Project Information

## AI Observability Score

## Critical Recommendations

## High Priority Recommendations

## Medium Priority Recommendations

## Low Priority Recommendations

## Existing Logging Analysis

## Spark Pipeline Analysis

## Parquet Output Analysis

## Exception Handling Analysis

## Recommended Logging Contract

## AI/RCA Readiness

## Files Requiring Attention

## Appendix
```

---

# 26. SAMPLE REPORT

Example:

```text
# AI-Ready Logging Advisory Report

Project:
ClinicalSparkPipeline

Files scanned:
327

Methods analyzed:
1,284

Spark operations detected:
2,941

Existing logging statements:
418

Potential logging gaps:
161

AI Observability Score:
58/100
```

Then:

```text
## Critical Recommendations

### 1. PatientProcessor.java:143

Operation:
JOIN

Priority:
HIGH

Current state:
No logging detected.

Recommended context:
- run_id
- left_count
- right_count
- output_count
- join_type
- duration

Why:
Join operations can materially change dataset cardinality.
These metrics can help future AI systems identify abnormal
record-flow changes.

Do not log:
- patient records
- patient identifiers
- clinical values

Future AI value:
HIGH
```

---

# 27. FILE-LEVEL SUMMARY

For each important Java file:

```text
PatientProcessor.java

AI Readiness: 42/100

HIGH:
- JOIN at line 143
- Parquet write at line 189
- exception path at line 201

MEDIUM:
- filter at line 155

Existing logging:
3 statements

Missing:
8 recommended observability fields
```

---

# 28. METHOD-LEVEL SUMMARY

For each important method:

```text
processPatients()

Risk:
HIGH

Detected:
✓ input
✓ join
✓ filter
✓ output
✗ structured logging
✗ record-flow metrics
✗ duration
✗ exception context
```

---

# 29. CLI

Implement:

```bash
java-log-advisor scan --project ./my-spark-project
```

Options:

```bash
--project
--output
--model
--config
--include
--exclude
--no-llm
--verbose
```

Important:

```bash
--no-llm
```

must run the deterministic scanner without calling Ollama.

This allows testing the scanner independently.

---

# 30. TWO-PASS EXECUTION

The tool should work in two passes.

## Pass 1 — Deterministic

```text
Scan repository
↓
Parse Java
↓
Detect Spark
↓
Detect logs
↓
Detect exceptions
↓
Apply rules
↓
Create findings
```

## Pass 2 — AI

```text
Select important findings
↓
Create context
↓
Call local Qwen
↓
Validate response
↓
Store recommendation
```

This separation is mandatory.

---

# 31. PERFORMANCE

Do not send every method to the LLM.

Prioritize:

```text
JOIN
FILTER
GROUP BY
AGGREGATION
INPUT
OUTPUT
EXCEPTION
Spark actions
```

Simple methods should be handled deterministically.

For example:

```text
1,284 methods
      ↓
Static analysis
      ↓
161 findings
      ↓
Priority filtering
      ↓
75 important findings
      ↓
LLM analysis
```

This reduces:

* token usage
* runtime
* local model workload
* unnecessary LLM calls

---

# 32. LLM CACHING

Implement caching.

If the same code and rule are analyzed again, do not call Ollama unnecessarily.

Generate a hash from:

```text
file content
method code
rule version
model name
prompt version
```

Store:

```text
cache/
```

This is important for iterative development.

---

# 33. TESTING STRATEGY

Create test fixtures containing small Java files.

Test:

### Test 1

Java method with no logging.

Expected:

```text
logging gap detected
```

### Test 2

Java method with existing INFO log.

Expected:

```text
existing logging detected
```

### Test 3

Spark JOIN.

Expected:

```text
JOIN finding
HIGH priority
```

### Test 4

Spark filter.

Expected:

```text
FILTER finding
```

### Test 5

Parquet write.

Expected:

```text
OUTPUT finding
```

### Test 6

try/catch without error logging.

Expected:

```text
EXCEPTION finding
```

### Test 7

try/catch with logger.error.

Expected:

```text
existing exception logging detected
```

### Test 8

Sensitive logging.

Example:

```java
logger.info("patient={}", patient);
```

Expected:

```text
sensitive logging warning
```

---

# 34. LLM TESTING

Create a fixed set of representative code snippets.

Store expected characteristics.

For example:

```text
JOIN:
Expected priority = HIGH
Expected AI usefulness = HIGH

simple select:
Expected priority = LOW

Parquet output:
Expected priority = HIGH
```

Do not require exact wording.

Evaluate structured fields.

---

# 35. LOGGING RECOMMENDATION QUALITY

The tool should distinguish:

```text
MISSING
WEAK
PARTIAL
GOOD
```

Example:

```text
MISSING:
No relevant logging.

WEAK:
Logging exists but contains no useful context.

PARTIAL:
Some required context exists.

GOOD:
Important operational context is captured.
```

---

# 36. OPTIONAL FUTURE FEATURE — PATCH GENERATION

DO NOT implement in MVP.

After the advisory system is stable, add:

```bash
java-log-advisor suggest-patch
```

Output a Git diff.

Example:

```diff
+ logger.info(
+     "Spark join completed runId={} leftCount={} rightCount={} outputCount={}",
+     runId,
+     leftCount,
+     rightCount,
+     outputCount
+ );
```

The patch must:

* never automatically commit
* never automatically push
* never modify production code without approval
* require developer review

---

# 37. FUTURE PHASE — AI-READY RUNTIME

Once logging has been implemented:

```text
Java + Spark
     ↓
Structured Logs
     ↓
Metrics
     ↓
Parquet Metadata
     ↓
Run History
     ↓
Local LLM
```

Then build:

```text
Pipeline Copilot
```

Questions:

```text
Why did today's job fail?

Why did output records decrease?

Which stage caused the anomaly?

What changed compared with yesterday?

Which Spark operation is taking longer?

Which dataset has unusual record loss?
```

---

# 38. FUTURE RAG

Only after runtime observability exists, consider RAG.

Potential sources:

```text
Java source
README
architecture docs
metadata definitions
logging standards
pipeline definitions
historical run summaries
```

Do NOT start with patient records.

---

# 39. FUTURE GRAPH / LINEAGE

A later version may create:

```text
Input Dataset
      ↓
Spark Transformation
      ↓
Join
      ↓
Filter
      ↓
Output Parquet
```

This can eventually support AI-powered lineage questions.

Do not implement Graph DB in MVP.

---

# 40. SECURITY REQUIREMENTS

The tool must:

* default to local Ollama
* never call external LLM APIs
* never upload source code
* never read patient data by default
* mask secrets
* avoid PHI recommendations
* log LLM calls locally without source-code contents
* make the model endpoint configurable
* provide a clear offline mode

Add:

```yaml
privacy:
  allow_external_llm: false
  scan_patient_data: false
  mask_secrets: true
```

If `allow_external_llm=false`, the tool must reject external endpoints.

---

# 41. OBSERVABILITY OF THE ADVISOR ITSELF

The advisor should also have basic logging.

Log:

```text
scan_start
scan_end
files_scanned
methods_analyzed
findings_created
llm_calls
llm_failures
cache_hits
report_generated
```

Do not log source-code contents.

---

# 42. IMPLEMENTATION ORDER

Claude MUST implement in this order.

## Milestone 1

Project scanner.

Deliver:

```text
project_summary.json
```

---

## Milestone 2

Java parser.

Deliver:

```text
classes
methods
line numbers
imports
exceptions
```

---

## Milestone 3

Spark detector.

Deliver detection for:

```text
read
write
join
filter
groupBy
agg
deduplication
actions
```

---

## Milestone 4

Existing logging detector.

Deliver:

```text
logger.info
logger.warn
logger.error
logger.debug
```

---

## Milestone 5

Deterministic rule engine.

Deliver:

```text
findings.json
```

No LLM yet.

---

## Milestone 6

Markdown report without LLM.

This establishes a working baseline.

---

## Milestone 7

Ollama integration.

Test:

```text
ollama running
model available
simple prompt
structured response
```

---

## Milestone 8

LLM analysis of high-priority findings.

---

## Milestone 9

Final Markdown + JSON report.

---

## Milestone 10

Unit tests + integration tests.

---

## Milestone 11

AI observability scoring.

---

## Milestone 12

Performance optimization and caching.

---

# 43. DEFINITION OF DONE FOR MVP

MVP is complete when:

```text
✓ Can scan a Java + Spark repository

✓ Detects Java classes and methods

✓ Detects common Spark operations

✓ Detects Spark input/output

✓ Detects joins

✓ Detects filters

✓ Detects aggregations

✓ Detects exceptions

✓ Detects existing logging

✓ Applies configurable logging rules

✓ Produces deterministic findings

✓ Connects to local Ollama

✓ Sends only relevant code context

✓ Receives structured LLM recommendations

✓ Generates Markdown report

✓ Generates JSON report

✓ Calculates deterministic AI-readiness score

✓ Masks obvious secrets

✓ Does not process patient data

✓ Has unit tests

✓ Can run completely without LLM using --no-llm
```

---

# 44. EXAMPLE FINAL USER EXPERIENCE

Developer runs:

```bash
java-log-advisor scan \
    --project ~/projects/my-spark-project
```

Tool displays:

```text
AI-Ready Logging Advisor
────────────────────────

Project: ClinicalSparkPipeline

Scanning...
████████████████████ 100%

Files:              327
Methods:            1,284
Spark operations:   2,941
Existing logs:        418
Findings:             161

Running Local Qwen analysis...
████████████████████ 100%

AI Observability Score: 58/100

HIGH:    47
MEDIUM:  83
LOW:     31

Report:
./logging-report/logging_advisory_report.md
```

The developer opens the report and sees exactly where logging should be improved.

---

# 45. WHAT NOT TO BUILD IN VERSION 1

Explicitly DO NOT build:

```text
✗ Vector database
✗ Graph database
✗ RAG
✗ Autonomous agent
✗ Multi-agent system
✗ Patient-data analysis
✗ Automatic source modification
✗ Automatic Git commit
✗ Automatic Git push
✗ Cloud LLM integration
✗ Production auto-remediation
✗ Complex UI
```

The goal is a reliable CLI-based POC first.

---

# 46. SUCCESS CRITERIA

The POC should answer this question:

> "Can a Local LLM, combined with deterministic Java/Spark code analysis, identify meaningful missing logging points that will make this application easier to monitor, debug, analyze, and eventually operate using GenAI?"

The tool should demonstrate that:

```text
Code
 ↓
Observability gaps
 ↓
Structured logging recommendations
 ↓
AI-readiness
```

can be automated locally.

---

# 47. CLAUDE EXECUTION INSTRUCTION

Implement this project incrementally.

Before writing large amounts of code:

1. Inspect the target Java + Spark repository.
2. Determine its Java version.
3. Determine Maven/Gradle.
4. Identify Spark version.
5. Identify logging framework.
6. Identify the actual Spark coding patterns used.
7. Produce a short implementation assessment.
8. Then implement Milestone 1 only.
9. Run tests.
10. Show the result.
11. Proceed to the next milestone only after the previous milestone works.

Do NOT make assumptions about the target project's structure.

Do NOT rewrite the existing Java + Spark project.

The advisor must remain a separate tool/repository.

The advisor must be read-only against the target project during MVP.

Every recommendation must include:

```text
file
class
method
line
operation
priority
reason
recommended fields
AI usefulness
security considerations
```

The implementation should favor simple, testable components over framework-heavy architecture.

The primary success criterion is **useful recommendations**, not the number of technologies used.

# 48. TBD

# 49. LOCAL LLM MODEL STRATEGY

## 49.1 Primary Model

The initial recommended model for the AI-Ready Logging Advisor is:

```text
Qwen3-Coder 30B
```

Run locally through:

```text
Ollama
```

Recommended Ollama model identifier:

```text
qwen3-coder:30b
```

The model is selected because the advisor's primary task is **software-engineering/code reasoning**, rather than general conversation.

The model needs to understand:

* Java
* Apache Spark
* Spark SQL/DataFrame APIs
* Java control flow
* exception handling
* logging frameworks
* data-processing pipelines
* transformation boundaries
* code context
* relationships between methods
* observability requirements

---

## 49.2 Model Must Be Configurable

Do NOT hard-code:

```text
qwen3-coder:30b
```

inside the application.

Use configuration:

```yaml
llm:
  provider: ollama
  host: http://localhost:11434
  model: qwen3-coder:30b
  temperature: 0.1
  timeout_seconds: 120
```

The CLI should also allow:

```bash
java-log-advisor scan \
    --project ./my-project \
    --model qwen3-coder:30b
```

This allows future comparison with:

```text
qwen3-coder:8b
qwen3-coder:14b
other local coding models
```

without changing application code.

---

# 49.3 Why Qwen3-Coder 30B

The advisor is a code-analysis application.

The LLM must reason about questions such as:

```text
Is this Spark join an important observability point?

Where does the actual Spark execution occur?

Does the existing logging provide enough context?

What metrics would help identify abnormal record loss?

Could this exception path hide the actual processing stage?

Would this logging recommendation expose sensitive information?
```

A coding-specialized model is therefore preferred over a small general-purpose conversational model.

The model should be used primarily for:

```text
Code understanding
Contextual reasoning
Recommendation prioritization
Observability reasoning
Security/sensitivity reasoning
Recommendation explanation
```

It should NOT be responsible for deterministic source-code discovery.

---

# 49.4 Model Responsibility Boundary

The architecture must remain:

```text
                 Java + Spark Code
                        │
                        ▼
              ┌───────────────────┐
              │ Static Analyzer    │
              │                   │
              │ AST               │
              │ Spark detection   │
              │ Log detection     │
              │ Exception detect  │
              └─────────┬─────────┘
                        │
                  Deterministic
                    findings
                        │
                        ▼
              ┌───────────────────┐
              │ Rule Engine       │
              └─────────┬─────────┘
                        │
                 Important findings
                        │
                        ▼
              ┌───────────────────┐
              │ Qwen3-Coder 30B   │
              │     LOCAL         │
              └─────────┬─────────┘
                        │
                        ▼
                 Explanation +
                 Recommendation
```

The LLM must NOT be responsible for:

```text
✗ Finding every Java file
✗ Counting all methods
✗ Detecting every logger statement
✗ Determining exact line numbers
✗ Calculating deterministic scores
✗ Parsing the complete repository
```

Those tasks belong to the scanner.

---

# 49.5 Local-Only Requirement

The MVP must support completely local execution.

Expected architecture:

```text
Developer Machine
│
├── AI-Ready Logging Advisor
│
├── Ollama
│
└── Qwen3-Coder 30B
```

No external LLM API should be required.

The default configuration:

```yaml
privacy:
  allow_external_llm: false
```

If an external endpoint is configured while this value is false, the application must refuse to run the LLM analysis.

---

# 49.6 Model Availability Check

Before scanning with LLM mode, verify that Ollama is available.

Example:

```text
Checking Ollama...
✓ Ollama available

Checking model...
✓ qwen3-coder:30b available

Starting analysis...
```

If unavailable:

```text
Ollama is not available.

Run the advisor with:

--no-llm

or start Ollama and retry.
```

The deterministic scanner must still work without the LLM.

---

# 49.7 Model Capability Test

Add a command:

```bash
java-log-advisor doctor
```

It should test:

```text
✓ Ollama reachable
✓ Model available
✓ Model response received
✓ Structured JSON response works
✓ Required prompt format supported
```

Example:

```text
AI-Ready Logging Advisor Diagnostics

Ollama:
    ✓ Connected

Model:
    qwen3-coder:30b
    ✓ Available

Test generation:
    ✓ Passed

Structured output:
    ✓ Passed

Ready for analysis.
```

---

# 49.8 Model Benchmarking

The architecture should allow benchmarking multiple local models.

Example:

```bash
java-log-advisor benchmark \
    --project ./sample-project \
    --models qwen3-coder:8b,qwen3-coder:30b
```

Measure:

```text
model
total_llm_calls
successful_calls
failed_calls
average_response_time
total_analysis_time
structured_output_success_rate
recommendation_count
```

Additionally, manually evaluate recommendation quality.

Create a benchmark dataset containing representative Java + Spark examples:

```text
JOIN
FILTER
AGGREGATION
PARQUET_WRITE
EXCEPTION
SPARK_READ
COMPLEX_TRANSFORMATION
```

---

# 49.9 Model Evaluation Criteria

Do not judge the model only by response quality.

Evaluate:

### 1. Correctness

Does the recommendation actually apply to the code?

### 2. Relevance

Is the suggested logging point useful?

### 3. Completeness

Did it identify important observability gaps?

### 4. Safety

Did it avoid recommending PHI/PII logging?

### 5. Consistency

Does it produce similar recommendations for similar code?

### 6. Structured output reliability

Does it consistently return the required schema?

### 7. Performance

How long does analysis take?

### 8. Token efficiency

How much context is required for useful reasoning?

---

# 49.10 Start With a Smaller Model if Hardware Requires It

Qwen3-Coder 30B is the preferred target model, but the application must not assume that every developer machine can run it efficiently.

If the machine has limited RAM/unified memory, use a smaller coding model for development and testing.

For example:

```text
Development:
qwen3-coder:8b

Production/stronger local analysis:
qwen3-coder:30b
```

The code must remain identical apart from configuration.

The purpose of the POC is to evaluate whether the **architecture and recommendations are useful**, not to force a specific model onto insufficient hardware.

---

# 49.11 Context Management

Do NOT send the entire repository to Qwen3-Coder 30B.

For each LLM request provide only:

```text
Project context
+
File context
+
Class context
+
Method context
+
Relevant code snippet
+
Detected Spark operations
+
Existing logging
+
Applicable logging rules
+
Deterministic finding
```

Example:

```text
Project:
ClinicalSparkPipeline

File:
PatientProcessor.java

Class:
PatientProcessor

Method:
processPatients()

Relevant lines:
135-170

Detected:
JOIN
FILTER

Existing logging:
INFO at line 121
No logging around JOIN
No logging around FILTER

Rule:
JOIN = HIGH priority
Required fields:
run_id
left_count
right_count
output_count
join_type
duration
```

This is the preferred context strategy.

---

# 49.12 Token Optimization

The system must minimize unnecessary LLM calls.

Use this pipeline:

```text
327 Java files
       ↓
Static analysis
       ↓
1,284 methods
       ↓
2,941 Spark operations
       ↓
161 findings
       ↓
Priority filtering
       ↓
75 important findings
       ↓
Qwen3-Coder 30B
```

Only important findings should normally reach the LLM.

The CLI should support:

```bash
--llm-priority high
```

to analyze only high-priority findings.

Also support:

```bash
--llm-limit 50
```

to limit the number of LLM calls.

---

# 49.13 LLM Cache

Cache LLM responses.

Cache key should include:

```text
file content hash
method code hash
rule version
prompt version
model name
```

Example:

```text
cache/
    <hash>.json
```

If the same code is analyzed again:

```text
Cache hit
```

No new LLM call should be required.

Changing the model or prompt version must invalidate the appropriate cache entry.

---

# 49.14 Temperature

Default:

```yaml
temperature: 0.1
```

The objective is consistent engineering recommendations rather than creative output.

The temperature must be configurable.

---

# 49.15 LLM Failure Handling

If Qwen fails:

```text
timeout
connection error
invalid JSON
model unavailable
unexpected response
```

the scanner must NOT fail.

Instead:

```text
Finding:
JOIN at PatientProcessor.java:143

LLM analysis:
FAILED

Reason:
Ollama timeout

Deterministic recommendation:
HIGH
```

The report must clearly distinguish:

```text
deterministic analysis
```

from:

```text
LLM analysis
```

---

# 49.16 Model Selection Future-Proofing

The architecture should use an abstraction such as:

```text
LLMProvider
    │
    └── OllamaProvider
```

Future implementations may include:

```text
OllamaProvider
OpenAIProvider
OtherLocalProvider
```

However, only `OllamaProvider` is required for MVP.

Do not implement cloud providers in MVP.

---

# 49.17 Recommended Initial Configuration

Use:

```yaml
llm:
  enabled: true
  provider: ollama
  host: http://localhost:11434
  model: qwen3-coder:30b
  temperature: 0.1
  timeout_seconds: 120
  max_retries: 1
  cache_enabled: true

privacy:
  allow_external_llm: false
  scan_patient_data: false
  mask_secrets: true
```

---

# 49.18 Initial Setup Documentation

README must explain:

```text
1. Install Ollama
2. Start Ollama
3. Pull Qwen3-Coder 30B
4. Verify model
5. Run java-log-advisor doctor
6. Run scanner
```

Example:

```bash
ollama pull qwen3-coder:30b

java-log-advisor doctor

java-log-advisor scan \
    --project /path/to/java-spark-project
```

The README should also explain how to switch models:

```bash
java-log-advisor scan \
    --project ./project \
    --model qwen3-coder:8b
```

---

# 49.19 Model Strategy Summary

The MVP model strategy is:

```text
                 LOCAL OLLAMA
                      │
                      ▼
              Qwen3-Coder 30B
                      │
                      ▼
              Code reasoning
                      │
                      ▼
          Logging recommendations
```

But the architecture must support:

```text
Qwen3-Coder 8B
Qwen3-Coder 14B
Qwen3-Coder 30B
Future local coding models
```

without source-code changes.

The initial recommendation is:

**Use Qwen3-Coder 30B as the primary evaluation model, but keep Qwen3-Coder 8B available as a lightweight development/benchmark model.**

---

# 50. UPDATED IMPLEMENTATION MILESTONES

The complete implementation order is now:

```text
Milestone 1
Project discovery

Milestone 2
Java AST/source analysis

Milestone 3
Spark operation detection

Milestone 4
Existing logging detection

Milestone 5
Deterministic logging rules

Milestone 6
Non-LLM report

Milestone 7
Ollama integration

Milestone 8
Qwen3-Coder 30B integration

Milestone 9
Structured LLM response validation

Milestone 10
LLM recommendations

Milestone 11
Markdown + JSON report

Milestone 12
AI observability scoring

Milestone 13
LLM caching

Milestone 14
Security/secret masking

Milestone 15
Unit + integration tests

Milestone 16
Model benchmarking

Milestone 17
Optional logging patch generation
```

Claude must complete and test each milestone before moving to the next.

---

# 51. FIRST CLAUDE IMPLEMENTATION REQUEST

When starting implementation, provide Claude with the plan and instruct it:

"Do not implement the complete system yet.

First inspect my Java + Spark repository.

Identify:

* Java version
* Maven/Gradle
* Spark version
* logging framework
* source structure
* major Spark APIs used
* existing logging patterns
* test framework

Then propose how the generic advisor architecture should adapt to this specific repository.

Do not modify the target Java + Spark project.

After inspection, implement Milestone 1 only."

# 52. LOCAL DATABASE — SQLITE

## 52.1 Decision

Use **SQLite** as the local database for the AI-Ready Logging Advisor.

Do NOT introduce:

* PostgreSQL
* MySQL
* MongoDB
* Redis
* Vector database
* Graph database

in the MVP.

SQLite is sufficient because the advisor stores structured analysis metadata rather than large clinical datasets.

The database must remain completely local.

---

# 52.2 Why We Need a Database

The first scan could technically work without a database:

```text
Code
 ↓
Scanner
 ↓
LLM
 ↓
Report
```

However, a database becomes valuable when running the advisor repeatedly.

For example:

```text
Scan #1
    ↓
58/100 AI Observability

Developer adds logging

Scan #2
    ↓
72/100 AI Observability

Developer adds more logging

Scan #3
    ↓
84/100 AI Observability
```

Without a database, comparing these scans becomes difficult.

SQLite allows the tool to maintain:

* scan history
* findings
* recommendations
* source-code hashes
* rule versions
* model information
* LLM analysis results
* AI-readiness scores
* recommendation status

---

# 52.3 Database Architecture

Use:

```text
                    Java + Spark Code
                           │
                           ▼
                    Static Analyzer
                           │
                           ▼
                     Rule Engine
                           │
                           ├──────────────┐
                           ▼              ▼
                       SQLite          Local LLM
                           │              │
                           │              ▼
                           │        LLM Recommendations
                           │              │
                           └───────┬──────┘
                                   ▼
                              SQLite
                                   │
                                   ▼
                               Reports
```

SQLite is the persistence layer.

---

# 52.4 Database Location

Default:

```text
.ai-ready-log-advisor/
    advisor.db
```

inside the advisor's working directory.

Do NOT put the database inside the target Java + Spark source repository by default.

Alternative configurable location:

```bash
java-log-advisor scan \
    --project /path/to/project \
    --database ./data/advisor.db
```

---

# 52.5 Database Must NOT Store Patient Data

The database must never contain:

* patient records
* patient IDs
* names
* addresses
* medical information
* diagnosis values
* medication values
* clinical notes

The database stores **code-analysis metadata only**.

Example:

```text
GOOD:
PatientProcessor.java
JOIN
line 143
HIGH
missing record-count logging

BAD:
Patient ID 12345
Diagnosis = diabetes
```

---

# 52.6 Suggested Database Schema

## projects

Stores analyzed projects.

```text
projects
--------
id
name
path
language
java_version
spark_version
build_system
logging_framework
created_at
updated_at
```

---

## scans

One record per scan.

```text
scans
-----
id
project_id
started_at
completed_at
status

files_scanned
classes_scanned
methods_scanned
spark_operations
existing_logs
findings_count

llm_enabled
llm_provider
llm_model

ai_observability_score
rule_version
scanner_version
```

Example:

```text
scan_id: 42
project: ClinicalSparkPipeline
model: qwen3-coder:30b
score: 58
```

---

# 52.7 source_files

Store metadata about source files.

```text
source_files
------------
id
scan_id
path
file_hash
language
line_count
class_count
method_count
```

Do NOT store complete source code in SQLite.

The actual source remains in the target repository.

The hash allows detection of changes between scans.

---

# 52.8 methods

Store discovered methods.

```text
methods
-------
id
source_file_id
class_name
method_name
start_line
end_line
return_type
parameter_count
```

---

# 52.9 spark_operations

Store detected Spark operations.

```text
spark_operations
----------------
id
method_id
operation_type
line
details
priority
```

Examples:

```text
JOIN
FILTER
GROUP_BY
AGGREGATION
PARQUET_WRITE
PARQUET_READ
SPARK_ACTION
```

Do not store patient-level data in `details`.

---

# 52.10 existing_logs

Store detected logging statements.

```text
existing_logs
-------------
id
method_id
line
level
logger_type
message_pattern
structured
```

Example:

```text
level: INFO
line: 143
structured: false
```

Do not store sensitive values extracted from source code.

---

# 52.11 findings

Store deterministic findings.

```text
findings
--------
id
scan_id
source_file_id
method_id

category
operation
line
priority

existing_logging
logging_quality

rule_id
status
```

Possible status:

```text
OPEN
ACCEPTED
REJECTED
IMPLEMENTED
FALSE_POSITIVE
```

---

# 52.12 recommendations

Store LLM recommendations.

```text
recommendations
---------------
id
finding_id

recommendation
reason

recommended_fields
do_not_log

ai_usefulness
ai_use_cases

model
prompt_version

created_at
```

Store structured JSON where appropriate.

---

# 52.13 LLM Runs

Track LLM execution separately.

```text
llm_runs
--------
id
scan_id
finding_id

provider
model

started_at
completed_at

duration_ms
status

input_tokens
output_tokens

cache_hit
error_type
```

Do NOT store the complete prompt or patient data.

If storing prompt hashes is useful:

```text
prompt_hash
```

may be stored instead.

---

# 52.14 Scores

Store scoring information.

```text
scores
------
id
scan_id

job_lifecycle
input_visibility
transformation_visibility
join_visibility
output_visibility
exception_visibility
structured_logging
run_correlation

overall_score
```

This makes historical comparison easy.

---

# 52.15 Recommendation History

A recommendation should survive future scans.

For example:

```text
Scan 1
──────
PatientProcessor.java:143
JOIN
Missing logging
Status: OPEN


Developer implements logging


Scan 2
──────
PatientProcessor.java:143
JOIN
Structured logging detected
Status: IMPLEMENTED
```

The system should use:

```text
file_hash
method
operation
line/context
rule_id
```

to determine whether a previous finding is still relevant.

Do not depend solely on line numbers because code can move.

---

# 52.16 Database Migrations

Use a simple migration mechanism.

Recommended:

```text
migrations/
    001_initial.sql
    002_add_llm_runs.sql
    003_add_scores.sql
```

The advisor should automatically initialize the database:

```bash
java-log-advisor init
```

or initialize it automatically on first scan.

---

# 52.17 Database CLI

Add:

```bash
java-log-advisor history
```

Example:

```text
Scan History

ID   Date         Score   Findings   Model
------------------------------------------------
1    2026-08-20   42      183        qwen3-coder:8b
2    2026-08-25   58      161        qwen3-coder:30b
3    2026-08-31   71      104        qwen3-coder:30b
```

Add:

```bash
java-log-advisor compare --scan 2 --scan 3
```

Output:

```text
AI Observability Improvement
─────────────────────────────

Previous: 58
Current: 71
Improvement: +13

HIGH findings:
Previous: 47
Current: 29
Resolved: 18
```

---

# 52.18 Finding Lifecycle

Implement:

```text
OPEN
  ↓
REVIEWED
  ↓
ACCEPTED
  ↓
IMPLEMENTED
```

Alternative:

```text
OPEN
  ↓
FALSE_POSITIVE
```

or:

```text
OPEN
  ↓
REJECTED
```

The developer should eventually be able to mark recommendations.

---

# 52.19 CLI Finding Management

Future MVP+ commands:

```bash
java-log-advisor findings
```

```bash
java-log-advisor findings --priority high
```

```bash
java-log-advisor finding show 123
```

```bash
java-log-advisor finding accept 123
```

```bash
java-log-advisor finding reject 123
```

```bash
java-log-advisor finding implemented 123
```

These commands should update SQLite.

---

# 52.20 Database and Reports

Reports should be generated from the database where possible.

Architecture:

```text
Scan
 ↓
SQLite
 ↓
Report Generator
 ├── Markdown
 └── JSON
```

This means reports can be regenerated without rescanning the repository.

Example:

```bash
java-log-advisor report --scan 42
```

---

# 52.21 Database and LLM Cache

The SQLite database may also maintain LLM cache metadata.

However, avoid storing huge model responses directly in SQLite during MVP.

Prefer:

```text
cache/
    <hash>.json
```

and store only:

```text
cache_key
model
prompt_version
response_path
created_at
```

in SQLite.

This keeps the database small.

---

# 52.22 Database Performance

SQLite should be sufficient for:

```text
hundreds of projects
thousands of scans
millions of findings
```

for a local developer tool.

Add indexes on:

```text
scans.project_id
findings.scan_id
findings.priority
findings.status
findings.source_file_id
recommendations.finding_id
llm_runs.scan_id
```

Do not prematurely introduce a server database.

---

# 52.23 Database Privacy

The database itself should be treated as local developer data.

Do not commit:

```text
advisor.db
```

to Git.

Add:

```text
.ai-ready-log-advisor/
*.db
*.sqlite
*.sqlite3
cache/
```

to `.gitignore`.

The advisor's own source code can be committed normally.

---

# 52.24 Updated Architecture

The complete MVP architecture becomes:

```text
┌───────────────────────────────────────────┐
│        Java + Apache Spark Project        │
└───────────────────┬───────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │ Static Code Analyzer  │
        └───────────┬───────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │ Deterministic Rules   │
        └───────────┬───────────┘
                    │
             Findings
                    │
          ┌─────────┴──────────┐
          ▼                    ▼
      SQLite               Local Qwen
          │                    │
          │             Recommendations
          │                    │
          └─────────┬──────────┘
                    ▼
                 SQLite
                    │
          ┌─────────┴──────────┐
          ▼                    ▼
       Reports              History
          │                    │
          ▼                    ▼
      Markdown             Comparison
        JSON
```

---

# 52.25 Updated Implementation Order

The implementation milestones should now be:

```text
1. Project discovery
2. Java AST/source analysis
3. Spark operation detection
4. Existing logging detection
5. Deterministic logging rules
6. SQLite database + schema
7. Non-LLM report
8. Ollama integration
9. Qwen3-Coder 30B integration
10. Structured LLM response validation
11. LLM recommendations
12. Markdown + JSON report
13. AI observability scoring
14. Scan history
15. Scan comparison
16. LLM caching
17. Security/secret masking
18. Unit + integration tests
19. Model benchmarking
20. Optional logging patch generation
```

SQLite should therefore be introduced **before LLM integration**, because it provides a stable persistence layer for deterministic findings and later LLM results.

---

# 52.26 MVP Database Definition of Done

The database implementation is complete when:

```text
✓ SQLite database created automatically
✓ Project information stored
✓ Scan history stored
✓ Source-file metadata stored
✓ Methods stored
✓ Spark operations stored
✓ Existing logging stored
✓ Deterministic findings stored
✓ LLM recommendations stored
✓ AI-readiness score stored
✓ LLM execution metadata stored
✓ Findings have lifecycle status
✓ Scan comparison works
✓ Database contains no patient data
✓ Database contains no source-code dumps
✓ Database is excluded from Git
✓ Schema migration mechanism exists
✓ Database tests exist
```

---

# 52.27 Future Database Evolution

Do NOT implement these in MVP.

Potential future additions:

```text
PostgreSQL
Central team database
Multi-user dashboard
Historical production logs
Runtime metrics
Distributed scan results
Organization-wide observability score
```

These should only be considered if the tool evolves from a local developer tool into a team/platform product.

