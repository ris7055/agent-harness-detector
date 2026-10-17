"""Read queries for the analyst console (SPEC section 7.5).

All reads go straight to Cloud SQL / Postgres via ``harnessguard_core.db``;
the console never calls the scorer except to (re)generate an explanation.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from harnessguard_core import db


def _rows(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with db.get_session() as s:
        return [dict(r._mapping) for r in s.execute(text(sql), params).all()]


def list_sessions(limit: int = 100) -> list[dict[str, Any]]:
    """Live sessions table (newest activity first)."""
    return _rows(
        """
        SELECT s.id, s.started_at, s.last_seen, s.event_count,
               s.risk_score, s.risk_band, s.model_version,
               u.username,
               l.label, l.variant, l.collector, l.task_id,
               (SELECT count(*) FROM session_events e
                 WHERE e.session_id = s.id AND e.type = 'page') AS page_count,
               (SELECT string_agg(DISTINCT e.page, ', ' ORDER BY e.page)
                  FROM session_events e
                 WHERE e.session_id = s.id AND e.type = 'page') AS pages,
               (SELECT d.decision FROM decisions d
                 WHERE d.session_id = s.id ORDER BY d.id DESC LIMIT 1)
                 AS last_decision
        FROM sessions s
        LEFT JOIN users u ON u.id = s.user_id
        LEFT JOIN session_labels l ON l.session_id = s.id
        ORDER BY s.last_seen DESC
        LIMIT :n
        """,
        {"n": limit},
    )


def list_cases(limit: int = 200) -> list[dict[str, Any]]:
    """Case list, open first (SPEC 7.5)."""
    return _rows(
        """
        SELECT c.id, c.session_id, c.action, c.score, c.decision, c.status,
               c.created_at, c.reviewed_at,
               (c.explanation IS NOT NULL) AS has_explanation,
               u.username
        FROM cases c
        LEFT JOIN sessions s ON s.id = c.session_id
        LEFT JOIN users u ON u.id = s.user_id
        ORDER BY (c.status = 'open') DESC, c.created_at DESC
        LIMIT :n
        """,
        {"n": limit},
    )


def get_case(case_id: int) -> dict[str, Any] | None:
    rows = _rows(
        """
        SELECT c.id, c.session_id, c.decision_id, c.action, c.score,
               c.decision, c.status, c.explanation, c.created_at, c.reviewed_at,
               d.band, d.model_version, d.latency_ms, d.features,
               d.created_at AS decided_at,
               u.username,
               l.label, l.variant, l.collector, l.task_id
        FROM cases c
        LEFT JOIN decisions d ON d.id = c.decision_id
        LEFT JOIN sessions s ON s.id = c.session_id
        LEFT JOIN users u ON u.id = s.user_id
        LEFT JOIN session_labels l ON l.session_id = c.session_id
        WHERE c.id = :i
        """,
        {"i": case_id},
    )
    return rows[0] if rows else None


def set_case_status(case_id: int, status: str) -> None:
    with db.get_session() as s:
        s.execute(
            text(
                "UPDATE cases SET status=:st, reviewed_at=now() WHERE id=:i"
            ),
            {"st": status, "i": case_id},
        )
        s.commit()


def session_events(session_id) -> list[dict[str, Any]]:
    """Full event stream for replay / timelines (chronological by seq)."""
    return _rows(
        """
        SELECT seq, t_ms, wall_ms, type, page, data
        FROM session_events
        WHERE session_id = :i
        ORDER BY seq
        """,
        {"i": session_id},
    )


def latest_fingerprint(session_id) -> dict[str, Any]:
    with db.get_session() as s:
        row = s.execute(
            text(
                "SELECT data FROM session_events WHERE session_id = :i"
                " AND type = 'fingerprint' ORDER BY seq DESC LIMIT 1"
            ),
            {"i": session_id},
        ).first()
    return dict(row.data) if row and isinstance(row.data, dict) else {}


def list_usernames() -> list[str]:
    return [
        r["username"]
        for r in _rows("SELECT username FROM users ORDER BY username", {})
    ]


_DECISIONS_SQL = """
    SELECT d.id, d.created_at, d.session_id, d.action, d.score, d.band,
           d.decision, d.model_version, d.latency_ms, d.features,
           u.username,
           c.id AS case_id, c.status AS case_status,
           COALESCE(t.amount_cents, l.amount_cents) AS amount_cents
    FROM decisions d
    LEFT JOIN sessions s ON s.id = d.session_id
    LEFT JOIN users u ON u.id = s.user_id
    LEFT JOIN cases c ON c.decision_id = d.id
    LEFT JOIN LATERAL (
        SELECT amount_cents FROM transfers tr
         WHERE tr.session_id = d.session_id
         ORDER BY tr.created_at DESC, tr.id DESC LIMIT 1
    ) t ON d.action = 'transfer'
    LEFT JOIN LATERAL (
        SELECT amount_cents FROM loan_applications la
         WHERE la.session_id = d.session_id
         ORDER BY la.created_at DESC, la.id DESC LIMIT 1
    ) l ON d.action = 'loan_apply'
"""


def list_decisions(
    decision: str | None = None,
    band: str | None = None,
    user: str | None = None,
    from_ts=None,
    to_ts=None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Detection log rows (newest first) with optional filters (SPEC 7.5)."""
    sql, params = _DECISIONS_SQL + " WHERE TRUE", {"n": limit}
    if decision in ("allow", "step_up", "block"):
        sql += " AND d.decision = :decision"
        params["decision"] = decision
    if band in ("green", "amber", "red"):
        sql += " AND d.band = :band"
        params["band"] = band
    if user:
        sql += " AND u.username = :user"
        params["user"] = user
    if from_ts is not None:
        sql += " AND d.created_at >= :from_ts"
        params["from_ts"] = from_ts
    if to_ts is not None:
        sql += " AND d.created_at <= :to_ts"
        params["to_ts"] = to_ts
    sql += " ORDER BY d.created_at DESC, d.id DESC LIMIT :n"
    return _rows(sql, params)


def decision_session_id(decision_id: int):
    rows = _rows(
        "SELECT session_id FROM decisions WHERE id = :i", {"i": decision_id}
    )
    return rows[0]["session_id"] if rows else None
