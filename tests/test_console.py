"""Analyst console tests (SPEC section 7.5, task D5).

The console reads the shared test database directly. Its only outbound
call (regenerate explanation) goes through ``console_app.main.httpx``,
which the tests can shim into the in-process scorer client.
"""

from __future__ import annotations

import types
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy import text

from harnessguard_core import db

from test_features import bot_events, human_events
from test_scorer import INTERNAL, _batch, _decide

FIXTURE_BENCHMARK = str(
    Path(__file__).parent / "fixtures" / "benchmark.sample.json"
)


def _login(console_client, password="test-console"):
    return console_client.post(
        "/login", data={"password": password}, follow_redirects=False
    )


@pytest.fixture()
def authed(console_client):
    _login(console_client)
    return console_client


def _bot_case(scorer_client):
    sid = uuid.uuid4()
    scorer_client.post("/v1/events", json=_batch(sid, bot_events()),
                       headers=INTERNAL)
    return sid, scorer_client.post(
        "/v1/decide", json=_decide(sid), headers=INTERNAL
    ).json()


def _human_decision(scorer_client):
    sid = uuid.uuid4()
    scorer_client.post("/v1/events", json=_batch(sid, human_events()),
                       headers=INTERNAL)
    return sid, scorer_client.post(
        "/v1/decide", json=_decide(sid, action="loan_apply"),
        headers=INTERNAL).json()


# ------------------------------------------------------------------- auth

def test_healthz_open(console_client):
    r = console_client.get("/healthz")
    assert r.status_code == 200 and r.json()["service"] == "console"


def test_pages_require_login(console_client):
    r = console_client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    for path in ["/cases", "/cases/1", "/log", "/benchmark"]:
        r = console_client.get(path, follow_redirects=False)
        assert r.status_code == 303, path
    assert console_client.get("/api/sessions").status_code == 401
    assert console_client.get("/api/decisions").status_code == 401


def test_login_flow(console_client):
    bad = _login(console_client, password="wrong")
    assert bad.status_code == 401

    ok = _login(console_client)
    assert ok.status_code == 303
    assert "hg_console" in ok.headers["set-cookie"]

    assert console_client.get("/").status_code == 200
    r = console_client.get("/logout", follow_redirects=False)
    assert r.status_code == 303
    r = console_client.get("/", follow_redirects=False)
    assert r.status_code == 303  # cookie cleared: back to the login page


# ------------------------------------------------------------- sessions

def test_live_sessions_api(authed, scorer_client):
    _bot_case(scorer_client)
    r = authed.get("/api/sessions")
    assert r.status_code == 200
    sessions = r.json()["sessions"]
    assert sessions
    row = sessions[0]
    for key in ("id", "started_at", "event_count", "risk_score",
                "risk_band", "page_count", "last_decision"):
        assert key in row
    assert authed.get("/").status_code == 200


# ----------------------------------------------------------------- cases

def test_case_list_and_detail(authed, scorer_client):
    _, body = _bot_case(scorer_client)
    case_id = body["case_id"]

    r = authed.get("/cases")
    assert r.status_code == 200 and f"CASE-{case_id:04d}" in r.text

    r = authed.get(f"/cases/{case_id}")
    assert r.status_code == 200
    for marker in ("Gemini explanation", "Top reasons", "Fingerprint",
                   "Mouse-path replay", "Event timeline", "Confirm fraud"):
        assert marker in r.text, marker

    assert authed.get("/cases/999999").status_code == 404


def test_case_shows_mock_explanation(authed, scorer_client):
    _, body = _bot_case(scorer_client)
    r = authed.get(f"/cases/{body['case_id']}")
    assert "fp_webdriver" in r.text  # mock explanation cites the feature


def test_case_status_updates(authed, scorer_client):
    _, body = _bot_case(scorer_client)
    case_id = body["case_id"]

    r = authed.post(f"/cases/{case_id}/status",
                    data={"status": "confirmed_fraud"},
                    follow_redirects=False)
    assert r.status_code == 303
    with db.get_session() as s:
        row = s.execute(
            text("SELECT status, reviewed_at FROM cases WHERE id=:i"),
            {"i": case_id}).first()._mapping
    assert row["status"] == "confirmed_fraud"
    assert row["reviewed_at"] is not None

    assert authed.post(f"/cases/{case_id}/status",
                       data={"status": "bogus"}).status_code == 400
    assert authed.post("/cases/999999/status",
                       data={"status": "confirmed_fraud"}).status_code == 404


def test_session_events_api(authed, scorer_client):
    sid, _ = _bot_case(scorer_client)
    r = authed.get(f"/api/sessions/{sid}/events")
    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) == len(bot_events())
    assert {e["type"] for e in events} >= {"page", "fingerprint", "click"}


def test_regenerate_explanation_calls_scorer(authed, scorer_client, monkeypatch):
    """Console POST /cases/{id}/explain proxies to the scorer's /v1 route."""
    import console_app.main as console_main

    def _route(url, **kw):
        kw.pop("timeout", None)
        return scorer_client.request("POST", urlparse(url).path, **kw)

    monkeypatch.setattr(console_main, "httpx",
                        types.SimpleNamespace(post=_route))
    sid, body = _bot_case(scorer_client)
    r = authed.post(f"/cases/{body['case_id']}/explain",
                    follow_redirects=False)
    assert r.status_code == 303
    with db.get_session() as s:
        expl = s.execute(
            text("SELECT explanation FROM cases WHERE id=:i"),
            {"i": body["case_id"]}).scalar_one()
    assert expl and "verdict" in expl


# ------------------------------------------------------------------- log

def test_detection_log_and_filters(authed, scorer_client):
    _, block = _bot_case(scorer_client)
    _, allow = _human_decision(scorer_client)
    assert allow["decision"] == "allow"

    assert authed.get("/log").status_code == 200

    rows = authed.get("/api/decisions").json()["decisions"]
    assert len(rows) >= 2
    ids = {r["id"] for r in rows}
    assert len(rows[0]["top_reasons"]) <= 3

    only_block = authed.get("/api/decisions?decision=block").json()["decisions"]
    assert only_block and all(r["decision"] == "block" for r in only_block)

    only_green = authed.get("/api/decisions?band=green").json()["decisions"]
    assert only_green and all(r["band"] == "green" for r in only_green)

    nobody = authed.get("/api/decisions?user=zzz_noone").json()["decisions"]
    assert nobody == []


def test_detection_log_csv_matches(authed, scorer_client):
    _bot_case(scorer_client)
    r = authed.get("/log.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    lines = [l for l in r.text.strip().splitlines() if l]
    api_rows = authed.get("/api/decisions").json()["decisions"]
    assert len(lines) == len(api_rows) + 1  # header + one line per row
    assert "reason_1" in lines[0]

    # CSV honours the same filters
    r2 = authed.get("/log.csv?decision=allow")
    data_lines = [l for l in r2.text.strip().splitlines() if l][1:]
    allow_rows = authed.get("/api/decisions?decision=allow").json()["decisions"]
    assert len(data_lines) == len(allow_rows)


def test_decision_timeline_api(authed, scorer_client):
    _, body = _bot_case(scorer_client)
    with db.get_session() as s:
        did = s.execute(
            text("SELECT decision_id FROM cases WHERE id=:i"),
            {"i": body["case_id"]}).scalar_one()
    r = authed.get(f"/api/decisions/{did}/timeline")
    assert r.status_code == 200
    assert len(r.json()["events"]) == len(bot_events())
    assert authed.get("/api/decisions/999999/timeline").status_code == 404


# ------------------------------------------------------------- benchmark

def test_benchmark_page(authed, monkeypatch):
    monkeypatch.setenv("BENCHMARK_URI", FIXTURE_BENCHMARK)
    r = authed.get("/benchmark")
    assert r.status_code == 200
    for marker in ("Model comparison", "xgb_full", "rules_baseline",
                   "Detection rate by agent variant", "ROC curves",
                   "Early detection", "llm_headless"):
        assert marker in r.text, marker


def test_benchmark_missing(authed, monkeypatch):
    monkeypatch.setenv("BENCHMARK_URI", "./does-not-exist.json")
    r = authed.get("/benchmark")
    assert r.status_code == 200
    assert "No benchmark yet" in r.text
