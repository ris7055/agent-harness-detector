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
