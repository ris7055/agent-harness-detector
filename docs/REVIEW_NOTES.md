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
