"""Pytest fixtures: a throwaway Postgres for every run.

Database resolution order:
  1. HG_TEST_DATABASE_URL env var -- must point at a DISPOSABLE database
     (all tables are dropped and recreated).
  2. Otherwise a testcontainers postgres:15 container is started.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "services" / "portal"))

os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("IP_HASH_SALT", "test-salt")
os.environ.setdefault("ALLOW_DATA_COLLECTION", "true")


@pytest.fixture(scope="session")
def database_url():
    url = os.environ.get("HG_TEST_DATABASE_URL")
    if url:
        yield url
        return
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:15") as pg:
        # testcontainers returns a psycopg2 URL; we use psycopg 3.
        yield pg.get_connection_url().replace("psycopg2", "psycopg")


@pytest.fixture(scope="session", autouse=True)
def _database(database_url):
    os.environ["DATABASE_URL"] = database_url
    from harnessguard_core import db
    from harnessguard_core.seed import seed

    db.reset_engine()
    engine = db.get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    db.init_db()
    with db.get_session() as s:
        seed(s)
    yield
    db.reset_engine()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c
