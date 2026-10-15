# D4 — Red-team agents (Playwright + Gemini)

**Branch:** `feat/d4-redteam` · **Depends on:** D2 merged (D3 not required) · **Target:** day 3 morning (Oct 17)
**Spec sections:** §9.2, §4 (Gemini modes)

> These agents only ever target **our own Bank Seroja demo portal** (localhost or our Cloud Run URL). Refuse any other `--base-url` host unless `--i-own-this-target` is passed.

## Build
1. `redteam/requirements.txt` (playwright, google-genai, pydantic, numpy) and `redteam/README.md` (setup: `pip install -r redteam/requirements.txt`, `playwright install chromium`, env `GEMINI_API_KEY`, `LLM_MODE`).
2. `redteam/run.py --base-url URL --variant V --n N [--task random|<task_type>] [--concurrency 2] [--headed]`:
   - For each run: generate a task via `harnessguard_core.tasks` (same generator humans get), open `${base}/collect/agent?hg_label=agent&hg_variant=V&hg_task=<id>`, then execute the task.
   - Log one JSON line per run to `data/redteam_runs.jsonl`: `ts, variant, task_id, task_type, outcome (allow|step_up|block|error|incomplete), steps, duration_s, error`.
   - Outcome detection: read the final page (success / OTP / held-for-review) text markers. On OTP page the agent may try the code shown in the simulated SMS banner (realistic) — record it.
3. Variants (SPEC §9.2):
   - `script_fill`, `script_type` — deterministic Playwright scripts per task type.
   - `llm_headless`, `llm_headed` — `redteam/agent.py`: a minimal agent loop. Each step: build a compact observation (URL, page title, visible text trimmed to ~2k chars, list of interactive elements with a stable index, role, label/name, current value length), send it + the task + last 5 actions to Gemini with a JSON response schema `{"action": "click|type|select|navigate|wait|done|fail", "index": int|null, "text": str|null, "reason": str}`; execute with Playwright `locator.click()` / `fill()` / `select_option()`; max 25 steps. `LLM_MODE=mock` uses a scripted policy so tests run offline.
   - `llm_stealth` — same loop, headed, plus: `add_init_script` hiding `navigator.webdriver`, faking `plugins`/`languages`, a realistic desktop UA and viewport; humanised think-time (uniform 0.4–2.5 s), per-key delays from a log-normal (median ~120 ms) using `keyboard.type` char-by-char, mouse moved along a cubic Bézier with jitter to a **random point inside** the target box before clicking.
   - `browser_use` — optional; only if `pip install browser-use` works with Gemini on Python 3.11. Skip without failing if unavailable.
4. `redteam/collect_batch.py` convenience: e.g. `--plan "script_fill:30,script_type:30,llm_headless:40,llm_headed:30,llm_stealth:40"`.

## Acceptance criteria
- [ ] Against the local stack, each variant completes at least 3 runs end-to-end (with `LLM_MODE=apikey` for LLM variants), and labels appear in `session_labels` with the right variant.
- [ ] Sessions from `llm_stealth` show `fp_webdriver = 0` and non-zero mouse movement before clicks (verify via a small `redteam/inspect_session.py <session_id>` that prints computed features).
- [ ] Host allow-list guard works.
- [ ] `pytest` passes (mock-mode test for the agent loop and observation builder).
