# D3 — Google Cloud deployment scripts

**Branch:** `feat/d3-deploy` · **Depends on:** D2 merged · **Target:** day 2 (Oct 16) — deploy early so human data collection can happen on the live URL.
**Spec sections:** §2 (services table), §8.3, §11, §13

> The developer runs these scripts in **Google Cloud Shell**. You (the coding agent) cannot run them — write them carefully, make them idempotent, and dry-run-check them with `bash -n` and `shellcheck` if available.

## Build
1. `deploy/config.env.example` with every variable (`PROJECT_ID`, `REGION=asia-southeast1`, `AR_REPO=harnessguard`, `SQL_INSTANCE=harnessguard-db`, `DB_NAME=harnessguard`, `DB_USER=hg`, `BUCKET` (default `${PROJECT_ID}-harnessguard`), `BQ_DATASET=harness_detector`, `PUBSUB_TOPIC=session-events`, `GEMINI_MODEL`, thresholds). Real `deploy/config.env` is gitignored.
2. `deploy/setup.sh` — everything in SPEC §13 "setup.sh", idempotent (check-then-create; re-running prints "exists" instead of failing). Generates random secrets into Secret Manager only if missing (`db-password`, `session-secret`, `console-password`, `internal-token`, `pubsub-push-token`, `ip-hash-salt`). Creates BigQuery tables with explicit schemas: `raw_event_batches` (Pub/Sub BQ-subscription schema), `session_features` and `training_features` (columns generated from `FEATURE_NAMES` by a small Python helper `deploy/bq_schema.py`), `benchmark_results`, and the `v_events` view. Prints the console password at the end.
3. `deploy/cloudbuild.yaml` — builds and pushes `portal`, `scorer`, `console` images to Artifact Registry (repo root as context, `-f services/<svc>/Dockerfile`), tagged with `$SHORT_SHA` fallback to a timestamp substitution.
4. `deploy/deploy.sh` — builds via Cloud Build, deploys the three Cloud Run services with the runtime service account, Cloud SQL attachment, secrets as env vars, `ENV=cloud`, `EVENT_TRANSPORT=pubsub`, `ANALYTICS_SINK=bigquery`, `LLM_MODE=vertex`, `MODEL_URI=gs://$BUCKET/models/latest.json` (scorer tolerates a missing file → rules), `BENCHMARK_URI=gs://$BUCKET/benchmark/benchmark.json`; sets `SCORER_URL` on portal after the scorer deploys; creates or updates the push subscription `session-events-scorer` → `https://<scorer>/pubsub/events?token=...` and the BigQuery subscription `session-events-bq` → `raw_event_batches`; prints the three URLs.
5. `deploy/teardown.sh` — default: stop Cloud SQL (`--activation-policy=NEVER`); `--start` to resume; `--delete` to delete all created resources after a confirmation prompt.
6. Make services cloud-ready where needed: Cloud SQL unix-socket `DATABASE_URL` built from `DB_USER`/`DB_PASS`/`DB_NAME`/`INSTANCE_CONNECTION_NAME` when `ENV=cloud`; `PORT` env respected; `GCSModelLoader` for `gs://` URIs.
7. `docs/DEPLOY.md`: step-by-step for a beginner in Cloud Shell (clone, `cp deploy/config.env.example deploy/config.env`, edit with `vim`, `bash deploy/setup.sh`, `bash deploy/deploy.sh`, how to see logs, how to stop Cloud SQL to save credit, rough cost notes).

## Acceptance criteria
- [x] `bash -n` passes on all scripts; scripts use `set -euo pipefail` and read only from `deploy/config.env`.
- [x] Re-running `setup.sh` is safe (no failures on existing resources).
- [x] No hardcoded project IDs, URLs, or secrets anywhere.
- [x] `.gitattributes` keeps `*.sh` as LF.
- [x] `docs/DEPLOY.md` written; README links to it.
