"""Scripted Playwright flows (SPEC section 9.2: script_fill, script_type).

Deterministic automation of each task kind. These are ordinary Playwright
scripts -- they do not disguise the browser. ``mode='fill'`` sets values with
``page.fill`` (instant); ``mode='type'`` uses ``page.type`` with a small fixed
delay. Both leave the normal automation signals (navigator.webdriver, etc.)
untouched.
"""

from __future__ import annotations

from typing import Any

from .common import click_submit, otp_from_text, read_outcome

TYPE_DELAY_MS = 60  # script_type: a plain per-key delay, not humanised timing


def _set(page, selector: str, value: str, mode: str) -> None:
    if mode == "type":
        page.click(selector)
        page.type(selector, value, delay=TYPE_DELAY_MS)
    else:
        page.fill(selector, value)


def _login(page, base: str, p: dict[str, Any], mode: str) -> None:
    page.goto(f"{base}/login")
    _set(page, "#username", p["username"], mode)
    _set(page, "#password", p["password"], mode)
    click_submit(page, "button[type=submit]")


def _do_transfer(page, base: str, p: dict[str, Any], mode: str) -> None:
    page.goto(f"{base}/transfer")
    _set(page, "#to_name", str(p["to_name"]), mode)
    page.select_option("#to_bank", str(p["to_bank"]))
    _set(page, "#to_account", str(p["to_account"]), mode)
    _set(page, "#amount", f"{p['amount']}", mode)
    _set(page, "#reference", str(p.get("reference", "")), mode)
    click_submit(page, "button[type=submit]")                  # -> review
    click_submit(page, "form[action='/transfer/confirm'] button[type=submit]")


def _do_loan(page, base: str, p: dict[str, Any], mode: str) -> None:
    page.goto(f"{base}/loan")
    _set(page, "#amount", f"{p['amount']}", mode)
    page.select_option("#tenure_months", str(p["tenure_months"]))  # it is a <select>
    _set(page, "#monthly_income", f"{p['monthly_income']}", mode)
    _set(page, "#employer", str(p["employer"]), mode)
    click_submit(page, "button[type=submit]")


def _maybe_otp(page) -> bool:
    """If the demo OTP page appeared, submit the shown code once. Returns True
    if an OTP challenge was seen (i.e. the decision was step_up)."""
    body = page.inner_text("body")
    code = otp_from_text(body)
    if code is None:
        return False
    page.fill("#otp", code)
    click_submit(page, "button[type=submit]")
    return True


def run_scripted(page, base: str, task: dict[str, Any], mode: str) -> dict[str, Any]:
    """Execute one task with a scripted flow. Returns {outcome, steps, saw_otp}."""
    p = task["params"]
    kind = task["kind"]
    _login(page, base, p, mode)
    saw_otp = False
    if kind in ("transfer_known", "transfer_new_payee"):
        _do_transfer(page, base, p, mode)
        saw_otp = _maybe_otp(page)
    elif kind == "loan_apply":
        _do_loan(page, base, p, mode)
        saw_otp = _maybe_otp(page)
    else:  # browse_only
        page.goto(f"{base}/dashboard")
        page.wait_for_load_state("networkidle")
    body = page.inner_text("body")
    outcome = read_outcome(body, saw_otp)
    if outcome is None:
        outcome = "incomplete" if kind != "browse_only" else "allow"
    return {"outcome": outcome, "saw_otp": saw_otp}
