"""Secret-safe helpers used at every integration/logging boundary."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REDACTED = "***"
_SECRET_KEYS = re.compile(
    r"(^|_)(access_?token|refresh_?token|token|secret|password|authorization|cookie|session|webhook)(_id)?$",
    re.IGNORECASE,
)


def mask_secret(value: Any) -> str:
    """Return a useful but non-reversible representation of a secret."""
    if value in (None, ""):
        return ""
    return REDACTED


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return REDACTED
    if not parsed.scheme or not parsed.netloc:
        return value
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    # Bitrix incoming webhook paths contain both a user id and a token.
    path = "/rest/***" if "/rest/" in parsed.path.lower() else parsed.path
    return urlunsplit((parsed.scheme, host, path, "", ""))


def sanitize_payload(value: Any, *, key: str = "") -> Any:
    """Recursively redact credentials, auth headers and secret-bearing URLs."""
    if _SECRET_KEYS.search(key):
        return mask_secret(value)
    if isinstance(value, dict):
        return {str(k): sanitize_payload(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_payload(item, key=key) for item in value]
    if isinstance(value, str) and value.lower().startswith(("http://", "https://")):
        return _safe_url(value)
    return value
