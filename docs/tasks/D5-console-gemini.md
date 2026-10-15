# D5 — Analyst console and Gemini explanations

**Branch:** `feat/d5-console` · **Depends on:** D2 merged · **Target:** day 3 (Oct 17)
**Spec sections:** §7.4, §7.5

## Build
1. `services/scorer/explain.py` per §7.4: `google-genai` client (`LLM_MODE=vertex` → `genai.Client(vertexai=True, project, location)`; `apikey` → API key; `mock` → deterministic JSON built from the top reasons). Structured JSON output with a response schema. Called in a background task after a case is created and from `POST /v1/cases/{id}/explain`. Errors stored as `{"error": ...}`; never raise into the decision path. Human reference ranges come from `model_meta.json` when a model is loaded; otherwise use static defaults defined in `explain.py`.
2. Console service (FastAPI + Jinja + Tailwind CDN + Chart.js CDN), password login (`CONSOLE_PASSWORD`). Reads Cloud SQL directly via `harnessguard_core.db`.
   - `/` live sessions table, auto-refresh 3 s via `/api/sessions`: short id, user, started, pages, events, score bar coloured by band, last decision, label tag (grey, only if present).
   - `/cases` (open first) and `/cases/{id}`: decision banner; score gauge; Gemini summary, evidence bullets, recommended action, next steps; "Regenerate explanation" button; top-reasons horizontal bar chart; fingerprint table; **mouse-path replay** on `<canvas>` (per page, scaled to the recorded `inner_w × inner_h`, path drawn progressively on Play, clicks as dots, keystroke ticks on a timeline under it); event timeline; buttons Confirm fraud / False positive (update `cases.status`, `reviewed_at`).
   - `/log` **Detection log** per SPEC §7.5: every decision in time order with score, decision, model version, latency and top reasons; filters (decision, band, time range, user); CSV export; expandable event timeline per row.
   - `/benchmark`: loads `BENCHMARK_URI` (local path or `gs://`); if missing, shows "No benchmark yet — run ml/benchmark.py". Renders: summary metric cards, per-model table, per-variant detection bar chart, ROC curves, early-detection line chart, latency p50/p95. Expected JSON format is defined in `docs/tasks/D6-ml-benchmark.md` — implement against that.
   - Visual quality matters (this is the demo screen): dark-on-light, clear hierarchy, red/amber/green bands with text labels too (not colour alone).
3. Optional if time: a "Live demo" toggle on `/` that highlights new cases with a subtle animation and a sound-free toast.

## Acceptance criteria
- [ ] With the local stack and `LLM_MODE=mock`, a bot-like session that gets `block` appears in `/cases` within ~3 s with an explanation.
- [ ] With `LLM_MODE=apikey` and a real key, the explanation is valid JSON matching the schema and cites real feature values.
- [ ] Mouse-path replay works for both a human session and a scripted session (the scripted one visibly shows straight jumps / no path).
- [ ] `/log` lists every decision made during a local test run, filters work, and CSV export downloads the same rows.
- [ ] `/benchmark` renders a sample `tests/fixtures/benchmark.sample.json`.
- [ ] `pytest` passes (explainer mock mode, console auth, API endpoints).
