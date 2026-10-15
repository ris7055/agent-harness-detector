"""Idempotent seed data (SPEC section 8.2).

Demo users all share the documented demo password ``Seroja@2026``.
Passwords are hashed with PBKDF2 (stdlib); the hash format is
``pbkdf2$<iterations>$<salt_hex>$<hash_hex>``.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import random

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import tasks as tasklib

_PBKDF2_ITERATIONS = 120_000

# Deterministic demo data (fixed seed so re-runs and tests are stable).
_SEED_USERS = [
    ("aisyah", "Aisyah Rahman"),
    ("daniel", "Daniel Wong"),
    ("meiling", "Mei Ling Choo"),
    ("ravi", "Ravi Kumar"),
    ("demo", "Demo User"),
]


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iters, salt, digest = stored.split("$")
        if scheme != "pbkdf2":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iters)
        ).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, AttributeError):
        return False


def seed(s: Session) -> None:
    """Insert demo users/accounts/payees/history if absent. Safe to run repeatedly."""
    if s.execute(text("SELECT 1 FROM users LIMIT 1")).first():
        return

    rng = random.Random(20261015)
    account_seq = 8800_0000_0000

    for username, full_name in _SEED_USERS:
        user_id = s.execute(
            text(
                "INSERT INTO users (username, password_hash, full_name)"
                " VALUES (:u, :p, :n) RETURNING id"
            ),
            {"u": username, "p": hash_password(tasklib.DEMO_PASSWORD), "n": full_name},
        ).scalar_one()

        account_seq += rng.randint(7, 97)
        balance_cents = rng.randint(500_000, 2_500_000)  # RM 5,000-25,000
        account_id = s.execute(
            text(
                "INSERT INTO accounts (user_id, account_number, balance_cents)"
                " VALUES (:u, :acct, :bal) RETURNING id"
            ),
            {"u": user_id, "acct": str(account_seq), "bal": balance_cents},
        ).scalar_one()

        # Two known payees per user (transfer_known tasks reference these).
        for name in rng.sample(tasklib.PAYEE_NAMES, 2):
            s.execute(
                text(
                    "INSERT INTO payees (user_id, name, bank, account_number)"
                    " VALUES (:u, :n, :b, :a)"
                ),
                {
                    "u": user_id,
                    "n": name,
                    "b": rng.choice(tasklib.BANKS),
                    "a": f"{rng.randint(1000,9999)} {rng.randint(1000,9999)} {rng.randint(1000,9999)}",
                },
            )

        # Five past completed transfers ("transactions") per account.
        for _ in range(5):
            s.execute(
                text(
                    "INSERT INTO transfers (account_id, to_name, to_bank, to_account,"
                    " amount_cents, reference, status, created_at)"
                    " VALUES (:a, :n, :b, :acct, :amt, :ref, 'completed',"
                    " now() - (:days || ' days')::interval)"
                ),
                {
                    "a": account_id,
                    "n": rng.choice(tasklib.PAYEE_NAMES),
                    "b": rng.choice(tasklib.BANKS),
                    "acct": str(rng.randint(10**11, 10**12 - 1)),
                    "amt": rng.randint(1_000, 150_000),
                    "ref": rng.choice(tasklib.REFERENCE_WORDS),
                    "days": rng.randint(3, 60),
                },
            )
    s.commit()
