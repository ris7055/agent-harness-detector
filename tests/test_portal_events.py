"""Portal telemetry transport tests (SPEC section 5.3, task D2).

/api/events forwards per EVENT_TRANSPORT: `http` -> scorer /v1/events
(exercised via the `stack` bridge), `pubsub` -> publish with a session_id
attribute (mocked publisher).
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text

from harnessguard_core import db


def _batch(sid):
    return {
        "session_id": str(sid),
        "page_load_id": str(uuid.uuid4()),
        "sent_at": 1760000000000,
        "events": [
            {"seq": 1, "t": 5.0, "wall": 1760000000005, "type": "page",
             "page": "/login", "data": {"path": "/login", "referrer_path": ""}},
            {"seq": 2, "t": 50.0, "wall": 1760000000050, "type": "mousemove",
             "page": "/login", "data": {"x": 10, "y": 20}},
        ],
    }


def _own(client, sid):
    """Make the test client's hg_sid cookie match the batch session."""
    client.cookies.set("hg_sid", str(sid))
    return sid


def test_api_events_reach_scorer_over_http(stack):
    sid = _own(stack, uuid.uuid4())
    batch = _batch(sid)
    r = stack.post("/api/events", json=batch)
    assert r.status_code == 204
    with db.get_session() as s:
        n = s.execute(
            text("SELECT count(*) FROM session_events WHERE session_id=:i"),
            {"i": sid},
        ).scalar_one()
    assert n == 2


def test_api_events_pubsub_publishes(client, monkeypatch):
    from app import main as portal_main

    calls = []

    class FakePublisher:
        def topic_path(self, project, topic):
            return f"projects/{project}/topics/{topic}"

        def publish(self, topic, data, **attrs):
            calls.append((topic, data, attrs))

    monkeypatch.setattr(portal_main, "_publisher", FakePublisher())
    monkeypatch.setenv("EVENT_TRANSPORT", "pubsub")
    monkeypatch.setenv("GCP_PROJECT", "demo-project")
    monkeypatch.setenv("PUBSUB_TOPIC", "session-events")

    batch = _batch(_own(client, uuid.uuid4()))
    r = client.post("/api/events", json=batch)
    assert r.status_code == 204

    assert len(calls) == 1
    topic, data, attrs = calls[0]
    assert topic == "projects/demo-project/topics/session-events"
    assert attrs["session_id"] == batch["session_id"]
    assert json.loads(data)["events"] == batch["events"]


def test_api_events_survives_scorer_outage(client, monkeypatch):
    # scorer down -> still 204; the page must never break on telemetry
    monkeypatch.setenv("SCORER_URL", "http://127.0.0.1:9")
    sid = _own(client, uuid.uuid4())
    assert client.post("/api/events", json=_batch(sid)).status_code == 204


def test_api_events_middleware_skips_ensure_session(client):
    # D1 review note: /api/events fires every 2 s per browser; the portal must
    # not upsert sessions there (the scorer owns last_seen). Cookie session id
    # differs from the batch's session_id, so this is observable.
    client.get("/login")  # creates the cookie session row
    cookie_sid = uuid.UUID(client.cookies.get("hg_sid"))
    with db.get_session() as s:
        s.execute(text("DELETE FROM sessions WHERE id=:i"), {"i": cookie_sid})
        s.commit()

    client.post("/api/events", json=_batch(uuid.uuid4()))
    with db.get_session() as s:
        assert s.execute(
            text("SELECT 1 FROM sessions WHERE id=:i"), {"i": cookie_sid}
        ).first() is None


def test_api_events_rejects_other_sessions(stack):
    """Review D2 MUST 1: a browser cannot inject events into another session."""
    victim = uuid.uuid4()
    _own(stack, uuid.uuid4())                 # attacker's own cookie
    r = stack.post("/api/events", json=_batch(victim))
    assert r.status_code == 204              # silent drop, no retry loop
    with db.get_session() as s:
        n = s.execute(
            text("SELECT count(*) FROM session_events WHERE session_id=:i"),
            {"i": victim},
        ).scalar_one()
    assert n == 0


def test_collector_js_is_served(client):
    """Review D2 MUST: base.html loads /static/collector.js, so it must exist."""
    r = client.get("/static/collector.js")
    assert r.status_code == 200
    assert "hg-session" in r.text and "/api/events" in r.text
    page = client.get("/login").text
    assert 'src="/static/collector.js"' in page
