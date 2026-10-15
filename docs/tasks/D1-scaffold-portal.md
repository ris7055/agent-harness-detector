# D1 — Scaffold, core package, database, bank portal

**Branch:** `feat/d1-portal` · **Depends on:** nothing · **Target:** day 1 (Oct 15–16)
**Spec sections:** §3, §4, §7.1 (pages only), §8.1, §8.2, §11, §12

## Build
1. Repo scaffold exactly as SPEC §3: `core/`, `services/portal/`, `services/scorer/` (stub with `/healthz` only), `services/console/` (stub with `/healthz` only), `tests/`, `docker-compose.yml`, `.env.example` (all vars from §11).
2. `core/harnessguard_core`: `config.py` (pydantic-settings), `db.py` (SQLAlchemy engine from `DATABASE_URL`, `init_db()` that applies `schema.sql`), `schema.sql` (all tables + indexes from §8.1), `seed.py` (idempotent seed from §8.2), `tasks.py` (task-card generator for §9.1: `transfer_known`, `transfer_new_payee`, `loan_apply`, `browse_only`, with randomised parameters and a deterministic `task_id`), `events.py` (pydantic `Event`, `EventBatch` from §5.3).
3. Portal (FastAPI + Jinja + Tailwind CDN), fictional brand **Bank Seroja** with a visible "DEMO — fictional bank" ribbon. Pages: `/login`, `/dashboard`, `/transfer` → `/transfer/review` → `POST /transfer/confirm`, `/otp`, `/loan`, `/collect`, `/collect/agent` (gated by `ALLOW_DATA_COLLECTION`), `/healthz`.
   - Sessions: `hg_sid` cookie (UUID4) + `sessions` row on first request; `<meta name="hg-session">` in the base template; salted IP hash.
   - For now `POST /transfer/confirm` and loan submit call a function `decide()` that **returns `allow`** (D2 wires the real scorer). Implement the full allow / step_up (OTP page with simulated SMS banner, 3 attempts) / block (case reference page) UI paths anyway, switchable via a temporary env `FORCE_DECISION=allow|step_up|block` so all three screens can be demoed and tested.
   - Transfers actually change balances on `allow` / successful OTP.
   - Every decision form includes hidden `hg_last_seq` (value filled by JS later; default `0`).
   - Clean, credible banking look: neutral palette, clear typography, works on a laptop screen; no stock photos, no real bank logos.
4. `docker-compose.yml`: `db` (postgres:15, healthcheck), `portal:8080`, `scorer:8081`, `console:8082`; services wait for db health, run `init_db()` + seed on startup.
5. Dockerfiles per service with repo root as build context, installing `./core`.
6. `.gitignore` is already present — keep it.

## Acceptance criteria
- [x] `docker compose up --build` → portal on http://localhost:8080; login as `daniel` / `Seroja@2026` works; dashboard shows balance and 5 transactions.
- [x] Transfer flow works end-to-end for all three `FORCE_DECISION` values; balances update only on success.
- [x] `/collect` assigns a task card, writes a `session_labels` row (label `human`), and continues into `/login` in the same session.
- [x] `/collect/agent?hg_label=agent&hg_variant=script_fill&hg_task=<id>` writes the label and redirects to `/login`; returns 404 when `ALLOW_DATA_COLLECTION=false`.
- [x] `pytest` passes: schema init + seed idempotent (run twice), login, transfer happy path, collect labelling.
- [x] README quickstart updated.
