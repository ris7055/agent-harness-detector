"""Scorer service tests (SPEC section 7.2, task D2).

Runs the scorer app in-process (scorer_client fixture) against the shared
test database.
"""

from __future__ import annotations

import base64
import json
import uuid

from sqlalchemy import text

from harnessguard_core import db

from test_features import WALL0, _ev, bot_events, human_events

INTERNAL = {"X-HG-Internal": "test-internal"}


def _batch(sid, events):
    return {
        "session_id": str(sid),
        "page_load_id": str(uuid.uuid4()),
        "sent_at": 1760000000000,
        "events": events,
    }


def _decide(sid, action="transfer", last_seq=0, amount_cents=12000):
    return {
        "session_id": str(sid),
        "action": action,
        "last_seq": last_seq,
        "context": {"amount_cents": amount_cents, "new_payee": True},
    }


def test_healthz_open(scorer_client):
    r = scorer_client.get("/healthz")
    assert r.status_code == 200 and r.json()["service"] == "scorer"


def test_v1_requires_internal_token(scorer_client):
    batch = _batch(uuid.uuid4(), [])
    assert scorer_client.post("/v1/events", json=batch).status_code == 401
    assert scorer_client.post(
        "/v1/events", json=batch, headers={"X-HG-Internal": "nope"}
    ).status_code == 401
    assert scorer_client.post("/v1/decide", json={}).status_code == 401
    assert scorer_client.get(f"/v1/sessions/{uuid.uuid4()}/score").status_code == 401


def test_ingest_stores_events_and_scores_session(scorer_client):
    sid = uuid.uuid4()
    evs = human_events()
    r = scorer_client.post("/v1/events", json=_batch(sid, evs), headers=INTERNAL)
    assert r.status_code == 204

    with db.get_session() as s:
        n = s.execute(
            text("SELECT count(*) FROM session_events WHERE session_id=:i"),
            {"i": sid},
        ).scalar_one()
        row = s.execute(
            text(
                "SELECT event_count, risk_score, risk_band, model_version"
                " FROM sessions WHERE id=:i"
            ),
            {"i": sid},
        ).first()._mapping
    assert n == len(evs)
    assert row["event_count"] == n
    assert row["risk_score"] is not None
    assert row["risk_score"] < 0.50 and row["risk_band"] == "green"
    assert row["model_version"] == "rules"

    # duplicate batches are idempotent (ON CONFLICT DO NOTHING)
    scorer_client.post("/v1/events", json=_batch(sid, evs), headers=INTERNAL)
    with db.get_session() as s:
        again = s.execute(
            text("SELECT count(*) FROM session_events WHERE session_id=:i"),
            {"i": sid},
        ).scalar_one()
        count = s.execute(
            text("SELECT event_count FROM sessions WHERE id=:i"), {"i": sid}
        ).scalar_one()
    assert again == n and count == n


def test_score_endpoint(scorer_client):
    sid = uuid.uuid4()
    scorer_client.post("/v1/events", json=_batch(sid, bot_events()), headers=INTERNAL)
    r = scorer_client.get(f"/v1/sessions/{sid}/score", headers=INTERNAL)
    assert r.status_code == 200
    body = r.json()
    assert body["score"] >= 0.50
    assert body["band"] in ("amber", "red")
    assert body["model_version"] == "rules"
    assert body["top_reasons"] and body["event_count"] == len(bot_events())

    assert scorer_client.get(
        f"/v1/sessions/{uuid.uuid4()}/score", headers=INTERNAL
    ).status_code == 404


def test_decide_bot_creates_case(scorer_client):
    sid = uuid.uuid4()
    scorer_client.post("/v1/events", json=_batch(sid, bot_events()), headers=INTERNAL)
    r = scorer_client.post("/v1/decide", json=_decide(sid), headers=INTERNAL)
    assert r.status_code == 200
    body = r.json()

    assert body["decision"] in ("step_up", "block")
    assert body["band"] in ("amber", "red")
    assert body["case_id"] is not None
    assert body["model_version"] == "rules"
    assert 0 <= body["latency_ms"] < 300  # p95 target excludes the seq wait
    assert body["top_reasons"]

    with db.get_session() as s:
        case = s.execute(
            text("SELECT decision, decision_id, status FROM cases WHERE id=:i"),
            {"i": body["case_id"]},
        ).first()._mapping
        dec = s.execute(
            text("SELECT decision, latency_ms, features FROM decisions WHERE id=:i"),
            {"i": case["decision_id"]},
        ).first()._mapping
    assert case["decision"] == body["decision"] and case["status"] == "open"
    assert dec["decision"] == body["decision"]
    assert dec["latency_ms"] == body["latency_ms"]
    assert dec["features"]["fp_webdriver"] == 1.0


def test_decide_human_allows(scorer_client):
    sid = uuid.uuid4()
    scorer_client.post("/v1/events", json=_batch(sid, human_events()),
                       headers=INTERNAL)
    r = scorer_client.post("/v1/decide", json=_decide(sid), headers=INTERNAL)
    body = r.json()
    assert body["decision"] == "allow"
    assert body["band"] == "green" and body["case_id"] is None


def test_decide_large_amount_raises_friction(scorer_client):
    # only a programmatic input: score ~0.39 (amber zone boundary is 0.50),
    # normally allow, but >= RM 5,000 with score >= 0.35 must step up.
    sid = uuid.uuid4()
    evs = [
        _ev(1, WALL0, "page", "/transfer", {"path": "/transfer"}),
        _ev(2, WALL0 + 100, "input", "/transfer",
            {"field_id": "amount", "value_length": 8}),
    ]
    scorer_client.post("/v1/events", json=_batch(sid, evs), headers=INTERNAL)

    small = scorer_client.post(
        "/v1/decide", json=_decide(sid, amount_cents=100), headers=INTERNAL
    ).json()
    assert small["decision"] == "allow" and small["score"] >= 0.35

    big = scorer_client.post(
        "/v1/decide", json=_decide(sid, amount_cents=600_000), headers=INTERNAL
    ).json()
    assert big["decision"] == "step_up" and big["case_id"] is not None


def test_decide_tolerates_missing_seq(scorer_client, monkeypatch):
    import scorer_app.main as scorer_main

    monkeypatch.setattr(scorer_main, "_SEQ_WAIT_S", 0.3)
    sid = uuid.uuid4()
    scorer_client.post(
        "/v1/events", json=_batch(sid, human_events()[:5]), headers=INTERNAL
    )
    r = scorer_client.post(
        "/v1/decide", json=_decide(sid, last_seq=9999), headers=INTERNAL
    )
    assert r.status_code == 200  # waits, then decides on what it has
    assert r.json()["latency_ms"] < 300


def test_explain_endpoint_exists(scorer_client):
    # full explainer coverage lives in test_explain.py (D5)
    r = scorer_client.post("/v1/cases/999999/explain", headers=INTERNAL)
    assert r.status_code == 404


def test_pubsub_push_decodes_envelope(scorer_client):
    sid = uuid.uuid4()
    evs = human_events()[:6]
    envelope = {
        "message": {
            "data": base64.b64encode(
                json.dumps(_batch(sid, evs)).encode()
            ).decode(),
            "attributes": {"session_id": str(sid)},
            "messageId": "123",
            "publishTime": "2026-10-16T00:00:00Z",
        },
        "subscription": "projects/demo/subscriptions/session-events-scorer",
    }
    r = scorer_client.post("/pubsub/events?token=test-push", json=envelope)
    assert r.status_code == 204
    with db.get_session() as s:
        n = s.execute(
            text("SELECT count(*) FROM session_events WHERE session_id=:i"),
            {"i": sid},
        ).scalar_one()
    assert n == len(evs)

    assert scorer_client.post(
        "/pubsub/events?token=wrong", json=envelope
    ).status_code == 401
    assert scorer_client.post(
        "/pubsub/events?token=test-push", json={"message": {"data": "!!bad!!"}}
    ).status_code == 400
    assert scorer_client.post(
        "/pubsub/events?token=test-push", json={"not": "an envelope"}
    ).status_code == 400


def test_no_forbidden_payload_keys_anywhere(scorer_client):
    # privacy rule: timings, key classes and value lengths only — never key
    # values, input values or passwords (AGENTS.md rule 4).
    sid = uuid.uuid4()
    evs = human_events() + bot_events()
    scorer_client.post("/v1/events", json=_batch(sid, evs), headers=INTERNAL)

    forbidden = {"key", "value", "password"}

    def keys(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield k
                yield from keys(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from keys(v)

    with db.get_session() as s:
        rows = s.execute(
            text("SELECT data FROM session_events WHERE session_id=:i"), {"i": sid}
        ).all()
    assert rows
    for row in rows:
        assert forbidden.isdisjoint(set(keys(row.data))), row.data


def test_collector_js_sends_no_sensitive_fields():
    # the collector only ever sends key CLASS and value LENGTH
    src = open(
        "services/portal/static/collector.js", encoding="utf-8"
    ).read()
    # every read of the raw key goes through the classifier, never the payload
    assert src.count("e.key") == src.count("keyClass(e.key)") == 1
    # a field's .value is read once, only to take its length
    assert src.count("e.target.value") == 1
    assert "v.length" in src
