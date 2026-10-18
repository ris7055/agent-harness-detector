"""HarnessGuard analyst console (SPEC section 7.5, task D5).

Server-rendered dashboard (Jinja + Tailwind + Chart.js) protected by a
single shared password (``CONSOLE_PASSWORD``, cookie session). Reads the
operational database directly; the only scorer call is "Regenerate
explanation" on a case page.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import (HTMLResponse, JSONResponse, RedirectResponse,
                               Response, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from markupsafe import Markup
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from harnessguard_core import db
from harnessguard_core.config import get_settings
from harnessguard_core.rules import score_rules

from . import queries

log = logging.getLogger("console")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

AUTH_COOKIE = "hg_console"
PUBLIC_PATHS = {"/login", "/healthz"}
CASE_STATUSES = {"confirmed_fraud", "false_positive"}


# ------------------------------------------------------------------- auth

def _auth_value() -> str:
    """Signed cookie payload proving the analyst knows CONSOLE_PASSWORD."""
    key = get_settings().console_password.encode()
    sig = hmac.new(key, b"console-analyst", hashlib.sha256).hexdigest()[:32]
    return f"console.{sig}"


def _authed(request: Request) -> bool:
    return hmac.compare_digest(
        request.cookies.get(AUTH_COOKIE) or "", _auth_value()
    )


def _safe_next(target: str | None) -> str:
    if (not target or not target.startswith("/")
            or target.startswith("//") or target.startswith("/\\")):
        return "/"
    return target


class ConsoleAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if (path not in PUBLIC_PATHS and not path.startswith("/static")
                and not _authed(request)):
            if path.startswith("/api/"):
                return JSONResponse({"error": "authentication required"},
                                    status_code=401)
            return RedirectResponse(
                f"/login?next={request.url.path}", status_code=303
            )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="HarnessGuard console", lifespan=lifespan)
app.add_middleware(ConsoleAuthMiddleware)

STATIC_DIR = BASE_DIR.parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _render(request: Request, template: str, status: int = 200, **ctx):
    ctx.setdefault("page", "")
    return templates.TemplateResponse(request, template, ctx,
                                      status_code=status)


def _json(data: Any) -> str:
    """JSON for inlining into <script> safely (no </script> break-out)."""
    return json.dumps(data, default=str).replace("</", "<\\/")


def _tojson_safe(data: Any) -> Markup:
    # Markup: Jinja autoescape would otherwise turn quotes into &#34; and
    # break the inline <script> (blank reasons chart, replay and timeline).
    return Markup(_json(data))


templates.env.filters["tojson_safe"] = _tojson_safe


def _fmt_dt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _reasons(features: Any, n: int = 5) -> list[dict[str, Any]]:
    """Top reasons recomputed from the stored feature snapshot.

    For the rules baseline this reproduces the scorer's reasons exactly
    (same code path); for a trained model it is an approximation since
    top_reasons are not persisted on the decision row.
    """
    if not isinstance(features, dict) or not features:
        return []
    try:
        _, reasons = score_rules(features)
    except Exception:  # noqa: BLE001 - a display helper must not 500
        return []
    return reasons[:n]


def _scorer_post(path: str):
    """Call the scorer's internal API (case explanation regeneration)."""
    settings = get_settings()
    return httpx.post(
        f"{settings.scorer_url.rstrip('/')}{path}",
        headers={"X-HG-Internal": settings.internal_token},
        timeout=10.0,
    )


# ------------------------------------------------------------------- auth

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    if _authed(request):
        return RedirectResponse("/", status_code=303)
    return _render(request, "login.html", next=next)


@app.post("/login")
def login(request: Request, password: str = Form(...),
          next: str = Form("/")):
    expected = get_settings().console_password
    if not expected or not hmac.compare_digest(
            password.encode(), expected.encode()):
        return _render(request, "login.html", status=401,
                       error="Incorrect password.", next=next)
    resp = RedirectResponse(_safe_next(next), status_code=303)
    resp.set_cookie(AUTH_COOKIE, _auth_value(), httponly=True,
                    samesite="lax", secure=get_settings().env == "cloud")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(AUTH_COOKIE)
    return resp


# ---------------------------------------------------------- live sessions

@app.get("/", response_class=HTMLResponse)
def live_sessions(request: Request):
    return _render(request, "sessions.html", page="sessions")


@app.get("/api/sessions")
def api_sessions():
    return {"sessions": queries.list_sessions()}


# ------------------------------------------------------------------ cases

@app.get("/cases", response_class=HTMLResponse)
def cases_page(request: Request):
    return _render(request, "cases.html", page="cases",
                   cases=queries.list_cases())


@app.get("/cases/{case_id}", response_class=HTMLResponse)
def case_detail(request: Request, case_id: int):
    case = queries.get_case(case_id)
    if case is None:
        return _render(request, "error.html", status=404,
                       title="Case not found",
                       message=f"CASE-{case_id:04d} does not exist.")
    events = queries.session_events(case["session_id"])
    ctx = {
        "case": case,
        "reasons": _reasons(case.get("features")),
        "fingerprint": queries.latest_fingerprint(case["session_id"]),
        "events_json": _json(events),
        "explanation": case.get("explanation")
        if isinstance(case.get("explanation"), dict) else None,
        "short_sid": str(case["session_id"])[:8],
    }
    return _render(request, "case_detail.html", page="cases", **ctx)


@app.post("/cases/{case_id}/status")
def case_status(case_id: int, status: str = Form(...)):
    if status not in CASE_STATUSES:
        return JSONResponse({"error": "invalid status"}, status_code=400)
    if queries.get_case(case_id) is None:
        return JSONResponse({"error": "unknown case"}, status_code=404)
    queries.set_case_status(case_id, status)
    return RedirectResponse(f"/cases/{case_id}", status_code=303)


@app.post("/cases/{case_id}/explain")
def case_explain(case_id: int):
    """Ask the scorer to (re)generate the Gemini explanation."""
    if queries.get_case(case_id) is None:
        return JSONResponse({"error": "unknown case"}, status_code=404)
    try:
        resp = _scorer_post(f"/v1/cases/{case_id}/explain")
        resp.raise_for_status()
    except Exception:  # noqa: BLE001 - scorer down must not break the page
        log.warning("scorer explain call failed", exc_info=True)
    return RedirectResponse(f"/cases/{case_id}", status_code=303)


@app.get("/api/sessions/{session_id}/events")
def api_session_events(session_id: str):
    """Event stream for the mouse-path replay and timelines."""
    return {"events": queries.session_events(session_id)}


# ----------------------------------------------------------- detection log

def _parse_dt(raw: str | None):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _log_filters(request: Request) -> dict[str, Any]:
    p = request.query_params
    return {
        "decision": p.get("decision") or None,
        "band": p.get("band") or None,
        "user": p.get("user") or None,
        "from_ts": _parse_dt(p.get("from")),
        "to_ts": _parse_dt(p.get("to")),
    }


def _log_rows(filters: dict[str, Any]) -> list[dict[str, Any]]:
    rows = queries.list_decisions(**filters)
    for r in rows:
        r["top_reasons"] = _reasons(r.pop("features", None), n=3)
    return rows


@app.get("/log", response_class=HTMLResponse)
def detection_log(request: Request):
    return _render(request, "log.html", page="log",
                   filters=request.query_params,
                   usernames=queries.list_usernames())


@app.get("/api/decisions")
def api_decisions(request: Request):
    return {"decisions": _log_rows(_log_filters(request))}


_CSV_FIELDS = [
    "id", "created_at", "session_id", "username", "action", "amount_cents",
    "score", "band", "decision", "model_version", "latency_ms", "case_id",
    "case_status", "reason_1", "reason_2", "reason_3",
]


@app.get("/log.csv")
def detection_log_csv(request: Request):
    rows = _log_rows(_log_filters(request))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS,
                            extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        r = dict(r)
        for i, reason in enumerate(r.pop("top_reasons", [])[:3], start=1):
            r[f"reason_{i}"] = f"{reason['feature']}={reason['value']}"
        writer.writerow(r)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=detection_log.csv"},
    )


@app.get("/api/decisions/{decision_id}/timeline")
def api_decision_timeline(decision_id: int):
    sid = queries.decision_session_id(decision_id)
    if sid is None:
        return JSONResponse({"error": "unknown decision"}, status_code=404)
    return {"session_id": str(sid), "events": queries.session_events(sid)}


# -------------------------------------------------------------- benchmark

def _load_benchmark() -> dict[str, Any] | None:
    uri = get_settings().benchmark_uri
    if not uri:
        return None
    try:
        if uri.startswith("gs://"):
            from google.cloud import storage  # lazy: only for gs:// URIs

            bucket, _, blob = uri[5:].partition("/")
            raw = (storage.Client().bucket(bucket).blob(blob)
                   .download_as_bytes())
        else:
            raw = Path(uri).read_bytes()
        return json.loads(raw)
    except FileNotFoundError:
        return None  # not generated yet -> "run ml/benchmark.py" page
    except Exception:  # noqa: BLE001 - corrupt/unreadable -> same page
        log.warning("could not load benchmark from %s", uri, exc_info=True)
        return None


@app.get("/benchmark", response_class=HTMLResponse)
def benchmark_page(request: Request):
    data = _load_benchmark()
    return _render(request, "benchmark.html", page="benchmark",
                   benchmark=data, benchmark_json=_json(data or {}),
                   benchmark_uri=get_settings().benchmark_uri)


# ------------------------------------------------------------------ misc

@app.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok", "service": "console"})
