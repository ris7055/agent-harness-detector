"""Core package tests: schema init, seed idempotency, tasks, events."""

from __future__ import annotations

import random
import uuid

import pytest
from sqlalchemy import text

from harnessguard_core import db
from harnessguard_core.events import EventBatch
from harnessguard_core.seed import hash_password, seed, verify_password
from harnessguard_core.tasks import TASK_KINDS, generate_task


def _count(s, table):
    return s.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_schema_init_and_seed_idempotent():
    db.init_db()  # second run must not fail
    with db.get_session() as s:
        seed(s)  # second run must be a no-op

        assert _count(s, "users") == 5
        assert _count(s, "accounts") == 5
        assert s.execute(
            text("SELECT count(*) FROM accounts WHERE balance_cents BETWEEN 500000 AND 2500000")
        ).scalar_one() == 5
        assert _count(s, "transfers") == 25  # 5 past transactions per account
        assert _count(s, "payees") == 10  # 2 per user


def test_password_hash_roundtrip():
    stored = hash_password("Seroja@2026")
    assert verify_password("Seroja@2026", stored)
    assert not verify_password("wrong", stored)


def test_generate_task_all_kinds_and_deterministic_id():
    for kind in TASK_KINDS:
        task = generate_task(kind=kind, rng=random.Random(1))
        assert task["kind"] == kind
        assert task["task_id"] and task["text"]
        # deterministic: same params -> same task_id
        again = generate_task(kind=kind, rng=random.Random(1))
        assert again["task_id"] == task["task_id"]


def test_generate_task_unknown_kind_rejected():
    with pytest.raises(ValueError):
        generate_task(kind="nonsense")


def test_event_batch_model():
    batch = EventBatch.model_validate(
        {
            "session_id": str(uuid.uuid4()),
            "page_load_id": str(uuid.uuid4()),
            "sent_at": 1760000000000,
            "events": [
                {
                    "seq": 1,
                    "t": 12.5,
                    "wall": 1760000000000,
                    "type": "page",
                    "page": "/login",
                    "data": {"path": "/login", "referrer_path": ""},
                },
                {
                    "seq": 2,
                    "t": 50.0,
                    "wall": 1760000000040,
                    "type": "keydown",
                    "page": "/login",
                    # privacy: key CLASS and field only, never the key value
                    "data": {"key_class": "char", "field_id": "username", "is_trusted": True},
                },
            ],
        }
    )
    assert len(batch.events) == 2

    with pytest.raises(Exception):
        EventBatch.model_validate(
            {
                "session_id": str(uuid.uuid4()),
                "page_load_id": str(uuid.uuid4()),
                "sent_at": 1,
                "events": [
                    {"seq": 1, "t": 0.0, "wall": 1, "type": "not_a_type",
                     "page": "/", "data": {}}
                ],
            }
        )
