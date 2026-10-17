"""Decision-point call to the scorer (SPEC 7.1, task D2).

``POST {SCORER_URL}/v1/decide`` with the ``X-HG-Internal`` shared-secret
header and a 2 s timeout. The scorer is unreachable -> fail-open to
``step_up`` and log. ``FORCE_DECISION`` (allow|step_up|block) still overrides
everything for demos/tests, and the result carries ``source`` so the caller
knows whether the scorer already wrote ``decisions``/``cases`` rows.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from harnessguard_core.config import get_settings

log = logging.getLogger("portal.decide")

_VALID = {"allow", "step_up", "block"}
_TIMEOUT_S = 2.0


def _forced() -> str | None:
    forced = os.environ.get("FORCE_DECISION", "").strip().lower()
    return forced if forced in _VALID else None


def _result(decision: str, source: str, **kw) -> dict[str, Any]:
    return {
        "decision": decision,
        "score": None,
        "band": None,
        "case_id": None,
        "model_version": source,
        "latency_ms": 0,
        "top_reasons": [],
        "source": source,
        **kw,
    }


def decide(action: str, session_id: str | None, last_seq: int,
           context: dict[str, Any]) -> dict[str, Any]:
    forced = _forced()
    if forced:
        return _result(forced, "forced")

    settings = get_settings()
    try:
        resp = httpx.post(
            f"{settings.scorer_url.rstrip('/')}/v1/decide",
            json={
                "session_id": session_id,
                "action": action,
                "last_seq": last_seq,
                "context": context,
            },
            headers={"X-HG-Internal": settings.internal_token},
            timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
        data["source"] = "scorer"
        return data
    except Exception:  # noqa: BLE001 - scorer down must not block banking
        log.warning("scorer /v1/decide failed; failing open to step_up",
                    exc_info=True)
        return _result("step_up", "failopen")
