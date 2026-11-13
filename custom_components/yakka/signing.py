"""Verifying Yakka's webhook signatures (no Home Assistant imports)."""

from __future__ import annotations

import hashlib
import hmac
import time

# Freshness window in seconds, as Yakka's docs recommend.
MAX_SKEW = 300


def verify_signature(
    secret: str,
    timestamp: str | None,
    signature: str | None,
    body: bytes,
    now: float | None = None,
) -> bool:
    """Check ``X-Signature`` (HMAC-SHA256 of ``"{timestamp}.{raw body}"``)."""
    if not timestamp or not signature or not timestamp.isdigit():
        return False
    if abs((time.time() if now is None else now) - int(timestamp)) > MAX_SKEW:
        return False
    expected = (
        "sha256="
        + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(signature, expected)
