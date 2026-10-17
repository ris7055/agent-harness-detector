#!/usr/bin/env bash
# Shared helpers for the HarnessGuard deploy scripts. Sourced, not run.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }
skip() { printf '    (exists) %s\n' "$*"; }

load_config() {
  local cfg="$ROOT/deploy/config.env"
  [ -f "$cfg" ] || die "deploy/config.env not found. Run: cp deploy/config.env.example deploy/config.env && vim deploy/config.env"
  set -a
  # shellcheck disable=SC1090  # config.env path is user-provided at runtime
  . "$cfg"
  set +a

  : "${PROJECT_ID:?set PROJECT_ID in deploy/config.env}"
  REGION="${REGION:-asia-southeast1}"
  AR_REPO="${AR_REPO:-harnessguard}"
  SQL_INSTANCE="${SQL_INSTANCE:-harnessguard-db}"
  SQL_TIER="${SQL_TIER:-db-f1-micro}"
  DB_NAME="${DB_NAME:-harnessguard}"
  DB_USER="${DB_USER:-hg}"
  BUCKET="${BUCKET:-${PROJECT_ID}-harnessguard}"
  BQ_DATASET="${BQ_DATASET:-harness_detector}"
  PUBSUB_TOPIC="${PUBSUB_TOPIC:-session-events}"
  RUN_SA="${RUN_SA:-harnessguard-run}"
  GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.5-flash}"
  ALLOW_BELOW="${ALLOW_BELOW:-0.50}"
  BLOCK_ABOVE="${BLOCK_ABOVE:-0.85}"
  ALLOW_DATA_COLLECTION="${ALLOW_DATA_COLLECTION:-true}"

  # These are consumed by setup.sh / deploy.sh / teardown.sh (which source this).
  # shellcheck disable=SC2034
  RUN_SA_EMAIL="${RUN_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
  # shellcheck disable=SC2034
  INSTANCE_CONNECTION_NAME="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"

  command -v gcloud >/dev/null || die "gcloud not found. Run these in Google Cloud Shell."
  gcloud config set project "$PROJECT_ID" >/dev/null
}

# Read a Secret Manager value (latest version).
secret_value() { gcloud secrets versions access latest --secret="$1" --project="$PROJECT_ID"; }
