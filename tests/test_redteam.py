"""Red-team unit tests (task D4). Offline: no browser, no network, mock policy."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from redteam.agent import mock_action  # noqa: E402
from redteam.common import (TargetNotAllowed, check_target, make_task,  # noqa: E402
                            otp_from_text, read_outcome, start_url)


def test_target_guard_allows_localhost():
    assert check_target("http://localhost:8080") == "http://localhost:8080"
    assert check_target("http://127.0.0.1:8080/") == "http://127.0.0.1:8080"


def test_target_guard_blocks_remote_without_optin():
    with pytest.raises(TargetNotAllowed):
        check_target("https://some-bank.example")


def test_target_guard_allows_remote_with_optin():
    assert check_target("https://my-portal.run.app", i_own_this_target=True) \
        == "https://my-portal.run.app"


def test_start_url_is_labelled_agent():
    url = start_url("http://localhost:8080", "llm_headless", "abc123")
    assert "hg_label=agent" in url and "hg_variant=llm_headless" in url
    assert "hg_task=abc123" in url


def test_make_task_reuses_portal_generator():
    task = make_task("transfer_new_payee", random.Random(1))
    assert task["kind"] == "transfer_new_payee"
    assert "username" in task["params"] and task["task_id"]


def test_outcome_and_otp_parsing():
    assert read_outcome("Transfer held for review  Reference CASE-0001", False) == "block"
    assert read_outcome("Transfer successful", False) == "allow"
    assert read_outcome("Transfer successful", True) == "step_up"
    assert read_outcome("still on the form", False) is None
    assert otp_from_text("SMS simulation: your code is 482913 ×") == "482913"
    assert otp_from_text("no code here") is None


def _obs(url, elements, text=""):
    return {"url": url, "title": "", "text": text,
            "elements": [{k: v for k, v in e.items() if k != "_handle"} for e in elements],
            "_els": elements, "task": "t"}


def test_mock_policy_fills_login_then_submits():
    task = make_task("browse_only", random.Random(2))
    els = [
        {"index": 0, "tag": "input", "type": "text", "id": "username", "name": "username",
         "label": "", "options": None, "value_len": 0},
        {"index": 1, "tag": "input", "type": "password", "id": "password", "name": "password",
         "label": "", "options": None, "value_len": 0},
        {"index": 2, "tag": "button", "type": "submit", "id": "", "name": "",
         "label": "Sign in", "options": None, "value_len": 0},
    ]
    a1 = mock_action(_obs("http://localhost:8080/login", els), task, [])
    assert a1 == {"action": "type", "index": 0, "text": task["params"]["username"]}
    els[0]["value_len"] = 8  # username now filled
    a2 = mock_action(_obs("http://localhost:8080/login", els), task, [])
    assert a2["action"] == "type" and a2["index"] == 1
    els[1]["value_len"] = 11  # password filled
    a3 = mock_action(_obs("http://localhost:8080/login", els), task, [])
    assert a3 == {"action": "click", "index": 2}


def test_mock_policy_enters_otp_code():
    task = make_task("transfer_new_payee", random.Random(3))
    els = [
        {"index": 0, "tag": "input", "type": "text", "id": "otp", "name": "otp",
         "label": "", "options": None, "value_len": 0},
        {"index": 1, "tag": "button", "type": "submit", "id": "", "name": "",
         "label": "Verify", "options": None, "value_len": 0},
    ]
    obs = _obs("http://localhost:8080/transfer/confirm", els,
               text="SMS simulation: your code is 123456 ×")
    action = mock_action(obs, task, [])
    assert action == {"action": "type", "index": 0, "text": "123456"}
