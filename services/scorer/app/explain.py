"""Gemini analyst explanation for flagged sessions (SPEC section 7.4).

``generate_explanation(case_id, scorer)`` rebuilds the explainer input from
the stored case + decision + session telemetry, asks Gemini for a structured
JSON verdict, and stores it in ``cases.explanation`` (jsonb). It is called in
a ``BackgroundTasks`` task right after a case is created and again from
``POST /v1/cases/{id}/explain`` -- it must never raise, so every failure is
captured and stored as ``{"error": ...}`` and the console falls back to the
raw top reasons.

``LLM_MODE``:
  - ``mock``    -> deterministic JSON built from the top reasons (tests, demos
                   with no key).
  - ``apikey``  -> ``genai.Client(api_key=GEMINI_API_KEY)`` (local dev).
  - ``vertex``  -> ``genai.Client(vertexai=True, project, location)``.

Human reference ranges come from the loaded model's ``model_meta.json``
(per-feature median/p25/p75 written by ml/train.py); with no model the
static ``HUMAN_REFERENCE`` defaults below are used.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import time

from sqlalchemy import text

from harnessguard_core import db
from harnessguard_core.config import get_settings

log = logging.getLogger("scorer.explain")

# Static human reference ranges, used until a trained model_meta.json
# provides measured ones (median / p25 / p75 over human sessions).
# Values are approximate medians for an ordinary desktop banking session.
HUMAN_REFERENCE: dict[str, dict[str, float]] = {
    "fp_webdriver": {"median": 0.0, "p25": 0.0, "p75": 0.0},
    "fp_headless_ua": {"median": 0.0, "p25": 0.0, "p75": 0.0},
    "fp_plugins_zero": {"median": 0.0, "p25": 0.0, "p75": 0.0},
    "fp_swiftshader": {"median": 0.0, "p25": 0.0, "p75": 0.0},
    "mouse_move_count": {"median": 220.0, "p25": 80.0, "p75": 600.0},
    "mouse_moves_per_sec": {"median": 14.0, "p25": 6.0, "p75": 26.0},
    "mouse_straightness_mean": {"median": 0.82, "p25": 0.7, "p75": 0.92},
    "mouse_speed_cv": {"median": 0.9, "p25": 0.55, "p75": 1.5},
    "click_no_premove_ratio": {"median": 0.05, "p25": 0.0, "p75": 0.2},
    "click_center_offset_mean": {"median": 0.28, "p25": 0.16, "p75": 0.45},
    "key_interval_mean": {"median": 160.0, "p25": 90.0, "p75": 280.0},
    "key_interval_cv": {"median": 0.55, "p25": 0.35, "p75": 0.85},
    "key_hold_mean": {"median": 85.0, "p25": 60.0, "p75": 120.0},
    "input_programmatic_ratio": {"median": 0.0, "p25": 0.0, "p75": 0.0},
    "time_to_first_interaction_s": {"median": 2.2, "p25": 1.0, "p75": 5.0},
    "actions_per_sec": {"median": 0.8, "p25": 0.35, "p75": 1.6},
}

EXPLANATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["likely_ai_agent", "likely_human", "uncertain"],
        },
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "summary": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "recommended_action": {
            "type": "string",
            "enum": ["allow", "step_up", "block_and_review"],
        },
        "analyst_next_steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "verdict", "confidence", "summary", "evidence",
        "recommended_action", "analyst_next_steps",
    ],
}

_PROMPT_RULES = (
    "You are a fraud analyst assistant for a demo bank. A behavioural model "
    "scored an online-banking session for AI-agent-like automation at a "
    "sensitive action. Write an analyst explanation as JSON only.\n"
    "Rules: never invent signals that are not in the input; cite the concrete "
    "numbers and how they compare to typical human ranges; be concise "
    "(summary = one or two sentences readable in 5 seconds; 3-6 evidence "
    "bullets; 2-4 next steps)."
)


# ------------------------------------------------------------------ input


def _load_case(case_id: int) -> dict[str, Any] | None:
    """Case row + its decision's features/band/model_version."""
    with db.get_session() as s:
        row = s.execute(
            text(
                "SELECT c.id, c.session_id, c.action, c.score, c.decision,"
                " c.status, d.band, d.model_version, d.features"
                " FROM cases c LEFT JOIN decisions d ON d.id = c.decision_id"
                " WHERE c.id = :i"
            ),
            {"i": case_id},
        ).first()
    return dict(row._mapping) if row is not None else None


def case_exists(case_id: int) -> bool:
    with db.get_session() as s:
        return s.execute(
            text("SELECT 1 FROM cases WHERE id=:i"), {"i": case_id}
        ).first() is not None


def _load_context(session_id, action: str) -> dict[str, Any]:
    """Best-effort business context for the decision (amount, payee).

    The ``decisions`` table intentionally stores no request context, so the
    explainer reconstructs it from the session's latest transfer / loan.
    The portal writes that row right after /v1/decide responds, so this
    (background) path polls briefly for it to land.
    """
    for _ in range(4):
        ctx = _load_context_once(session_id, action)
        if ctx:
            return ctx
        time.sleep(0.2)
    return {}


def _load_context_once(session_id, action: str) -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    with db.get_session() as s:
        if action == "transfer":
            row = s.execute(
                text(
                    "SELECT amount_cents, to_name, to_bank, to_account"
                    " FROM transfers WHERE session_id=:s"
                    " ORDER BY created_at DESC LIMIT 1"
                ),
                {"s": session_id},
            ).first()
            if row:
                m = row._mapping
                ctx = {
                    "amount_cents": m["amount_cents"],
                    "to_name": m["to_name"],
                    "to_bank": m["to_bank"],
                    "to_account": m["to_account"],
                }
        elif action == "loan_apply":
            row = s.execute(
                text(
                    "SELECT amount_cents, tenure_months, employer"
                    " FROM loan_applications WHERE session_id=:s"
                    " ORDER BY created_at DESC LIMIT 1"
                ),
                {"s": session_id},
            ).first()
            if row:
                m = row._mapping
                ctx = {
                    "amount_cents": m["amount_cents"],
                    "tenure_months": m["tenure_months"],
                    "employer": m["employer"],
                }
    return ctx


def _load_fingerprint(session_id) -> dict[str, Any]:
    """Compact summary of the latest fingerprint event."""
    with db.get_session() as s:
        row = s.execute(
            text(
                "SELECT data FROM session_events WHERE session_id=:s"
                " AND type='fingerprint' ORDER BY seq DESC LIMIT 1"
            ),
            {"s": session_id},
        ).first()
    if not row or not isinstance(row.data, dict):
        return {}
    d = row.data
    keys = (
        "webdriver", "ua", "languages_count", "plugins_count",
        "hardware_concurrency", "device_memory", "screen_w", "screen_h",
        "inner_w", "inner_h", "outer_w", "outer_h", "dpr", "timezone",
        "touch_points", "has_chrome_obj", "webgl_renderer",
        "notification_permission",
    )
    return {k: d.get(k) for k in keys if k in d}


def _human_reference(scorer_meta: dict[str, Any]) -> dict[str, Any]:
    """Per-feature human median/p25/p75 from model_meta.json, else defaults."""
    for key in ("human_reference", "feature_reference", "feature_stats"):
        ref = scorer_meta.get(key)
        if isinstance(ref, dict) and ref:
            return ref
    return HUMAN_REFERENCE


def build_input(
    case: dict[str, Any],
    top_reasons: list[dict[str, Any]],
    scorer_meta: dict[str, Any],
) -> dict[str, Any]:
    """The prompt payload described by SPEC 7.4."""
    settings = get_settings()
    ref = _human_reference(scorer_meta or {})
    reasons_with_ref = []
    for r in top_reasons[:5]:
        entry = {"feature": r.get("feature"), "value": r.get("value"),
                 "contribution": r.get("contribution")}
        human = ref.get(str(r.get("feature")))
        if isinstance(human, dict):
            entry["human_median"] = human.get("median")
            entry["human_p25"] = human.get("p25")
            entry["human_p75"] = human.get("p75")
        reasons_with_ref.append(entry)
    return {
        "action": case.get("action"),
        "decision": case.get("decision"),
        "score": case.get("score"),
        "band": case.get("band"),
        "thresholds": {"allow_below": settings.allow_below,
                       "block_above": settings.block_above},
        "context": _load_context(case.get("session_id"), case.get("action") or ""),
        "top_reasons": reasons_with_ref,
        "fingerprint": _load_fingerprint(case.get("session_id")),
    }


# ------------------------------------------------------------------ llm


def _mock_explanation(payload: dict[str, Any]) -> dict[str, Any]:
    """Deterministic canned explanation built from the top reasons."""
    score = float(payload.get("score") or 0.0)
    band = payload.get("band") or "green"
    decision = payload.get("decision") or "allow"
    reasons = payload.get("top_reasons") or []
    fp = payload.get("fingerprint") or {}

    verdict = {"red": "likely_ai_agent", "amber": "uncertain",
               "green": "likely_human"}.get(band, "uncertain")
    fp_hits = [r for r in reasons
               if str(r.get("feature", "")).startswith("fp_")]
    confidence = "high" if (score >= 0.9 or len(fp_hits) >= 2) else (
        "medium" if reasons else "low")

    top = reasons[0]["feature"] if reasons else "no dominant signal"
    summary = (
        f"Session scored {score:.2f} ({band}) at the {payload.get('action')} "
        f"action and was {decision.replace('_', ' ')}ed"
        if decision != "step_up" else
        f"Session scored {score:.2f} ({band}) at the {payload.get('action')} "
        f"action and was stepped up to OTP"
    )
    summary += f". Top signal: {top}."

    evidence = []
    for r in reasons:
        feat, val = r.get("feature"), r.get("value")
        line = f"{feat} = {val}"
        if r.get("human_median") is not None:
            line += (f" (typical human median {r['human_median']}, "
                     f"IQR {r.get('human_p25')}–{r.get('human_p75')})")
        evidence.append(line)
    if fp.get("webdriver"):
        evidence.append("navigator.webdriver is true — the browser reports "
                        "it is being driven by automation")
    if not reasons and not fp.get("webdriver"):
        evidence.append("No single dominant signal; the score aggregates "
                        "weak behavioural anomalies")

    recommended = {"allow": "allow", "step_up": "step_up",
                   "block": "block_and_review"}.get(decision, "step_up")
    next_steps = [
        "Replay the mouse path on this case page and compare with a known "
        "human session",
        "Review the fingerprint table (webdriver, headless UA, plugins) for "
        "automation markers",
        "Confirm fraud or mark false positive so the label feeds the next "
        "benchmark run",
    ]
    return {
        "verdict": verdict,
        "confidence": confidence,
        "summary": summary,
        "evidence": evidence[:6],
        "recommended_action": recommended,
        "analyst_next_steps": next_steps,
    }


def _gemini_explanation(payload: dict[str, Any]) -> dict[str, Any]:
    """Call Gemini (apikey or Vertex) for a structured JSON explanation."""
    from google import genai  # lazy: only needed outside mock mode
    from google.genai import types

    settings = get_settings()
    if settings.llm_mode == "vertex":
        client = genai.Client(vertexai=True, project=settings.gcp_project,
                              location=settings.gcp_region)
    else:
        client = genai.Client(api_key=settings.gemini_api_key)
    prompt = (
        f"{_PROMPT_RULES}\n\n"
        f"INPUT:\n{json.dumps(payload, default=str, indent=2)}"
    )
    resp = client.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=EXPLANATION_SCHEMA,
        ),
    )
    data = json.loads(resp.text)
    if not isinstance(data, dict):
        raise ValueError("Gemini returned non-object JSON")
    return {k: data.get(k) for k in EXPLANATION_SCHEMA["required"]}


# ------------------------------------------------------------------ store


def _store(case_id: int, explanation: dict[str, Any]) -> None:
    with db.get_session() as s:
        s.execute(
            text("UPDATE cases SET explanation=CAST(:e AS jsonb) WHERE id=:i"),
            {"e": json.dumps(explanation), "i": case_id},
        )
        s.commit()


def generate_explanation(case_id: int, scorer=None) -> dict[str, Any]:
    """(Re)generate and store the explanation for a case. Never raises.

    ``scorer`` is the live ``Scorer`` instance; its ``score()`` recomputes the
    top reasons from the stored features (identical for rules and XGBoost)
    and its ``meta`` carries the model's human reference ranges.
    """
    try:
        case = _load_case(case_id)
        if case is None:
            return {"error": f"case {case_id} not found"}
        features = case.get("features") or {}
        if scorer is not None and isinstance(features, dict) and features:
            _, reasons = scorer.score(features)
        else:
            reasons = []
        payload = build_input(case, reasons, getattr(scorer, "meta", {}) or {})
        if get_settings().llm_mode == "mock":
            explanation = _mock_explanation(payload)
        else:
            explanation = _gemini_explanation(payload)
    except Exception as exc:  # noqa: BLE001 - store the error, keep the case
        log.exception("explanation failed for case %s", case_id)
        explanation = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        _store(case_id, explanation)
    except Exception:  # noqa: BLE001
        log.exception("could not store explanation for case %s", case_id)
    return explanation
