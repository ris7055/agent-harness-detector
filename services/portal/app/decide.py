"""Decision-point stub (D1).

D2 wires this to ``POST {SCORER_URL}/v1/decide`` with a 2 s timeout and a
fail-open to ``step_up``. For now it returns ``allow`` unless the temporary
``FORCE_DECISION`` env var forces ``allow|step_up|block`` so all three UI
paths can be demoed and tested.
"""

from __future__ import annotations

import os
from typing import Any

_VALID = {"allow", "step_up", "block"}


def decide(action: str, session_id: str | None, last_seq: int, context: dict[str, Any]) -> dict[str, Any]:
    forced = os.environ.get("FORCE_DECISION", "").strip().lower()
    decision = forced if forced in _VALID else "allow"
    return {
        "decision": decision,
        "score": None,
        "band": None,
        "case_id": None,
        "model_version": "stub",
        "latency_ms": 0,
        "top_reasons": [],
    }
