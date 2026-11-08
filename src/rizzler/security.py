"""Security helpers shared by CI and the eventual modular server."""
from __future__ import annotations
import hmac
import re
import secrets
from pathlib import Path

ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
DANGEROUS_PREFIXES = ('AIza', 'sk-', 'ghp_', 'gho_', 'ghs_', 'github_pat_')


def validate_session_id(value: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValueError('Invalid session ID')
    return value


def authenticate(presented: str | None, expected: str) -> bool:
    return bool(expected) and isinstance(presented, str) and hmac.compare_digest(presented, expected)


def new_session_id() -> str:
    return secrets.token_urlsafe(32)


def safe_upload_name(name: str) -> str:
    """Reject directory traversal and misleading filename encodings."""
    if not isinstance(name, str) or not name or len(name) > 100:
        raise ValueError('Invalid filename')
    if name != Path(name).name or '/' in name or '\\' in name:
        raise ValueError('Path separators are not permitted')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,99}', name):
        raise ValueError('Unsafe filename')
    if name.lower().endswith(('.csv', '.xlsx', '.xls')):
        return name
    raise ValueError('Unsupported upload type')


def scrub(text: str, sensitive_values: tuple[str, ...] = ()) -> str:
    """Best-effort log redaction; not a substitute for not logging secrets."""
    value = str(text)
    for secret in sensitive_values:
        if secret:
            value = value.replace(secret, '[REDACTED]')
    value = re.sub(r'AIza[0-9A-Za-z_-]{25,}', '[REDACTED_GOOGLE_KEY]', value)
    value = re.sub(r'(?:sk-(?:proj-)?|ghp_|gho_|ghs_|github_pat_)[A-Za-z0-9_-]{16,}', '[REDACTED_TOKEN]', value)
    return value
