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
3. Variants (SPEC §9.2) — **non-evasive only**:
   - `script_fill`, `script_type` — deterministic Playwright scripts per task type.
   - `llm_headless`, `llm_headed` — `redteam/agent.py`: a minimal agent loop. Each step: build a compact observation (URL, page title, visible text trimmed to ~2k chars, list of interactive elements with a stable index, role, label/name, current value length), send it + the task + last 5 actions to Gemini with a JSON response schema `{"action": "click|type|select|navigate|wait|done|fail", "index": int|null, "text": str|null, "reason": str}`; execute with Playwright; max 25 steps. `LLM_MODE=mock` uses a deterministic offline policy so tests (and a key-less dry run) work.
   - **Not built:** a stealth / anti-detection variant. See the out-of-scope note in SPEC §9.2 — the project does not ship evasion tooling. Stealth is a Limitations / Future Work item, not code.

## Acceptance criteria
- [x] Against the local stack, each runnable variant (`script_fill`, `script_type`, `llm_headless`) completes runs end-to-end and labels appear in `session_labels` with the right variant. (`llm_headed` is the same loop with a visible browser; it needs a display, so it runs on the laptop, not in headless CI.)
- [x] Host allow-list guard works (`check_target`; `--i-own-this-target` for a non-localhost target you own).
- [x] `pytest` passes (mock-mode agent-policy and observation tests; target-guard tests).
