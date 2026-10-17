"""Shared helpers for the HarnessGuard red team (SPEC section 9.2, task D4).

These agents generate labelled **automated** sessions against OUR OWN Bank
Seroja demo portal, so the detector has a non-human adversary to measure
against. They do NOT hide that they are automated: no fingerprint spoofing,
no synthetic "human" mouse/keystroke timing. Detecting stock browser
automation is the realistic threat model; evasion is out of scope (noted as
Future Work in the benchmark).

``check_target`` refuses any host other than localhost unless the operator
states they own it.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
# Reuse the portal's task generator so humans and agents do identical tasks.
sys.path.insert(0, str(ROOT / "core"))

from harnessguard_core.tasks import TASK_KINDS, generate_task  # noqa: E402

RUNS_LOG = ROOT / "data" / "redteam_runs.jsonl"

# Non-evasive variants only. (A stealth / anti-detection variant is
# deliberately NOT implemented — see redteam/README.md.)
VARIANTS = ["script_fill", "script_type", "llm_headless", "llm_headed"]

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

# Text markers on the portal's result pages -> outcome.
OUTCOME_MARKERS = [
    ("held for review", "block"),
    ("Transfer blocked", "block"),
    ("Application blocked", "block"),
    ("Transfer failed", "block"),
    ("Transfer successful", "completed"),
    ("Loan application submitted", "completed"),
]
OTP_MARKER = "SMS simulation: your code is"


class TargetNotAllowed(ValueError):
    pass


def check_target(base_url: str, i_own_this_target: bool = False) -> str:
    """Only localhost by default; any other host needs an explicit opt-in."""
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise TargetNotAllowed(f"not a valid http(s) URL: {base_url!r}")
    if parsed.hostname not in LOCAL_HOSTS and not i_own_this_target:
        raise TargetNotAllowed(
            f"refusing to run against {parsed.hostname}: the red team only targets "
            "your own Bank Seroja deployment. If this is your own Cloud Run portal, "
            "re-run with --i-own-this-target."
        )
    return base_url.rstrip("/")


def make_task(kind: str | None, rng: random.Random) -> dict[str, Any]:
    if kind in (None, "", "random"):
        kind = rng.choice(TASK_KINDS)
    return generate_task(kind=kind, rng=rng)


def start_url(base: str, variant: str, task_id: str) -> str:
    """Labelled data-collection entry: new session, logged out, label=agent."""
    return (f"{base}/collect/agent?hg_label=agent&hg_variant={variant}"
            f"&hg_task={task_id}")


def read_outcome(body_text: str, saw_otp: bool) -> str | None:
    """Final outcome from page text; None if the run has not finished yet."""
    for marker, kind in OUTCOME_MARKERS:
        if marker in body_text:
            if kind == "completed":
                return "step_up" if saw_otp else "allow"
            return kind
    return None


def otp_from_text(body_text: str) -> str | None:
    """Read the simulated OTP shown on the demo OTP page (demo only)."""
    idx = body_text.find(OTP_MARKER)
    if idx < 0:
        return None
    tail = body_text[idx + len(OTP_MARKER): idx + len(OTP_MARKER) + 20]
    digits = "".join(ch for ch in tail if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else None


def click_submit(page, selector_or_handle: Any, timeout_ms: int = 5000) -> None:
    """Click a submit control and wait for the navigation it triggers.

    The portal's collector flushes telemetry before a form submits, so the
    real navigation happens a moment after the click (not synchronously). We
    wait for it explicitly; if no navigation occurs we carry on.
    """
    try:
        with page.expect_navigation(wait_until="networkidle", timeout=timeout_ms):
            if isinstance(selector_or_handle, str):
                page.click(selector_or_handle)
            else:
                selector_or_handle.click()
    except Exception:  # noqa: BLE001 - no navigation fired; nothing to wait for
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass


def log_run(record: dict[str, Any], path: Path = RUNS_LOG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(timezone.utc).isoformat(), **record}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
