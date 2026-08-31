"""Source-code safety layer: secret masking and PHI/PII heuristics.

The advisor is a *code analyzer*. Before any code snippet is sent to the LLM we
scrub obvious secrets, and we screen both existing log statements and generated
recommendations for sensitive fields.
"""
from __future__ import annotations

import re
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Secret masking
# ---------------------------------------------------------------------------
_SECRET_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'(?i)(password|passwd|pwd)\s*[:=]\s*["\']?[^"\'\s,;)]+'), r'\1=***MASKED***'),
    (re.compile(r'(?i)(secret|api[_-]?key|apikey|access[_-]?key|client[_-]?secret)\s*[:=]\s*["\']?[^"\'\s,;)]+'),
     r'\1=***MASKED***'),
    (re.compile(r'(?i)(token|bearer|authorization)\s*[:=]\s*["\']?[^"\'\s,;)]+'), r'\1=***MASKED***'),
    # JDBC / connection strings with credentials
    (re.compile(r'(?i)(jdbc:[a-z]+://[^"\'\s]*[?&](?:user|password)=)[^"\'\s&]+'), r'\1***MASKED***'),
    # AWS-style access keys
    (re.compile(r'AKIA[0-9A-Z]{16}'), '***MASKED_AWS_KEY***'),
    # Long base64-ish literals assigned to something
    (re.compile(r'(?i)(key|secret|token)\s*=\s*"[A-Za-z0-9+/]{24,}={0,2}"'), r'\1="***MASKED***"'),
]


def mask_secrets(text: str) -> str:
    """Return *text* with obvious secrets replaced by placeholders."""
    if not text:
        return text
    out = text
    for pattern, repl in _SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out


# ---------------------------------------------------------------------------
# Sensitive-field / PHI-PII detection
# ---------------------------------------------------------------------------
SENSITIVE_TERMS = [
    "patient", "patientid", "patient_id", "patientname", "patient_name",
    "mrn", "ssn", "dob", "date_of_birth", "birthdate",
    "diagnosis", "icd", "medication", "prescription", "drug",
    "clinical", "medical_history", "medicalhistory", "notes", "clinical_note",
    "address", "street", "zipcode", "postcode", "phone", "phone_number",
    "email", "e_mail", "firstname", "first_name", "lastname", "last_name",
    "full_name", "fullname", "insurance", "policy_number",
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "credential", "access_token", "private_key",
]

_SENSITIVE_RE = re.compile(
    r'(?i)\b(' + '|'.join(re.escape(t) for t in SENSITIVE_TERMS) + r')\b'
)

# whole-object logging like  logger.info("patient={}", patient)
_OBJECT_LOG_RE = re.compile(
    r'(?i)\b(request|response|body|payload|patient|record|entity|dto|user)\b\s*[})\]]?\s*$'
)


def find_sensitive_terms(text: str) -> List[str]:
    if not text:
        return []
    return sorted({m.group(1).lower() for m in _SENSITIVE_RE.finditer(text)})


def looks_like_sensitive_log(message_pattern: str, args_blob: str = "") -> bool:
    """Heuristic: does this log statement appear to emit sensitive data?"""
    blob = f"{message_pattern} {args_blob}"
    if find_sensitive_terms(blob):
        return True
    if _OBJECT_LOG_RE.search(args_blob.strip()):
        return True
    return False


DEFAULT_DO_NOT_LOG = [
    "patient identifiers",
    "patient name / demographics",
    "clinical values (diagnosis, medication, notes)",
    "full request/response bodies or entity objects",
    "credentials, tokens, secrets, connection strings",
]


def sanitize_recommended_fields(fields: List[str]) -> Tuple[List[str], List[str]]:
    """Split *fields* into (safe, rejected) using the sensitive-term screen."""
    safe, rejected = [], []
    for f in fields or []:
        if find_sensitive_terms(f):
            rejected.append(f)
        else:
            safe.append(f)
    return safe, rejected
