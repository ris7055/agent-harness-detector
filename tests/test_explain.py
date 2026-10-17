"""Gemini explainer tests (SPEC section 7.4, task D5).

LLM_MODE=mock in the test env: the explainer must produce deterministic
JSON matching the response schema, store it on the case row, store
{"error": ...} on failure, and never raise into the decision path.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from harnessguard_core import db

from test_features import bot_events
from test_scorer import INTERNAL, _batch, _decide

SCHEMA_KEYS = {"verdict", "confidence", "summary", "evidence",
               "recommended_action", "analyst_next_steps"}


def _bot_case(scorer_client) -> tuple[uuid.UUID, int]:
    """Bot telemetry + decide -> case id (explanation runs in the background
    task, which TestClient executes before returning)."""
    sid = uuid.uuid4()
    scorer_client.post("/v1/events", json=_batch(sid, bot_events()),
                       headers=INTERNAL)
    body = scorer_client.post("/v1/decide", json=_decide(sid),
                              headers=INTERNAL).json()
    assert body["case_id"] is not None
    return sid, body["case_id"]


def _explanation(case_id: int) -> dict | None:
    with db.get_session() as s:
        return s.execute(
            text("SELECT explanation FROM cases WHERE id=:i"), {"i": case_id}
        ).scalar_one()


def test_mock_explanation_matches_schema(scorer_client):
    _, case_id = _bot_case(scorer_client)
    expl = _explanation(case_id)
    assert expl is not None, "background task should have stored an explanation"
    assert set(expl) == SCHEMA_KEYS
    assert expl["verdict"] in ("likely_ai_agent", "likely_human", "uncertain")
    assert expl["confidence"] in ("low", "medium", "high")
    assert expl["recommended_action"] in ("allow", "step_up", "block_and_review")
    assert isinstance(expl["summary"], str) and expl["summary"]
    assert isinstance(expl["evidence"], list) and expl["evidence"]
    assert isinstance(expl["analyst_next_steps"], list)


def test_mock_explanation_cites_real_features(scorer_client):
    _, case_id = _bot_case(scorer_client)
    expl = _explanation(case_id)
    blob = " ".join(expl["evidence"]) + expl["summary"]
    # the bot fixture fires fp_webdriver; the explainer must cite it
    assert "fp_webdriver" in blob
    # and the concrete score must appear
    assert "0." in expl["summary"]


def test_explain_endpoint_regenerates(scorer_client):
    _, case_id = _bot_case(scorer_client)
    r = scorer_client.post(f"/v1/cases/{case_id}/explain", headers=INTERNAL)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == SCHEMA_KEYS
    assert _explanation(case_id) == body


def test_explain_endpoint_404_and_auth(scorer_client):
    assert scorer_client.post(
        "/v1/cases/999999/explain", headers=INTERNAL
    ).status_code == 404
    assert scorer_client.post("/v1/cases/1/explain").status_code == 401


def test_llm_error_stored_not_raised(scorer_client, monkeypatch):
    """Any Gemini failure is stored as {"error": ...}; the case survives."""
    import scorer_app.explain as explain_mod

    def boom(_payload):
        raise RuntimeError("simulated Gemini outage")

    monkeypatch.setenv("LLM_MODE", "apikey")
    monkeypatch.setattr(explain_mod, "_gemini_explanation", boom)
    _, case_id = _bot_case(scorer_client)
    expl = _explanation(case_id)
    assert expl is not None and "error" in expl
    assert "Gemini outage" in expl["error"]


def test_explanation_never_breaks_decide(scorer_client, monkeypatch):
    """Even a crashing explainer must not affect /v1/decide (SPEC 7.2.4)."""
    import scorer_app.explain as explain_mod

    def crash(*_a, **_kw):
        raise RuntimeError("explainer exploded")

    monkeypatch.setattr(explain_mod, "generate_explanation", crash)
    sid = uuid.uuid4()
    scorer_client.post("/v1/events", json=_batch(sid, bot_events()),
                       headers=INTERNAL)
    r = scorer_client.post("/v1/decide", json=_decide(sid), headers=INTERNAL)
    assert r.status_code == 200
    assert r.json()["case_id"] is not None
