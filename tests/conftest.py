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
os.environ.setdefault("INTERNAL_TOKEN", "test-internal")
os.environ.setdefault("PUBSUB_PUSH_TOKEN", "test-push")
os.environ.setdefault("SCORER_URL", "http://scorer.test")
os.environ.setdefault("CONSOLE_PASSWORD", "test-console")


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


def load_scorer_app():
    """Import services/scorer/app under the name `scorer_app` (the portal
    package already owns the plain name `app`)."""
    import importlib.util

    if "scorer_app.main" in sys.modules:
        return sys.modules["scorer_app.main"].app
    pkg_dir = ROOT / "services" / "scorer" / "app"
    spec = importlib.util.spec_from_file_location(
        "scorer_app",
        pkg_dir / "__init__.py",
        submodule_search_locations=[str(pkg_dir)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["scorer_app"] = module
    spec.loader.exec_module(module)
    import scorer_app.main  # noqa: F401

    return sys.modules["scorer_app.main"].app


@pytest.fixture()
def scorer_client():
    """In-process scorer app sharing the test database."""
    from fastapi.testclient import TestClient

    with TestClient(load_scorer_app()) as c:
        yield c


def load_console_app():
    """Import services/console/app under the name `console_app` (the portal
    package already owns the plain name `app`)."""
    import importlib.util

    if "console_app.main" in sys.modules:
        return sys.modules["console_app.main"].app
    pkg_dir = ROOT / "services" / "console" / "app"
    spec = importlib.util.spec_from_file_location(
        "console_app",
        pkg_dir / "__init__.py",
        submodule_search_locations=[str(pkg_dir)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["console_app"] = module
    spec.loader.exec_module(module)
    import console_app.main  # noqa: F401

    return sys.modules["console_app.main"].app


@pytest.fixture()
def console_client():
    """In-process console app sharing the test database."""
    from fastapi.testclient import TestClient

    with TestClient(load_console_app()) as c:
        yield c


@pytest.fixture()
def stack(client, scorer_client, monkeypatch):
    """Portal wired to the in-process scorer: its httpx calls are routed
    into the scorer TestClient (same test DB, real HTTP path)."""
    import types
    from urllib.parse import urlparse

    from app import decide as decide_mod
    from app import main as portal_main

    def _route(method, url, **kw):
        kw.pop("timeout", None)  # TestClient doesn't support it; shim is instant
        return scorer_client.request(method, urlparse(url).path, **kw)

    class _AsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kw):
            return _route("POST", url, **kw)

    shim = types.SimpleNamespace(
        AsyncClient=_AsyncClient,
        post=lambda url, **kw: _route("POST", url, **kw),
    )
    monkeypatch.setattr(decide_mod, "httpx", shim)
    monkeypatch.setattr(portal_main, "httpx", shim)
    return client


# Load the scorer and console packages at collection time so test modules
# can `import scorer_app.*` / `console_app.*` directly.
load_scorer_app()
load_console_app()
