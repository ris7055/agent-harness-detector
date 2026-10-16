# Review notes

Build agents add a section per branch when they finish (what was built, how to run it, deviations, known gaps).
The reviewer adds a "Review: <branch>" section with items marked **MUST** (blocks merge) or **SHOULD** (nice to fix).

---

## feat/d1-portal

**Built:** full repo scaffold per SPEC §3 — `core/harnessguard_core` (`config.py`,
`db.py`, `schema.sql` with all §8.1 tables + indexes, `models.py` query helpers,
`seed.py`, `tasks.py`, `events.py`); Bank Seroja portal (FastAPI + Jinja +
Tailwind CDN, "DEMO — fictional bank" ribbon) with `/login`, `/dashboard`,
`/transfer` → review → `/transfer/confirm`, `/otp`, `/loan`, `/collect`,
`/collect/agent`, `/api/events`, `/healthz`; scorer and console stubs
(`/healthz` only); `docker-compose.yml` (db + 3 services, healthcheck gating,
init_db + seed on startup); `.env.example` with all §11 vars; pytest suite.

**How to run:** `docker compose up --build` → portal on :8080
(`daniel`/`Seroja@2026`). `FORCE_DECISION=allow|step_up|block` exercises all
three decision paths while `decide()` is a stub. Tests: `pip install -r
requirements-dev.txt && pytest` (18 tests; spins a throwaway postgres:15 via
testcontainers, or set `HG_TEST_DATABASE_URL` to a disposable DB).

**Verified:** all acceptance criteria checked live against the compose stack —
login, dashboard (balance + 5 transactions), transfer allow (balance debited),
step_up (OTP banner code completes the transfer; 3 wrong → `failed_otp`, no
debit), block (`CASE-0001` reference, `cases` row, no debit), `/collect` task
card + `session_labels` row, `/collect/agent` label + 303 → `/login`, and 404s
when `ALLOW_DATA_COLLECTION=false`.

**Deviations from spec:**
- `POST /api/events` validates the `EventBatch` and attempts the `http`
  forward to `${SCORER_URL}/v1/events`, but drops the batch on failure since
  the scorer endpoint lands in D2. Returns 204 either way.
- Loan OTP codes are kept in a process-local dict (`_LOAN_OTPS`) because
  `loan_applications` has no `otp_code` column and §8.1 schema must not change.
  Transfers use their real `otp_code`/`otp_attempts` columns.
- Seed data is deterministic (`random.Random(20261015)`) so tests and demos are
  repeatable.
- Added an extra `idx_transfers_account` index for dashboard queries.

**Known gaps (intended for later tasks):**
- `collector.js` is not included yet (D2) — `hg_last_seq` stays `0`.
- `decide()` ignores `SCORER_URL` unless `FORCE_DECISION` is set (returns
  `allow`); D2 wires the real call with the 2 s fail-open to `step_up`.
- Scorer `/v1/*` and the console dashboard do not exist yet.
- `decisions` rows written by the portal stub carry `score=NULL`,
  `model_version='stub'`.

## Review: feat/d1-portal

Reviewed by Claude against SPEC/AGENTS. Overall solid: structure matches §3, all queries are parameterised, passwords hashed (PBKDF2), no secrets committed, and the 18 tests pass (re-run against a separate PostgreSQL). Fix the items below on this branch, then it can merge.

**MUST 1: Transfer amount is trusted from a hidden form field.** `POST /transfer/confirm` takes `amount_cents` from the client and never checks it is positive. Reproduced: posting `amount_cents=-100000` as `ravi` *increased* the balance by RM 1,000. Fix: in `/transfer/confirm`, reject `amount_cents <= 0`, reject `amount_cents > balance` on every path (allow, step_up, block), and return 400 if the user has no account. Re-check `amount_cents > 0` in the OTP completion path too. Add a test for a negative and a zero amount.

**MUST 2: Each data-collection task must be its own session.** `/collect` (POST) writes the label onto the browser's existing `hg_sid`, and `record_label` uses `ON CONFLICT DO NOTHING`. If a volunteer does two tasks in the same browser, both tasks land in one session and only the first task's label survives, which corrupts the training data. Fix: when a task starts (`POST /collect` and `GET /collect/agent`), issue a **new** `hg_sid` (new UUID, new `sessions` row, set the cookie on the response), clear `hg_auth` (log out), then write the label for the new session id. Add a test: two consecutive `/collect` starts in one client produce two different session ids, each with its own label.

**SHOULD 1: Open redirect on login.** `next="//evil.example"` redirects off-site (reproduced). Only accept `next` values that start with `/` and do not start with `//` or `/\`; otherwise use `/dashboard`.

**SHOULD 2: Loan OTPs live in process memory.** On Cloud Run with more than one instance (or after a restart) the OTP is lost. The spec now adds `otp_code text` and `otp_attempts int default 0` to `loan_applications` (SPEC §8.1). Add them in `schema.sql` with `ALTER TABLE loan_applications ADD COLUMN IF NOT EXISTS ...` so existing databases upgrade, and remove `_LOAN_OTPS`.

**SHOULD 3: `/collect/agent` accepts any `hg_label`.** Accept only `agent` or `human`; otherwise 400.

**SHOULD 4: Secure cookies in the cloud.** Set `secure=True` on `hg_sid` and `hg_auth` when `ENV=cloud` (Cloud Run is HTTPS).

**SHOULD 5: `new_payee` is hard-coded `True`.** Compute it: `True` unless `to_account` matches one of the user's saved payees. The scorer uses this in D2.

**Note for D2 (no action now):** `SessionMiddleware` does a synchronous DB upsert on every request, including `/api/events`, which will fire every 2 s per browser. In D2, skip `ensure_session` for `/api/events`, since the scorer updates `sessions.last_seen` itself.

### Fixes (applied by Claude on this branch)
- **MUST 1:** fixed. `/transfer/confirm` validates the account, `amount_cents > 0`, `amount_cents <= balance` and recipient fields **before** calling `decide()`, so every path (allow/step_up/block) is covered. The OTP completion path re-checks the amount. Tests: `test_transfer_rejects_non_positive_amounts`, `test_transfer_rejects_amount_over_balance_on_every_path`.
- **MUST 2:** fixed. `POST /collect` and `GET /collect/agent` call `_start_fresh_session()`: a new `hg_sid` and `sessions` row, logged out (`hg_auth` cleared). The middleware writes the rotated cookie. Tests: `test_each_collect_task_gets_its_own_session`, `test_collect_agent_rotates_session_and_validates_label`.
- **SHOULD 1:** fixed. `_safe_next()` rejects `//host`, `/\host` and absolute URLs. Test: `test_login_blocks_open_redirect`.
- **SHOULD 2:** fixed. `loan_applications.otp_code` / `otp_attempts` are added with idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in `schema.sql`, and `_LOAN_OTPS` is removed. Test: `test_loan_otp_persisted_in_db`.
- **SHOULD 3:** fixed. `/collect/agent` returns 400 unless `hg_label` is `agent` or `human`.
- **SHOULD 4:** fixed. `_cookie_kwargs()` sets `Secure` when `ENV=cloud`. Test: `test_cookies_secure_in_cloud`.
- **SHOULD 5:** fixed. `new_payee` is computed against the user's saved payees (spaces ignored). Test: `test_new_payee_flag`.

Result: 26 tests pass. Ready to merge.

---

## feat/d2-scorer

**Built:** live behavioural pipeline per SPEC §5–§7.

- `services/portal/static/collector.js` (~270 lines, no deps): all §5.2 event
  types (fingerprint, page, mousemove @50 ms throttle, click, keydown/keyup with
  `key_class` only, input with `value_length` only, paste, focus/blur, scroll,
  visibility, submit); `seq` in `sessionStorage`; 2 s batching; `sendBeacon` on
  pagehide/hidden; awaited flush (≤800 ms) before every form submit, stamping
  `hg_last_seq`. Wired via `base.html` meta tags + form ids on all forms.
- `core/harnessguard_core/features.py`: `FEATURE_NAMES` (44) +
  `compute_features(events, until_seq=None)` — the single implementation for
  every §6 feature; missing values → `-1`; pure and deterministic.
- `core/harnessguard_core/rules.py`: weighted-signal baseline →
  `(score, top_reasons)` + `band_for_score`.
- `core/harnessguard_core/analytics.py`: `AnalyticsSink` with `JsonlSink`
  (`data/analytics/session_features.jsonl`) and `BigQuerySink`
  (`insert_rows_json`); selected by `ANALYTICS_SINK`; never raises into
  handlers.
- Scorer service (`services/scorer/app/`): `/v1/events` (idempotent upsert by
  `(session_id, seq)`, `sessions.last_seen/event_count` + debounced rescore →
  `risk_score`/`risk_band`), `/pubsub/events` (`?token=` + push-envelope
  decode), `/v1/decide` (≤1.5 s seq wait @100 ms, thresholds +
  ≥RM 5000 & score ≥ 0.35 → min `step_up` context rule, `decisions` + `cases`
  rows, analytics snapshot, `top_reasons`), `/v1/sessions/{id}/score`,
  `/v1/cases/{id}/explain` → 501, `/healthz`. `X-HG-Internal` on `/v1/*`.
  Model loader (`model.py`): empty `MODEL_URI` → rules; local dir / local
  `latest.json` / `gs://` pointer; feature-name mismatch → loud log + rules.
- Portal: real `decide()` → `POST /v1/decide` (2 s timeout, `X-HG-Internal`,
  fail-open `step_up`, `FORCE_DECISION` still wins); `/api/events` forwards per
  `EVENT_TRANSPORT` (http with auth header, or lazy Pub/Sub publisher with
  `session_id` attribute); middleware skips `ensure_session` on `/api/events`
  per the D1 note.

**How to run:** `docker compose up --build` → portal :8080, scorer :8081
(`curl -H "X-HG-Internal: $INTERNAL_TOKEN" localhost:8081/v1/sessions/<id>/score`).
Tests: `pytest` — 60 passed, 1 skipped (see deviations).

**Verified live against the compose stack:**
- Login → batched `POST /api/events` → 32 `session_events` rows in <2 s;
  `sessions.risk_score=0.259`/`green` updated; score endpoint returns it.
- Human-like telemetry + RM 25.50 transfer → `allow` → success page
  (`decisions.latency_ms=1`, `model_version=rules`).
- Bot telemetry (webdriver=true, no-premove centre clicks, programmatic inputs)
  + RM 500 transfer → `step_up` (score 0.817, amber) → OTP page; `cases` row
  created. `top_reasons`: `fp_webdriver`, `input_programmatic_ratio`,
  `click_no_premove_ratio`.
- Privacy: scanned all stored `session_events.data` payloads — no `key`,
  `value`, `password`, `text` or `char` keys; `data/analytics/` is gitignored.
- `/v1/*` returns 401 without the internal header; `/pubsub/events` 401/403
  without a valid `?token=`.

**Deviations from spec:**
- `xgboost` pinned `>=2.0,<2.1`: xgboost ≥2.1 added a hard ~350 MB
  `nvidia-nccl-cu12` wheel dependency on Linux even for CPU-only inference.
  D6 training should save models with the 2.0.x API/format.
- Scorer image installs `libgomp1` (xgboost needs OpenMP; `python:3.11-slim`
  doesn't ship it).
- Portal writes `decisions`/`cases` rows only for `FORCE_DECISION` and
  fail-open paths — when the scorer answered, it already wrote them; the
  portal writing again would duplicate rows.
- The real XGBoost round-trip test skips on this Windows host (installed
  `xgboost.dll` can't load its OpenMP runtime); it runs in the Linux image.

**Known gaps:**
- `/v1/cases/{id}/explain` is a 501 stub — D3 implements the LLM explainer.
- `BigQuerySink` and `gs://` model loading are unit-tested with fakes only;
  no GCP credentials exist locally (per spec).
- `EVENT_TRANSPORT=pubsub` is covered by mocked-publisher tests only.
- Click events carry `target_rect` so `click_center_offset_*` is computed;
  events without element bounds (e.g. document-level clicks) contribute `-1`.

## Review: feat/d2-scorer

Reviewed by Claude, including a real-browser end-to-end run (Playwright Chromium against portal and scorer). The feature engineering, rules baseline, scorer API and privacy handling are solid. Four bugs were found; all are fixed on this branch.

**MUST 1 (fixed): `collector.js` was never served.** `base.html` loads `/static/collector.js`, but the portal mounted `services/portal/app/static/` while the file lives in `services/portal/static/`. The mount was also conditional, so it failed silently: **real browsers sent zero events** and every decision was scored on an empty session (score 0, always `allow`). The D2 live check posted synthetic batches with curl, so it never exercised the browser path. Fix: mount `BASE_DIR.parent / "static"` unconditionally. Test: `test_collector_js_is_served`.

**MUST 2 (fixed): cross-session event injection.** `/api/events` accepted any `session_id` in the batch, so a client could push events into another user's session (or invent sessions). Fix: drop batches whose `session_id` differs from the `hg_sid` cookie, still answering 204 so the collector does not retry forever. Test: `test_api_events_rejects_other_sessions`.

**MUST 3 (fixed): model scoring crashed with named features.** `Scorer.score` built an unnamed `DMatrix`. A booster trained from a DataFrame or named DMatrix (what D6 will produce) raises on unnamed input, so `/v1/decide` would return 500 for every request and the portal would fail open to OTP for everyone. Fix: pass `feature_names`, and fall back to rules for that request if the model errors. The existing round-trip test never ran (it was skipped on Windows and also called the non-existent `np.random.Random`). It is now fixed to use the native xgboost API (no scikit-learn in the scorer image), and `test_unnamed_model_also_scores` was added.

**MUST 4 (fixed): collector sequence numbers.**
- `hg_seq` lived in `sessionStorage` and was not keyed by session, so a second tab restarted at seq 1 and the server's `ON CONFLICT (session_id, seq) DO NOTHING` silently discarded that tab's events. It is now `localStorage["hg_seq:<session>"]`, shared by all tabs of the session and re-read on every increment.
- On submit, `hg_last_seq` was set from *acknowledged* events only, and the flush was skipped if a periodic batch was in flight. The decision could therefore be taken without the latest keystrokes and the submit event. Now the highest pushed seq is stamped and a forced flush is sent; the scorer already waits up to 1.5 s for it. Verified in the browser run: every decision covers all events including the submit.

**Notes (no action):**
- A Playwright session with humanised mouse and typing still scores about 0.75 (step-up) because `navigator.webdriver` is true. That is correct behaviour; the human path must be validated by real people in normal browsers (the `/collect` data collection).
- `decide()` is called while the portal holds a DB session (up to 2 s). This is acceptable at prototype scale.

Result: 64 tests pass. Ready to merge.
