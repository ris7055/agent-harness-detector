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


# ---------------------------------------------------------------- review fixes


def test_transfer_rejects_non_positive_amounts(client, monkeypatch):
    monkeypatch.setenv("FORCE_DECISION", "allow")
    _login(client, username="ravi")
    before = _balance(client, "ravi")
    for bad in (-100000, 0):
        r = client.post("/transfer/confirm", data=_confirm_form(amount_cents=bad))
        assert r.status_code == 400
    assert _balance(client, "ravi") == before


def test_transfer_rejects_amount_over_balance_on_every_path(client, monkeypatch):
    _login(client, username="meiling")
    before = _balance(client, "meiling")
    for forced in ("allow", "step_up", "block"):
        monkeypatch.setenv("FORCE_DECISION", forced)
        r = client.post("/transfer/confirm", data=_confirm_form(amount_cents=before + 1))
        assert r.status_code == 400, forced
    assert _balance(client, "meiling") == before


def test_login_blocks_open_redirect(client):
    for evil in ("//evil.example", "/\\evil.example", "https://evil.example"):
        r = client.post(
            "/login",
            data={"username": "daniel", "password": "Seroja@2026", "next": evil},
            follow_redirects=False,
        )
        assert r.headers["location"] == "/dashboard", evil
    r = client.post(
        "/login",
        data={"username": "daniel", "password": "Seroja@2026", "next": "/transfer"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/transfer"


def test_each_collect_task_gets_its_own_session(client):
    _login(client)
    first = client.post("/collect", data={"collector": "raffa"})
    sid1 = client.cookies.get("hg_sid")
    second = client.post("/collect", data={"collector": "raffa"})
    sid2 = client.cookies.get("hg_sid")
    assert first.status_code == second.status_code == 200
    assert sid1 and sid2 and sid1 != sid2
    # starting a task logs the volunteer out so they follow the task card from login
    assert client.get("/dashboard", follow_redirects=False).status_code == 303
    with db.get_session() as s:
        rows = s.execute(
            text("SELECT session_id, task_id FROM session_labels"
                 " WHERE session_id IN (:a, :b)"),
            {"a": uuid.UUID(sid1), "b": uuid.UUID(sid2)},
        ).all()
    assert len(rows) == 2
    assert rows[0]._mapping["task_id"] != rows[1]._mapping["task_id"]


def test_collect_agent_rotates_session_and_validates_label(client):
    client.get("/login")
    old = client.cookies.get("hg_sid")
    r = client.get("/collect/agent?hg_label=agent&hg_variant=llm_stealth&hg_task=t1",
                   follow_redirects=False)
    assert r.status_code == 303 and client.cookies.get("hg_sid") != old
    bad = client.get("/collect/agent?hg_label=bot&hg_task=t2", follow_redirects=False)
    assert bad.status_code == 400


def test_loan_otp_persisted_in_db(client, monkeypatch):
    monkeypatch.setenv("FORCE_DECISION", "step_up")
    _login(client, username="aisyah")
    r = client.post("/loan", data={
        "amount": "8000", "tenure_months": "12",
        "monthly_income": "5200", "employer": "Kenanga Labs",
        "hg_last_seq": "0",
    })
    assert r.status_code == 200
    with db.get_session() as s:
        loan = s.execute(text(
            "SELECT l.id, l.otp_code FROM loan_applications l JOIN users u ON u.id=l.user_id"
            " WHERE u.username='aisyah' ORDER BY l.id DESC LIMIT 1")).first()._mapping
    assert loan["otp_code"] and len(loan["otp_code"]) == 6
    ok = client.post("/otp", data={"kind": "loan", "item_id": str(loan["id"]),
                                   "otp": loan["otp_code"]})
    assert ok.status_code == 200 and "submitted" in ok.text


def test_new_payee_flag(client, monkeypatch):
    from app import main as portal_main
    seen = {}

    def fake_decide(action, sid, last_seq, context):
        seen.update(context)
        return {"decision": "allow", "score": None, "band": None,
                "model_version": "test", "latency_ms": 0}

    monkeypatch.setattr(portal_main, "decide", fake_decide)
    monkeypatch.delenv("FORCE_DECISION", raising=False)
    _login(client)
    with db.get_session() as s:
        known = s.execute(text(
            "SELECT p.name, p.bank, p.account_number FROM payees p JOIN users u"
            " ON u.id=p.user_id WHERE u.username='daniel' LIMIT 1")).first()._mapping
    form = _confirm_form(amount_cents=100)
    form.update(to_name=known["name"], to_bank=known["bank"],
                to_account=known["account_number"])
    client.post("/transfer/confirm", data=form)
    assert seen["new_payee"] is False
    client.post("/transfer/confirm", data=_confirm_form(amount_cents=100))
    assert seen["new_payee"] is True


def test_cookies_secure_in_cloud(client, monkeypatch):
    from harnessguard_core.config import get_settings
    monkeypatch.setenv("ENV", "cloud")
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    try:
        r = client.get("/login")
        assert "secure" in r.headers.get("set-cookie", "").lower()
    finally:
        monkeypatch.setenv("ENV", "local")
        if hasattr(get_settings, "cache_clear"):
            get_settings.cache_clear()
