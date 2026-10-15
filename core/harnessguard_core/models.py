"""Thin query helpers over SQLAlchemy text SQL (no ORM models for the prototype)."""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def row_to_dict(row: Any) -> dict[str, Any] | None:
    return dict(row._mapping) if row is not None else None


def get_user_by_username(s: Session, username: str) -> dict | None:
    return row_to_dict(
        s.execute(text("SELECT * FROM users WHERE username=:u"), {"u": username}).first()
    )


def get_user(s: Session, user_id: int) -> dict | None:
    return row_to_dict(
        s.execute(text("SELECT * FROM users WHERE id=:i"), {"i": user_id}).first()
    )


def get_account_for_user(s: Session, user_id: int) -> dict | None:
    return row_to_dict(
        s.execute(
            text("SELECT * FROM accounts WHERE user_id=:u ORDER BY id LIMIT 1"),
            {"u": user_id},
        ).first()
    )


def get_account(s: Session, account_id: int) -> dict | None:
    return row_to_dict(
        s.execute(text("SELECT * FROM accounts WHERE id=:i"), {"i": account_id}).first()
    )


def get_payees_for_user(s: Session, user_id: int) -> list[dict]:
    rows = s.execute(
        text("SELECT * FROM payees WHERE user_id=:u ORDER BY id"), {"u": user_id}
    ).all()
    return [dict(r._mapping) for r in rows]


def ensure_session(
    s: Session,
    session_id: str | _uuid.UUID,
    user_agent: str | None = None,
    ip_hash: str | None = None,
) -> _uuid.UUID:
    sid = _uuid.UUID(str(session_id))
    exists = s.execute(
        text("SELECT 1 FROM sessions WHERE id=:i"), {"i": sid}
    ).first()
    if exists:
        s.execute(text("UPDATE sessions SET last_seen=now() WHERE id=:i"), {"i": sid})
    else:
        s.execute(
            text(
                "INSERT INTO sessions (id, started_at, last_seen, user_agent, ip_hash)"
                " VALUES (:i, now(), now(), :ua, :ip)"
            ),
            {"i": sid, "ua": user_agent, "ip": ip_hash},
        )
    return sid


def set_session_user(s: Session, session_id: str | _uuid.UUID, user_id: int) -> None:
    s.execute(
        text("UPDATE sessions SET user_id=:u, last_seen=now() WHERE id=:i"),
        {"u": user_id, "i": _uuid.UUID(str(session_id))},
    )


def recent_transfers(s: Session, account_id: int, limit: int = 5) -> list[dict]:
    rows = s.execute(
        text(
            "SELECT * FROM transfers WHERE account_id=:a AND status='completed'"
            " ORDER BY created_at DESC, id DESC LIMIT :n"
        ),
        {"a": account_id, "n": limit},
    ).all()
    return [dict(r._mapping) for r in rows]


def create_transfer(
    s: Session,
    account_id: int,
    session_id: str | _uuid.UUID | None,
    to_name: str,
    to_bank: str,
    to_account: str,
    amount_cents: int,
    reference: str,
    status: str,
    otp_code: str | None = None,
) -> int:
    return s.execute(
        text(
            "INSERT INTO transfers (account_id, session_id, to_name, to_bank, to_account,"
            " amount_cents, reference, status, otp_code)"
            " VALUES (:a, :sid, :n, :b, :acct, :amt, :ref, :st, :otp) RETURNING id"
        ),
        {
            "a": account_id,
            "sid": _uuid.UUID(str(session_id)) if session_id else None,
            "n": to_name,
            "b": to_bank,
            "acct": to_account,
            "amt": amount_cents,
            "ref": reference,
            "st": status,
            "otp": otp_code,
        },
    ).scalar_one()


def get_transfer(s: Session, transfer_id: int) -> dict | None:
    return row_to_dict(
        s.execute(text("SELECT * FROM transfers WHERE id=:i"), {"i": transfer_id}).first()
    )


def debit_account(s: Session, account_id: int, amount_cents: int) -> None:
    s.execute(
        text(
            "UPDATE accounts SET balance_cents = balance_cents - :amt"
            " WHERE id=:a AND balance_cents >= :amt"
        ),
        {"amt": amount_cents, "a": account_id},
    )


def record_label(
    s: Session,
    session_id: str | _uuid.UUID,
    label: str,
    variant: str | None = None,
    collector: str | None = None,
    task_id: str | None = None,
) -> None:
    """Insert ground-truth label once per session (never a model input)."""
    s.execute(
        text(
            "INSERT INTO session_labels (session_id, label, variant, collector, task_id)"
            " VALUES (:sid, :l, :v, :c, :t) ON CONFLICT (session_id) DO NOTHING"
        ),
        {"sid": _uuid.UUID(str(session_id)), "l": label, "v": variant, "c": collector, "t": task_id},
    )


def get_label(s: Session, session_id: str | _uuid.UUID) -> dict | None:
    return row_to_dict(
        s.execute(
            text("SELECT * FROM session_labels WHERE session_id=:i"),
            {"i": _uuid.UUID(str(session_id))},
        ).first()
    )


def record_decision(
    s: Session,
    session_id: str | _uuid.UUID | None,
    action: str,
    decision: str,
    score: float | None = None,
    band: str | None = None,
    model_version: str | None = None,
    latency_ms: int | None = None,
    features: dict | None = None,
) -> int:
    import json

    return s.execute(
        text(
            "INSERT INTO decisions (session_id, action, score, band, decision,"
            " model_version, latency_ms, features)"
            " VALUES (:sid, :a, :sc, :b, :d, :mv, :lat, CAST(:f AS jsonb)) RETURNING id"
        ),
        {
            "sid": _uuid.UUID(str(session_id)) if session_id else None,
            "a": action,
            "sc": score,
            "b": band,
            "d": decision,
            "mv": model_version,
            "lat": latency_ms,
            "f": json.dumps(features) if features is not None else None,
        },
    ).scalar_one()


def create_case(
    s: Session,
    session_id: str | _uuid.UUID | None,
    decision_id: int | None,
    action: str,
    decision: str,
    score: float | None = None,
) -> int:
    return s.execute(
        text(
            "INSERT INTO cases (session_id, decision_id, action, score, decision)"
            " VALUES (:sid, :did, :a, :sc, :d) RETURNING id"
        ),
        {
            "sid": _uuid.UUID(str(session_id)) if session_id else None,
            "did": decision_id,
            "a": action,
            "sc": score,
            "d": decision,
        },
    ).scalar_one()
