"""Portal happy-path tests (task D1 acceptance criteria)."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import text

from harnessguard_core import db


def _login(client, username="daniel", password="Seroja@2026"):
    return client.post(
        "/login", data={"username": username, "password": password}, follow_redirects=False
    )


def _balance(client, username="daniel") -> int:
    with db.get_session() as s:
        return s.execute(
            text(
                "SELECT balance_cents FROM accounts a JOIN users u ON u.id=a.user_id"
                " WHERE u.username=:u"
            ),
            {"u": username},
        ).scalar_one()


def _confirm_form(amount_cents=12050):
    return {
        "to_name": "Lim Wei Jie",
        "to_bank": "Teratai Bank",
        "to_account": "8812 0045 3301",
        "amount_cents": str(amount_cents),
        "reference": "dinner",
        "hg_last_seq": "0",
    }


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["service"] == "portal"


def test_root_redirects_to_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_login_and_dashboard(client):
    assert client.get("/login").status_code == 200

    bad = _login(client, password="wrong")
    assert bad.status_code == 401

    r = _login(client)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"

    dash = client.get("/dashboard")
    assert dash.status_code == 200
    assert "RM" in dash.text and "Recent transactions" in dash.text
    assert dash.text.count("</tr>") >= 6  # header + 5 seeded transactions

    # session row exists and is linked to the user after login
    sid = client.cookies.get("hg_sid")
    assert sid
    with db.get_session() as s:
        row = s.execute(
            text("SELECT user_id, ip_hash FROM sessions WHERE id=:i"),
            {"i": uuid.UUID(sid)},
        ).first()
    assert row is not None
    assert row._mapping["user_id"] is not None and row._mapping["ip_hash"]


def test_transfer_allow_end_to_end(client, monkeypatch):
    monkeypatch.delenv("FORCE_DECISION", raising=False)
    _login(client)
    before = _balance(client)

    review = client.post(
        "/transfer",
        data={
            "to_name": "Lim Wei Jie",
            "to_bank": "Teratai Bank",
            "to_account": "8812 0045 3301",
            "amount": "120.50",
            "reference": "dinner",
        },
    )
    assert review.status_code == 200 and "Confirm transfer" in review.text

    done = client.post("/transfer/confirm", data=_confirm_form())
    assert done.status_code == 200 and "Transfer successful" in done.text
    assert _balance(client) == before - 12050

    with db.get_session() as s:
        t = s.execute(
            text("SELECT status, amount_cents FROM transfers"
                 " WHERE to_account='8812 0045 3301' ORDER BY id DESC LIMIT 1")
        ).first()
        assert t._mapping["status"] == "completed" and t._mapping["amount_cents"] == 12050


def test_transfer_step_up_otp(client, monkeypatch):
    monkeypatch.setenv("FORCE_DECISION", "step_up")
    _login(client)
    before = _balance(client)

    page = client.post("/transfer/confirm", data=_confirm_form())
    assert page.status_code == 200 and "Verify it's you" in page.text
    assert _balance(client) == before  # nothing moved yet
    code = re.search(r"your code is <strong[^>]*>(\d{6})", page.text).group(1)
    item_id = re.search(r'name="item_id" value="(\d+)"', page.text).group(1)

    wrong = client.post("/otp", data={"kind": "transfer", "item_id": item_id,
                                      "otp": "000000" if code != "000000" else "111111"})
    assert wrong.status_code == 401 and "attempt(s) left" in wrong.text

    ok = client.post("/otp", data={"kind": "transfer", "item_id": item_id, "otp": code})
    assert ok.status_code == 200 and "Transfer successful" in ok.text
    assert _balance(client) == before - 12050


def test_transfer_otp_three_wrong_blocks(client, monkeypatch):
    monkeypatch.setenv("FORCE_DECISION", "step_up")
    _login(client)
    before = _balance(client)

    page = client.post("/transfer/confirm", data=_confirm_form(amount_cents=9000))
    code = re.search(r"your code is <strong[^>]*>(\d{6})", page.text).group(1)
    item_id = re.search(r'name="item_id" value="(\d+)"', page.text).group(1)
    bad_code = "000000" if code != "000000" else "111111"

    for _ in range(3):
        r = client.post("/otp", data={"kind": "transfer", "item_id": item_id, "otp": bad_code})
    assert "Too many incorrect codes" in r.text
    assert _balance(client) == before
    with db.get_session() as s:
        status = s.execute(
            text("SELECT status FROM transfers WHERE id=:i"), {"i": int(item_id)}
        ).scalar_one()
        assert status == "failed_otp"


def test_transfer_block(client, monkeypatch):
    monkeypatch.setenv("FORCE_DECISION", "block")
    _login(client)
    before = _balance(client)

    page = client.post("/transfer/confirm", data=_confirm_form())
    assert page.status_code == 200 and "held for review" in page.text
    assert re.search(r"CASE-\d{4}", page.text)
    assert _balance(client) == before

    with db.get_session() as s:
        t = s.execute(
            text("SELECT status FROM transfers"
                 " WHERE to_account='8812 0045 3301' ORDER BY id DESC LIMIT 1")
        ).first()
        assert t._mapping["status"] == "blocked"
        assert s.execute(text("SELECT count(*) FROM cases")).scalar_one() >= 1


def test_loan_flows(client, monkeypatch):
    monkeypatch.setenv("FORCE_DECISION", "block")
    _login(client)
    r = client.post("/loan", data={
        "amount": "12000", "tenure_months": "24",
        "monthly_income": "4500", "employer": "Amanah Tech Sdn Bhd",
        "hg_last_seq": "0",
    })
    assert r.status_code == 200 and "held for review" in r.text


def test_collect_human_labels_session(client):
    assert client.get("/collect").status_code == 200
    r = client.post("/collect", data={"collector": "raffa"})
    assert r.status_code == 200 and "Task card" in r.text

    sid = uuid.UUID(client.cookies.get("hg_sid"))
    with db.get_session() as s:
        label = s.execute(
            text("SELECT label, collector, task_id FROM session_labels WHERE session_id=:i"),
            {"i": sid},
        ).first()
    assert label is not None
    assert label._mapping["label"] == "human"
    assert label._mapping["collector"] == "raffa" and label._mapping["task_id"]


def test_collect_agent_labels_and_redirects(client):
    r = client.get(
        "/collect/agent?hg_label=agent&hg_variant=script_fill&hg_task=abc123",
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == "/login"
    sid = uuid.UUID(client.cookies.get("hg_sid"))
    with db.get_session() as s:
        label = s.execute(
            text("SELECT label, variant, task_id FROM session_labels WHERE session_id=:i"),
            {"i": sid},
        ).first()
    assert label._mapping["label"] == "agent"
    assert label._mapping["variant"] == "script_fill"
    assert label._mapping["task_id"] == "abc123"


def test_collect_disabled_returns_404(client, monkeypatch):
    monkeypatch.setenv("ALLOW_DATA_COLLECTION", "false")
    assert client.get("/collect").status_code == 404
    assert client.get("/collect/agent?hg_label=agent&hg_task=x").status_code == 404


def test_protected_pages_redirect_when_logged_out(client):
    for path in ("/dashboard", "/transfer", "/loan"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"


def test_api_events_accepts_valid_batch(client):
    batch = {
        "session_id": client.cookies.get("hg_sid") or str(uuid.uuid4()),
        "page_load_id": str(uuid.uuid4()),
        "sent_at": 1760000000000,
        "events": [
            {"seq": 1, "t": 1.0, "wall": 1760000000000, "type": "page",
             "page": "/login", "data": {"path": "/login", "referrer_path": ""}}
        ],
    }
    r = client.post("/api/events", json=batch)
    assert r.status_code == 204

    bad = client.post("/api/events", json={"nope": True})
    assert bad.status_code == 422
