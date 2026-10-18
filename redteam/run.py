"""HarnessGuard red-team runner (SPEC section 9.2, task D4).

Generates labelled AUTOMATED sessions against your own Bank Seroja demo portal
and logs the outcome of each run. Variants (all non-evasive):
  script_fill   - scripted Playwright, page.fill (headless)
  script_type   - scripted Playwright, page.type with a small delay (headless)
  llm_headless  - Gemini observe->act loop, headless Chromium
  llm_headed    - same, headed Chromium

Examples (from the repo root; `python -m redteam.run` also works):
  python redteam/run.py --base-url http://localhost:8080 --variant script_fill --n 5
  python redteam/run.py --base-url http://localhost:8080 --variant llm_headless --n 10 --task transfer_new_payee
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
import traceback

if __package__ in (None, ""):
    # Allow `python redteam/run.py ...` as well as `python -m redteam.run ...`.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "redteam"

from .agent import run_llm_agent
from .common import (VARIANTS, check_target, log_run, make_task, read_outcome,
                     start_url)
from .scripted import run_scripted


def _run_once(pw, base: str, variant: str, task: dict, model: str, headed: bool) -> dict:
    # HG_CHROMIUM_PATH lets you point at a specific Chromium build if Playwright's
    # bundled one is not where it expects (otherwise leave it unset).
    launch_kw = {"headless": not headed}
    exe = os.environ.get("HG_CHROMIUM_PATH")
    if exe:
        launch_kw["executable_path"] = exe
    browser = pw.chromium.launch(**launch_kw)
    context = browser.new_context()
    page = context.new_page()
    t0 = time.monotonic()
    try:
        page.goto(start_url(base, variant, task["task_id"]))  # label=agent, new session
        page.wait_for_load_state("networkidle")
        if variant in ("script_fill", "script_type"):
            res = run_scripted(page, base, task, mode="fill" if variant == "script_fill" else "type")
            res.setdefault("steps", None)
        else:
            res = run_llm_agent(page, base, task, model)
        res["error"] = None
    except Exception as exc:  # noqa: BLE001
        res = {"outcome": "error", "steps": None, "saw_otp": False,
               "error": f"{type(exc).__name__}: {exc}"}
        traceback.print_exc()
    finally:
        res["duration_s"] = round(time.monotonic() - t0, 2)
        context.close()
        browser.close()
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HarnessGuard red team (non-evasive automation).")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--variant", required=True, choices=VARIANTS)
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--task", default="random",
                    help="random | transfer_known | transfer_new_payee | loan_apply | browse_only")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--model", default=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
    ap.add_argument("--i-own-this-target", action="store_true",
                    help="confirm you own a non-localhost target (e.g. your Cloud Run portal)")
    args = ap.parse_args(argv)

    base = check_target(args.base_url, args.i_own_this_target)
    rng = random.Random(args.seed)
    headed = args.variant == "llm_headed"

    from playwright.sync_api import sync_playwright

    summary: dict[str, int] = {}
    with sync_playwright() as pw:
        for i in range(args.n):
            task = make_task(args.task, rng)
            res = _run_once(pw, base, args.variant, task, args.model, headed)
            record = {
                "variant": args.variant, "task_id": task["task_id"],
                "task_type": task["kind"], "outcome": res["outcome"],
                "steps": res.get("steps"), "duration_s": res["duration_s"],
                "error": res.get("error"),
            }
            log_run(record)
            summary[res["outcome"]] = summary.get(res["outcome"], 0) + 1
            print(f"[{i+1}/{args.n}] {args.variant} {task['kind']} -> {res['outcome']} "
                  f"({res['duration_s']}s)")

    print("\nsummary:", ", ".join(f"{k}={v}" for k, v in sorted(summary.items())))
    # A detector working on the rules baseline should flag most of these.
    flagged = summary.get("block", 0) + summary.get("step_up", 0)
    total = sum(summary.values())
    if total:
        print(f"flagged (step_up+block): {flagged}/{total} = {flagged/total:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
