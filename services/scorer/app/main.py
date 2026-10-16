"""HarnessGuard scorer (SPEC section 7.2, task D2).

Ingests telemetry batches, keeps a live per-session risk score, and takes
the allow / step_up / block decision at sensitive actions. ``/v1/*`` requires
the ``X-HG-Internal`` shared-secret header; the Pub/Sub push endpoint uses a
``?token=`` secret in the push URL.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from harnessguard_core import db, models
from harnessguard_core.analytics import AnalyticsSink, get_sink
from harnessguard_core.config import get_settings
from harnessguard_core.events import EventBatch
from harnessguard_core.features import compute_features
from harnessguard_core.rules import band_for_score, decision_for_score

from .model import Scorer

log = logging.getLogger("scorer")

_scorer = Scorer()
_sink: AnalyticsSink | None = None

# Debounce: recompute a session's live score at most once per second.
_RESCORE_DEBOUNCE_S = 1.0
_last_scored: dict[uuid.UUID, float] = {}
_last_scored_lock = threading.Lock()

# /v1/decide waits this long for the collector's pre-submit flush to arrive.
_SEQ_WAIT_S = 1.5
_SEQ_POLL_S = 0.1

# Context friction rule (SPEC 7.2.3): >= RM 5,000 with score >= 0.35 -> step_up.
_FRICTION_AMOUNT_CENTS = 500_000
_FRICTION_SCORE = 0.35


def _require_internal(request: Request) -> None:
    expected = get_settings().internal_token
    token = request.headers.get("x-hg-internal", "")
    if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid X-HG-Internal")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _sink
    db.init_db()
    _scorer.load(get_settings().model_uri)
    _sink = get_sink()
    yield


app = FastAPI(title="HarnessGuard scorer", lifespan=lifespan)


# ------------------------------------------------------------------ ingest

def _load_events(s, session_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = s.execute(
        text(
            "SELECT seq, t_ms, wall_ms, type, page, data FROM session_events"
            " WHERE session_id=:i ORDER BY seq"
        ),
        {"i": session_id},
    ).all()
    return [
        {"seq": r.seq, "t": r.t_ms, "wall": r.wall_ms, "type": r.type,
         "page": r.page, "data": r.data or {}}
        for r in rows
    ]


def _score_session(session_id: uuid.UUID):
    """(features, score, top_reasons, model_version) over all stored events."""
    with db.get_session() as s:
        evs = _load_events(s, session_id)
    feats = compute_features(evs)
    score, reasons = _scorer.score(feats)
    return feats, score, reasons, _scorer.version


def _rescore(session_id: uuid.UUID) -> None:
    try:
        settings = get_settings()
        _, score, _, version = _score_session(session_id)
        with db.get_session() as s:
            s.execute(
                text(
                    "UPDATE sessions SET risk_score=:sc, risk_band=:b,"
                    " model_version=:mv, last_seen=now() WHERE id=:i"
                ),
                {"sc": score,
                 "b": band_for_score(score, settings.allow_below, settings.block_above),
                 "mv": version, "i": session_id},
            )
            s.commit()
    except Exception:  # noqa: BLE001 - rescoring must never break ingest
        log.exception("rescore failed for session %s", session_id)


def _maybe_rescore(session_id: uuid.UUID) -> None:
    now = time.monotonic()
    with _last_scored_lock:
        if len(_last_scored) > 100_000:
            _last_scored.clear()
        last = _last_scored.get(session_id)
        if last is not None and now - last < _RESCORE_DEBOUNCE_S:
            return
        _last_scored[session_id] = now
    _rescore(session_id)


def _ingest(batch: EventBatch) -> None:
    sid = batch.session_id
    with db.get_session() as s:
        models.ensure_session(s, sid)
        inserted = 0
        for ev in batch.events:
            res = s.execute(
                text(
                    "INSERT INTO session_events (session_id, seq, t_ms, wall_ms,"
                    " type, page, data)"
                    " VALUES (:sid,:seq,:t,:w,:ty,:p,CAST(:d AS jsonb))"
                    " ON CONFLICT (session_id, seq) DO NOTHING"
                ),
                {"sid": sid, "seq": ev.seq, "t": ev.t, "w": ev.wall,
                 "ty": ev.type, "p": ev.page, "d": json.dumps(ev.data)},
            )
            inserted += max(res.rowcount, 0)
        s.execute(
            text(
                "UPDATE sessions SET last_seen=now(),"
                " event_count=event_count+:n WHERE id=:i"
            ),
            {"n": inserted, "i": sid},
        )
        s.commit()
    _maybe_rescore(sid)


@app.post("/v1/events", dependencies=[Depends(_require_internal)])
def ingest_events(batch: EventBatch):
    _ingest(batch)
    return Response(status_code=204)


@app.post("/pubsub/events")
async def pubsub_events(request: Request, token: str = ""):
    expected = get_settings().pubsub_push_token
    if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid push token")
    try:
        envelope = await request.json()
        raw = base64.b64decode(envelope["message"]["data"])
        batch = EventBatch.model_validate_json(raw)
    except Exception:  # noqa: BLE001 - poison messages must not retry forever
        return JSONResponse(status_code=400, content={"error": "malformed push envelope"})
    _ingest(batch)
    return Response(status_code=204)


# ------------------------------------------------------------------ decide

class DecideRequest(BaseModel):
    session_id: uuid.UUID
    action: str
    last_seq: int = 0
    context: dict[str, Any] = Field(default_factory=dict)


def _wait_for_seq(session_id: uuid.UUID, last_seq: int) -> None:
    """Wait until the pre-submit flush has landed (SPEC 7.2 step 1)."""
    if last_seq <= 0:
        return
    deadline = time.monotonic() + _SEQ_WAIT_S
    while time.monotonic() < deadline:
        with db.get_session() as s:
            max_seq = s.execute(
                text("SELECT max(seq) FROM session_events WHERE session_id=:i"),
                {"i": session_id},
            ).scalar()
        if max_seq is not None and max_seq >= last_seq:
            return
        time.sleep(_SEQ_POLL_S)


def _generate_explanation(case_id: int) -> None:
    """Queued after a case is created so decisions never block on the LLM.
    The Gemini explainer itself is implemented in D5 (SPEC 7.4)."""
    log.info("case %s queued for explanation (implemented in D5)", case_id)


@app.post("/v1/decide", dependencies=[Depends(_require_internal)])
def decide(req: DecideRequest, background_tasks: BackgroundTasks):
    settings = get_settings()
    _wait_for_seq(req.session_id, req.last_seq)

    started = time.perf_counter()
    feats, score, reasons, version = _score_session(req.session_id)
    band = band_for_score(score, settings.allow_below, settings.block_above)
    decision = decision_for_score(score, settings.allow_below, settings.block_above)
    amount = (req.context or {}).get("amount_cents")
    if (decision == "allow" and isinstance(amount, (int, float))
            and amount >= _FRICTION_AMOUNT_CENTS and score >= _FRICTION_SCORE):
        decision = "step_up"  # context can only raise friction

    latency_ms = int((time.perf_counter() - started) * 1000)
    case_id = None
    with db.get_session() as s:
        decision_id = models.record_decision(
            s, req.session_id, req.action, decision, score=score, band=band,
            model_version=version, latency_ms=latency_ms, features=feats,
        )
        if decision in ("step_up", "block"):
            case_id = models.create_case(
                s, req.session_id, decision_id, req.action, decision, score=score
            )
            background_tasks.add_task(_generate_explanation, case_id)
        s.execute(
            text(
                "UPDATE sessions SET risk_score=:sc, risk_band=:b,"
                " model_version=:mv, last_seen=now() WHERE id=:i"
            ),
            {"sc": score, "b": band, "mv": version, "i": req.session_id},
        )
        s.commit()

    if _sink is not None:
        _sink.write_session_features(
            {
                "session_id": str(req.session_id),
                "decided_at": datetime.now(timezone.utc).isoformat(),
                "action": req.action,
                "model_version": version,
                "score": score,
                "decision": decision,
                **feats,
            }
        )

    return {
        "decision": decision,
        "score": score,
        "band": band,
        "case_id": case_id,
        "model_version": version,
        "latency_ms": latency_ms,
        "top_reasons": reasons,
    }


# ------------------------------------------------------------------ misc

@app.get("/v1/sessions/{session_id}/score", dependencies=[Depends(_require_internal)])
def session_score(session_id: uuid.UUID):
    settings = get_settings()
    with db.get_session() as s:
        row = s.execute(
            text(
                "SELECT user_id, started_at, last_seen, event_count FROM sessions"
                " WHERE id=:i"
            ),
            {"i": session_id},
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown session")
    _, score, reasons, version = _score_session(session_id)
    return {
        "session_id": str(session_id),
        "score": score,
        "band": band_for_score(score, settings.allow_below, settings.block_above),
        "model_version": version,
        "top_reasons": reasons,
        "user_id": row.user_id,
        "event_count": row.event_count,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "last_seen": row.last_seen.isoformat() if row.last_seen else None,
    }


@app.post("/v1/cases/{case_id}/explain", dependencies=[Depends(_require_internal)])
def explain_case(case_id: int):
    return JSONResponse(
        status_code=501,
        content={"error": "Gemini explainer is implemented in D5"},
    )


@app.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok", "service": "scorer"})
