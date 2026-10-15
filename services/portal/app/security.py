"""Cookie signing (HMAC-SHA256) and salted IP hashing."""

from __future__ import annotations

import hashlib
import hmac

from harnessguard_core.config import get_settings


def sign_value(value: str) -> str:
    secret = get_settings().session_secret.encode()
    sig = hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{value}.{sig}"


def verify_signed(signed: str | None) -> str | None:
    if not signed or "." not in signed:
        return None
    value, sig = signed.rsplit(".", 1)
    expected = sign_value(value).rsplit(".", 1)[1]
    if hmac.compare_digest(sig, expected):
        return value
    return None


def ip_hash(ip: str) -> str:
    salt = get_settings().ip_hash_salt
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()
