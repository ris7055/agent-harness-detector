"""LLM-driven agent (SPEC section 9.2: llm_headless, llm_headed).

A minimal observe -> act loop. Each step builds a compact text observation of
the page (URL, title, trimmed visible text, and the interactive elements with a
stable index), asks the model for ONE action as JSON, and executes it with
Playwright. ``LLM_MODE=mock`` uses a deterministic offline policy so the loop is
testable without a key; it is also the fallback if a model call fails.

This is an ordinary automated browser driven by a model. It does NOT spoof
fingerprints or synthesise human-like input -- detecting that evasion is out of
scope (see redteam/README.md).
"""

from __future__ import annotations

import json
import os
from typing import Any

from .common import click_submit, otp_from_text, read_outcome

MAX_STEPS = 25
TEXT_LIMIT = 2000

ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string",
                   "enum": ["click", "type", "select", "navigate", "wait", "done", "fail"]},
        "index": {"type": "integer"},
        "text": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["action"],
}

SYSTEM = (
    "You are a QA automation agent testing a demo banking web app. Complete the "
    "task by choosing ONE action at a time. Respond with JSON only matching the "
    "schema. Use the element 'index' from the observation. 'type' needs 'text'. "
    "'select' needs 'text' (the option to choose). 'navigate' needs 'text' (a path "
    "like /transfer). Call 'done' when the task is finished."
)


def _interactive(page) -> list[dict[str, Any]]:
    """Visible inputs, selects, buttons and links with a stable index."""
    handles = page.query_selector_all(
        "input:not([type=hidden]), select, textarea, button, a[href]")
    out = []
    for i, h in enumerate(handles):
        try:
            if not h.is_visible():
                continue
        except Exception:
            continue
        tag = (h.evaluate("e => e.tagName") or "").lower()
        out.append({
            "index": len(out),
            "tag": tag,
            "type": h.get_attribute("type") or "",
            "id": h.get_attribute("id") or "",
            "name": h.get_attribute("name") or "",
            "label": (h.inner_text() or h.get_attribute("placeholder")
                      or h.get_attribute("aria-label") or "")[:60].strip(),
            "options": ([o.get_attribute("value") for o in h.query_selector_all("option")]
                        if tag == "select" else None),
            # Live DOM value (reflects typed text AND the selected <option>);
            # the 'value' attribute is absent on <select>, so evaluate it.
            "value_len": (len(h.evaluate("e => e.value || ''"))
                          if tag in ("input", "select", "textarea") else 0),
            "_handle": h,
        })
    return out


def build_observation(page, task: dict[str, Any]) -> dict[str, Any]:
    els = _interactive(page)
    public = [{k: v for k, v in e.items() if k != "_handle"} for e in els]
    return {
        "url": page.url,
        "title": page.title(),
        "text": page.inner_text("body")[:TEXT_LIMIT],
        "elements": public,
        "_els": els,
        "task": task["text"],
    }


# --------------------------------------------------------------- policies


def _find(els: list[dict], **crit) -> dict | None:
    for e in els:
        if all(str(e.get(k, "")).lower() == str(v).lower() for k, v in crit.items()):
            return e
    return None


def mock_action(obs: dict[str, Any], task: dict[str, Any], history: list) -> dict[str, Any]:
    """Deterministic offline policy: fills known fields by id, then submits."""
    p = task["params"]
    els = obs["_els"]
    url = obs["url"]
    body = obs["text"]

    # Field id -> value to enter. Includes the two <select> fields.
    field_values = {
        "username": p.get("username"), "password": p.get("password"),
        "to_name": p.get("to_name"), "to_bank": p.get("to_bank"),
        "to_account": p.get("to_account"), "amount": p.get("amount"),
        "reference": p.get("reference"), "tenure_months": p.get("tenure_months"),
        "monthly_income": p.get("monthly_income"), "employer": p.get("employer"),
    }

    # OTP page: enter the shown demo code.
    if "/otp" in url or otp_from_text(body):
        code = otp_from_text(body)
        otp_el = _find(els, id="otp")
        if code and otp_el and otp_el["value_len"] == 0:
            return {"action": "type", "index": otp_el["index"], "text": code}
        btn = _find(els, tag="button")
        if btn:
            return {"action": "click", "index": btn["index"]}

    # Fill the first still-empty known field on this page.
    for el in els:
        fid = el["id"]
        if fid in field_values and field_values[fid] is not None and el["value_len"] == 0:
            verb = "select" if el["tag"] == "select" else "type"
            return {"action": verb, "index": el["index"], "text": str(field_values[fid])}

    # Navigation by task kind once logged in.
    if url.endswith("/dashboard"):
        if task["kind"] in ("transfer_known", "transfer_new_payee"):
            return {"action": "navigate", "text": "/transfer"}
        if task["kind"] == "loan_apply":
            return {"action": "navigate", "text": "/loan"}
        return {"action": "done", "reason": "browse_only complete"}

    # Submit buttons (login, review-confirm, loan, transfer).
    btn = _find(els, tag="button", type="submit") or _find(els, tag="button")
    if btn:
        return {"action": "click", "index": btn["index"]}

    if read_outcome(body, saw_otp=True):
        return {"action": "done", "reason": "reached a result page"}
    return {"action": "wait"}


def gemini_action(obs: dict[str, Any], task: dict[str, Any], history: list,
                  model: str) -> dict[str, Any]:
    """Ask Gemini for one action. Falls back to the mock policy on any error."""
    try:
        from google import genai
        from google.genai import types

        mode = os.environ.get("LLM_MODE", "mock")
        if mode == "vertex":
            client = genai.Client(vertexai=True, project=os.environ["GCP_PROJECT"],
                                  location=os.environ.get("GCP_REGION", "us-central1"))
        else:
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        prompt = (f"{SYSTEM}\n\nTASK: {task['text']}\n\n"
                  f"OBSERVATION:\n{json.dumps({k: obs[k] for k in ('url','title','text','elements')})}\n\n"
                  f"RECENT ACTIONS: {json.dumps(history[-5:])}")
        resp = client.models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ACTION_SCHEMA),
        )
        return json.loads(resp.text)
    except Exception:
        return mock_action(obs, task, history)


def execute(page, obs: dict[str, Any], action: dict[str, Any], base: str) -> None:
    kind = action.get("action")
    els = obs["_els"]
    idx = action.get("index")
    el = els[idx] if isinstance(idx, int) and 0 <= idx < len(els) else None
    if kind == "click" and el:
        if el["tag"] == "button" and (el["type"] == "submit" or not el["type"]):
            click_submit(page, el["_handle"])   # submit may navigate after a flush
        else:
            el["_handle"].click()
            page.wait_for_load_state("networkidle")
    elif kind == "type" and el:
        el["_handle"].fill(str(action.get("text", "")))
    elif kind == "select" and el:
        page.select_option(f"#{el['id']}" if el["id"] else el["_handle"],
                           str(action.get("text", "")))
    elif kind == "navigate":
        page.goto(base + str(action.get("text", "/dashboard")))
        page.wait_for_load_state("networkidle")


def run_llm_agent(page, base: str, task: dict[str, Any], model: str) -> dict[str, Any]:
    """Observe->act until done/fail or MAX_STEPS. Returns {outcome, steps, saw_otp}."""
    use_mock = os.environ.get("LLM_MODE", "mock") == "mock"
    history: list = []
    saw_otp = False
    steps = 0
    for steps in range(1, MAX_STEPS + 1):
        obs = build_observation(page, task)
        if "/otp" in obs["url"] or otp_from_text(obs["text"]):
            saw_otp = True
        outcome = read_outcome(obs["text"], saw_otp)
        if outcome is not None:
            return {"outcome": outcome, "steps": steps, "saw_otp": saw_otp}
        action = (mock_action if use_mock else
                  lambda o, t, h: gemini_action(o, t, h, model))(obs, task, history)
        history.append({k: action.get(k) for k in ("action", "index", "reason")})
        if action.get("action") in ("done", "fail"):
            break
        try:
            execute(page, obs, action, base)
        except Exception as exc:  # noqa: BLE001
            history.append({"error": str(exc)[:120]})
    body = page.inner_text("body")
    outcome = read_outcome(body, saw_otp)
    if outcome is None:
        outcome = "allow" if task["kind"] == "browse_only" else "incomplete"
    return {"outcome": outcome, "steps": steps, "saw_otp": saw_otp}
