"""Bank Seroja portal -- fictional demo bank (SPEC section 7.1, task D1)."""

from __future__ import annotations

import logging
import random
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from harnessguard_core import db, models
from harnessguard_core.config import get_settings
from harnessguard_core.events import EventBatch
from harnessguard_core.seed import seed, verify_password
from harnessguard_core.tasks import BANKS, USERNAMES, generate_task

from .decide import decide
from .security import ip_hash, sign_value, verify_signed

log = logging.getLogger("portal")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

MAX_OTP_ATTEMPTS = 3

# Pending OTPs for loan applications (process-local; transfers keep theirs in
# the transfers table). Key: loan id -> {"code": str, "attempts": int}.
_LOAN_OTPS: dict[int, dict] = {}


def _rm(cents: int | None) -> str:
    return f"RM {((cents or 0) / 100):,.2f}"


templates.env.filters["rm"] = _rm


def _parse_amount_cents(raw: str) -> int | None:
    try:
        cents = int((Decimal(raw.replace(",", "").strip()) * 100).quantize(Decimal("1")))
        return cents if cents > 0 else None
    except (InvalidOperation, ValueError):
        return None


def _render(request: Request, template: str, status: int = 200, **ctx) -> HTMLResponse:
    ctx.setdefault("user", getattr(request.state, "user", None))
    ctx["hg_session"] = getattr(request.state, "hg_sid", "")
    return templates.TemplateResponse(
        request, template, ctx, status_code=status
    )


def _current_user(request: Request) -> dict | None:
    uid = verify_signed(request.cookies.get("hg_auth"))
    if uid is None:
        return None
    with db.get_session() as s:
        return models.get_user(s, int(uid))


class SessionMiddleware(BaseHTTPMiddleware):
    """Assigns hg_sid (UUID4) cookie + sessions row with salted IP hash."""

    SKIP = {"/healthz"}

    async def dispatch(self, request: Request, call_next):
        raw = request.cookies.get("hg_sid")
        try:
            sid = str(uuid.UUID(raw)) if raw else None
        except ValueError:
            sid = None
        if sid is None:
            sid = str(uuid.uuid4())

        if request.url.path not in self.SKIP and not request.url.path.startswith("/static"):
            ip = request.client.host if request.client else ""
            with db.get_session() as s:
                models.ensure_session(
                    s, sid, request.headers.get("user-agent"), ip_hash(ip)
                )
                s.commit()

        request.state.hg_sid = sid
        request.state.user = _current_user(request)
        response = await call_next(request)
        response.set_cookie("hg_sid", sid, httponly=True, samesite="lax")
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    with db.get_session() as s:
        seed(s)
    yield


app = FastAPI(title="Bank Seroja (HarnessGuard demo portal)", lifespan=lifespan)
app.add_middleware(SessionMiddleware)
_static = BASE_DIR / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")


def _login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


# ----------------------------------------------------------------- pages

@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/dashboard"):
    return _render(request, "login.html", next=next)


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...),
          next: str = Form("/dashboard")):
    with db.get_session() as s:
        user = models.get_user_by_username(s, username.strip().lower())
        if not user or not verify_password(password, user["password_hash"]):
            return _render(
                request, "login.html", status=401,
                error="Invalid username or password.", next=next,
            )
        models.set_session_user(s, request.state.hg_sid, user["id"])
        s.commit()
    target = next if next.startswith("/") else "/dashboard"
    resp = RedirectResponse(target, status_code=303)
    resp.set_cookie("hg_auth", sign_value(str(user["id"])), httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("hg_auth")
    return resp


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = request.state.user
    if not user:
        return _login_redirect()
    with db.get_session() as s:
        account = models.get_account_for_user(s, user["id"])
        transactions = models.recent_transfers(s, account["id"]) if account else []
    return _render(
        request, "dashboard.html", account=account, transactions=transactions,
    )


@app.get("/transfer", response_class=HTMLResponse)
def transfer_form(request: Request):
    if not request.state.user:
        return _login_redirect()
    with db.get_session() as s:
        account = models.get_account_for_user(s, request.state.user["id"])
    return _render(request, "transfer.html", banks=BANKS, account=account)


@app.post("/transfer", response_class=HTMLResponse)
def transfer_review(request: Request,
                    to_name: str = Form(...), to_bank: str = Form(...),
                    to_account: str = Form(...), amount: str = Form(...),
                    reference: str = Form("")):
    user = request.state.user
    if not user:
        return _login_redirect()
    with db.get_session() as s:
        account = models.get_account_for_user(s, user["id"])

    amount_cents = _parse_amount_cents(amount)
    error = None
    if not to_name.strip() or not to_account.strip():
        error = "Recipient name and account number are required."
    elif to_bank not in BANKS:
        error = "Please choose a recipient bank."
    elif amount_cents is None:
        error = "Enter a valid amount greater than RM 0."
    elif account and amount_cents > account["balance_cents"]:
        error = "Insufficient balance for this transfer."
    if error:
        return _render(request, "transfer.html", status=400, error=error,
                       banks=BANKS, account=account,
                       form={"to_name": to_name, "to_bank": to_bank,
                             "to_account": to_account, "amount": amount,
                             "reference": reference})
    return _render(request, "transfer_review.html",
                   to_name=to_name.strip(), to_bank=to_bank,
                   to_account=to_account.strip(), amount_cents=amount_cents,
                   amount=amount, reference=reference.strip())


@app.post("/transfer/confirm", response_class=HTMLResponse)
def transfer_confirm(request: Request,
                     to_name: str = Form(...), to_bank: str = Form(...),
                     to_account: str = Form(...), amount_cents: int = Form(...),
                     reference: str = Form(""), hg_last_seq: int = Form(0)):
    user = request.state.user
    if not user:
        return _login_redirect()
    sid = request.state.hg_sid

    with db.get_session() as s:
        account = models.get_account_for_user(s, user["id"])
        result = decide(
            "transfer", sid, hg_last_seq,
            {"amount_cents": amount_cents, "to_account": to_account,
             "new_payee": True},
        )
        decision = result["decision"]
        decision_id = models.record_decision(
            s, sid, "transfer", decision, score=result.get("score"),
            band=result.get("band"), model_version=result.get("model_version"),
            latency_ms=result.get("latency_ms"),
        )

        if decision == "allow":
            if not account or amount_cents > account["balance_cents"]:
                s.rollback()
                return _render(request, "transfer.html", status=400,
                               banks=BANKS, account=account,
                               error="Insufficient balance for this transfer.")
            models.create_transfer(
                s, account["id"], sid, to_name, to_bank, to_account,
                amount_cents, reference, "completed",
            )
            models.debit_account(s, account["id"], amount_cents)
            s.commit()
            return _render(request, "result.html", kind="success",
                           title="Transfer successful",
                           message=f"{_rm(amount_cents)} was sent to {to_name} "
                                   f"({to_bank}, account {to_account}).",
                           reference=reference)

        if decision == "step_up":
            otp = f"{random.randint(0, 999999):06d}"
            tid = models.create_transfer(
                s, account["id"], sid, to_name, to_bank, to_account,
                amount_cents, reference, "pending_otp", otp_code=otp,
            )
            s.commit()
            return _render(request, "otp.html", kind="transfer", item_id=tid,
                           otp_code=otp,
                           message="For your security we sent a 6-digit code "
                                   "to your registered mobile number.")

        # block
        models.create_transfer(
            s, account["id"], sid, to_name, to_bank, to_account,
            amount_cents, reference, "blocked",
        )
        case_id = models.create_case(s, sid, decision_id, "transfer", "block",
                                     score=result.get("score"))
        s.commit()
        return _render(request, "result.html", kind="blocked",
                       title="Transfer held for review",
                       message="This transfer has been held while our team "
                               "reviews the session.",
                       case_ref=f"CASE-{case_id:04d}")


@app.post("/otp", response_class=HTMLResponse)
def otp_verify(request: Request, kind: str = Form(...), item_id: int = Form(...),
               otp: str = Form("")):
    user = request.state.user
    if not user:
        return _login_redirect()

    if kind == "transfer":
        with db.get_session() as s:
            transfer = models.get_transfer(s, item_id)
            account = models.get_account_for_user(s, user["id"])
            if (not transfer or not account
                    or transfer["account_id"] != account["id"]
                    or transfer["status"] != "pending_otp"):
                return _render(request, "result.html", status=400, kind="blocked",
                               title="Transfer unavailable",
                               message="This transfer is no longer awaiting a code.")

            if otp.strip() == (transfer["otp_code"] or ""):
                if transfer["amount_cents"] > account["balance_cents"]:
                    s.execute(
                        text("UPDATE transfers SET status='failed_otp' WHERE id=:i"),
                        {"i": item_id},
                    )
                    s.commit()
                    return _render(request, "result.html", status=400, kind="blocked",
                                   title="Transfer failed",
                                   message="Insufficient balance.")
                s.execute(
                    text("UPDATE transfers SET status='completed' WHERE id=:i"),
                    {"i": item_id},
                )
                models.debit_account(s, account["id"], transfer["amount_cents"])
                s.commit()
                return _render(request, "result.html", kind="success",
                               title="Transfer successful",
                               message=f"{_rm(transfer['amount_cents'])} was sent to "
                                       f"{transfer['to_name']} ({transfer['to_bank']}, "
                                       f"account {transfer['to_account']}).",
                               reference=transfer["reference"])

            attempts = transfer["otp_attempts"] + 1
            status = "failed_otp" if attempts >= MAX_OTP_ATTEMPTS else "pending_otp"
            s.execute(
                text("UPDATE transfers SET otp_attempts=:n, status=:st WHERE id=:i"),
                {"n": attempts, "st": status, "i": item_id},
            )
            s.commit()
            if attempts >= MAX_OTP_ATTEMPTS:
                return _render(request, "result.html", kind="blocked",
                               title="Transfer blocked",
                               message="Too many incorrect codes. The transfer "
                                       "was not completed.")
            return _render(request, "otp.html", status=401, kind="transfer",
                           item_id=item_id, otp_code=transfer["otp_code"],
                           error=f"Incorrect code. {MAX_OTP_ATTEMPTS - attempts} "
                                 f"attempt(s) left.")

    if kind == "loan":
        pending = _LOAN_OTPS.get(item_id)
        with db.get_session() as s:
            loan = None
            if pending:
                loan = models.row_to_dict(s.execute(
                    text("SELECT * FROM loan_applications WHERE id=:i"),
                    {"i": item_id}).first())
            if not pending or not loan or loan["user_id"] != user["id"] \
                    or loan["status"] != "pending_otp":
                return _render(request, "result.html", status=400, kind="blocked",
                               title="Application unavailable",
                               message="This application is no longer awaiting a code.")
            if otp.strip() == pending["code"]:
                s.execute(
                    text("UPDATE loan_applications SET status='approved' WHERE id=:i"),
                    {"i": item_id},
                )
                s.commit()
                _LOAN_OTPS.pop(item_id, None)
                return _render(request, "result.html", kind="success",
                               title="Loan application submitted",
                               message="Your loan application was submitted for "
                                       "processing.")
            pending["attempts"] += 1
            if pending["attempts"] >= MAX_OTP_ATTEMPTS:
                s.execute(
                    text("UPDATE loan_applications SET status='failed_otp' WHERE id=:i"),
                    {"i": item_id},
                )
                s.commit()
                _LOAN_OTPS.pop(item_id, None)
                return _render(request, "result.html", kind="blocked",
                               title="Application blocked",
                               message="Too many incorrect codes. The application "
                                       "was not submitted.")
            return _render(request, "otp.html", status=401, kind="loan",
                           item_id=item_id, otp_code=pending["code"],
                           error=f"Incorrect code. "
                                 f"{MAX_OTP_ATTEMPTS - pending['attempts']} attempt(s) left.")

    return _render(request, "result.html", status=400, kind="blocked",
                   title="Bad request", message="Unknown verification target.")


@app.get("/loan", response_class=HTMLResponse)
def loan_form(request: Request):
    if not request.state.user:
        return _login_redirect()
    return _render(request, "loan.html")


@app.post("/loan", response_class=HTMLResponse)
def loan_apply(request: Request,
               amount: str = Form(...), tenure_months: int = Form(...),
               monthly_income: str = Form(...), employer: str = Form(...),
               hg_last_seq: int = Form(0)):
    user = request.state.user
    if not user:
        return _login_redirect()
    sid = request.state.hg_sid
    amount_cents = _parse_amount_cents(amount)
    income_cents = _parse_amount_cents(monthly_income)
    if amount_cents is None or income_cents is None or not employer.strip() \
            or tenure_months <= 0:
        return _render(request, "loan.html", status=400,
                       error="Please complete all fields with valid values.")

    with db.get_session() as s:
        result = decide("loan_apply", sid, hg_last_seq,
                        {"amount_cents": amount_cents})
        decision = result["decision"]
        decision_id = models.record_decision(
            s, sid, "loan_apply", decision, score=result.get("score"),
            band=result.get("band"), model_version=result.get("model_version"),
            latency_ms=result.get("latency_ms"),
        )
        status = {"allow": "approved", "step_up": "pending_otp",
                  "block": "blocked"}[decision]
        loan_id = s.execute(
            text(
                "INSERT INTO loan_applications (user_id, session_id, amount_cents,"
                " tenure_months, monthly_income_cents, employer, status)"
                " VALUES (:u, :sid, :amt, :ten, :inc, :emp, :st) RETURNING id"
            ),
            {"u": user["id"], "sid": uuid.UUID(sid), "amt": amount_cents,
             "ten": tenure_months, "inc": income_cents, "emp": employer.strip(),
             "st": status},
        ).scalar_one()

        if decision == "allow":
            s.commit()
            return _render(request, "result.html", kind="success",
                           title="Loan application submitted",
                           message=f"Your application for {_rm(amount_cents)} over "
                                   f"{tenure_months} months was submitted for "
                                   f"processing.")
        if decision == "step_up":
            otp = f"{random.randint(0, 999999):06d}"
            _LOAN_OTPS[loan_id] = {"code": otp, "attempts": 0}
            s.commit()
            return _render(request, "otp.html", kind="loan", item_id=loan_id,
                           otp_code=otp,
                           message="For your security we sent a 6-digit code "
                                   "to your registered mobile number.")
        case_id = models.create_case(s, sid, decision_id, "loan_apply", "block",
                                     score=result.get("score"))
        s.commit()
        return _render(request, "result.html", kind="blocked",
                       title="Application held for review",
                       message="This application has been held while our team "
                               "reviews the session.",
                       case_ref=f"CASE-{case_id:04d}")


# ----------------------------------------------------------------- telemetry

@app.post("/api/events")
async def api_events(request: Request, batch: EventBatch):
    """Validate telemetry batches (SPEC 5.3). Forwarding to the scorer/Pub/Sub
    is wired by D2; for now batches are accepted and dropped."""
    transport = get_settings().event_transport
    if transport == "http" and get_settings().scorer_url:
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                await client.post(
                    f"{get_settings().scorer_url.rstrip('/')}/v1/events",
                    content=batch.model_dump_json(),
                    headers={"Content-Type": "application/json"},
                )
        except Exception:
            log.debug("scorer /v1/events unreachable; dropping batch")
    return Response(status_code=204)


# ----------------------------------------------------------------- collect

@app.get("/collect", response_class=HTMLResponse)
def collect_page(request: Request):
    if not get_settings().allow_data_collection:
        return _render(request, "result.html", status=404, kind="blocked",
                       title="Not found", message="This page does not exist.")
    return _render(request, "collect.html")


@app.post("/collect", response_class=HTMLResponse)
def collect_start(request: Request, collector: str = Form(...)):
    if not get_settings().allow_data_collection:
        return _render(request, "result.html", status=404, kind="blocked",
                       title="Not found", message="This page does not exist.")
    sid = request.state.hg_sid
    rng = random.Random()
    kind = rng.choice(["transfer_known", "transfer_new_payee", "loan_apply",
                       "browse_only"])
    username = rng.choice(USERNAMES)
    known_payees = None
    if kind == "transfer_known":
        with db.get_session() as s:
            u = models.get_user_by_username(s, username)
            known_payees = models.get_payees_for_user(s, u["id"]) if u else None
    task = generate_task(kind=kind, rng=rng, username=username,
                         known_payees=known_payees)
    with db.get_session() as s:
        models.record_label(s, sid, "human", collector=collector.strip(),
                            task_id=task["task_id"])
        s.commit()
    return _render(request, "collect_task.html", task=task,
                   collector=collector.strip())


@app.get("/collect/agent")
def collect_agent(request: Request, hg_label: str = "agent",
                  hg_variant: str | None = None, hg_task: str | None = None):
    if not get_settings().allow_data_collection:
        return _render(request, "result.html", status=404, kind="blocked",
                       title="Not found", message="This page does not exist.")
    with db.get_session() as s:
        models.record_label(s, request.state.hg_sid, hg_label,
                            variant=hg_variant, collector="redteam",
                            task_id=hg_task)
        s.commit()
    return RedirectResponse("/login", status_code=303)


# ----------------------------------------------------------------- misc

@app.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok", "service": "portal"})
