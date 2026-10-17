#!/usr/bin/env bash
# HarnessGuard one-time infrastructure setup (SPEC section 13).
# Idempotent: safe to re-run. Run from the repo root in Google Cloud Shell:
#   bash deploy/setup.sh
set -euo pipefail
# shellcheck source=deploy/lib.sh
. "$(dirname "$0")/lib.sh"
load_config

log "Enabling APIs (first run can take a minute)..."
gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  sqladmin.googleapis.com pubsub.googleapis.com bigquery.googleapis.com \
  aiplatform.googleapis.com storage.googleapis.com secretmanager.googleapis.com \
  --project "$PROJECT_ID"

# --- Artifact Registry -------------------------------------------------------
if gcloud artifacts repositories describe "$AR_REPO" --location "$REGION" >/dev/null 2>&1; then
  skip "Artifact Registry repo $AR_REPO"
else
  log "Creating Artifact Registry repo $AR_REPO..."
  gcloud artifacts repositories create "$AR_REPO" --repository-format=docker \
    --location "$REGION" --description "HarnessGuard images"
fi

# --- Secrets (generate random values only if missing) ------------------------
ensure_secret() {
  local name="$1" value="$2"
  if gcloud secrets describe "$name" >/dev/null 2>&1; then
    skip "secret $name"
  else
    log "Creating secret $name..."
    printf '%s' "$value" | gcloud secrets create "$name" --data-file=- --replication-policy=automatic
  fi
}
rand() { openssl rand -hex 24; }
ensure_secret db-password      "$(rand)"
ensure_secret session-secret   "$(rand)"
ensure_secret console-password "$(rand)"
ensure_secret internal-token   "$(rand)"
ensure_secret pubsub-push-token "$(rand)"
ensure_secret ip-hash-salt     "$(rand)"

# --- Runtime service account + roles -----------------------------------------
if gcloud iam service-accounts describe "$RUN_SA_EMAIL" >/dev/null 2>&1; then
  skip "service account $RUN_SA_EMAIL"
else
  log "Creating runtime service account $RUN_SA..."
  gcloud iam service-accounts create "$RUN_SA" --display-name "HarnessGuard Cloud Run runtime"
fi
log "Granting roles to $RUN_SA_EMAIL..."
for role in roles/cloudsql.client roles/pubsub.publisher roles/bigquery.dataEditor \
            roles/bigquery.jobUser roles/aiplatform.user roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:$RUN_SA_EMAIL" --role "$role" --condition=None >/dev/null
done

# --- Cloud Build's builder account --------------------------------------------
# New projects no longer auto-grant roles to the default Compute Engine service
# account, which Cloud Build now runs builds as. Without this, `gcloud builds
# submit` fails with "compute@developer... does not have storage.objects.get".
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
BUILD_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
log "Granting Cloud Build roles to $BUILD_SA..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:$BUILD_SA" --role roles/cloudbuild.builds.builder \
  --condition=None >/dev/null

# --- Cloud Storage bucket ----------------------------------------------------
if gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
  skip "bucket gs://$BUCKET"
else
  log "Creating bucket gs://$BUCKET..."
  gcloud storage buckets create "gs://$BUCKET" --location "$REGION" --uniform-bucket-level-access
fi
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member "serviceAccount:$RUN_SA_EMAIL" --role roles/storage.objectAdmin >/dev/null

# --- Cloud SQL (PostgreSQL 15, smallest tier, no HA) -------------------------
if gcloud sql instances describe "$SQL_INSTANCE" >/dev/null 2>&1; then
  skip "Cloud SQL instance $SQL_INSTANCE"
else
  log "Creating Cloud SQL instance $SQL_INSTANCE (a few minutes)..."
  gcloud sql instances create "$SQL_INSTANCE" \
    --database-version=POSTGRES_15 --tier="$SQL_TIER" --region="$REGION" \
    --storage-size=10 --storage-type=HDD --no-backup --availability-type=zonal
fi
log "Setting database password..."
gcloud sql users set-password "$DB_USER" --instance "$SQL_INSTANCE" \
  --password "$(secret_value db-password)" 2>/dev/null || \
gcloud sql users create "$DB_USER" --instance "$SQL_INSTANCE" \
  --password "$(secret_value db-password)"
if gcloud sql databases describe "$DB_NAME" --instance "$SQL_INSTANCE" >/dev/null 2>&1; then
  skip "database $DB_NAME"
else
  log "Creating database $DB_NAME..."
  gcloud sql databases create "$DB_NAME" --instance "$SQL_INSTANCE"
fi

# --- BigQuery dataset + tables + view ----------------------------------------
if bq --project_id="$PROJECT_ID" show --dataset "$BQ_DATASET" >/dev/null 2>&1; then
  skip "BigQuery dataset $BQ_DATASET"
else
  log "Creating BigQuery dataset $BQ_DATASET..."
  bq --project_id="$PROJECT_ID" --location="$REGION" mk --dataset "$PROJECT_ID:$BQ_DATASET"
fi
mk_table() {
  local table="$1"
  if bq --project_id="$PROJECT_ID" show "$BQ_DATASET.$table" >/dev/null 2>&1; then
    skip "table $table"
  else
    log "Creating table $table..."
    python3 "$ROOT/deploy/bq_schema.py" "$table" > "/tmp/hg_${table}.json"
    bq --project_id="$PROJECT_ID" mk --table "$BQ_DATASET.$table" "/tmp/hg_${table}.json"
  fi
}
mk_table raw_event_batches
mk_table session_features
mk_table training_features
mk_table benchmark_results
log "Creating/replacing view v_events..."
bq --project_id="$PROJECT_ID" query --use_legacy_sql=false \
  "CREATE OR REPLACE VIEW \`$PROJECT_ID.$BQ_DATASET.v_events\` AS
   SELECT message_id, publish_time,
          JSON_VALUE(data, '\$.session_id') AS session_id,
          data AS batch_json
   FROM \`$PROJECT_ID.$BQ_DATASET.raw_event_batches\`"

# --- Pub/Sub topic -----------------------------------------------------------
if gcloud pubsub topics describe "$PUBSUB_TOPIC" >/dev/null 2>&1; then
  skip "Pub/Sub topic $PUBSUB_TOPIC"
else
  log "Creating Pub/Sub topic $PUBSUB_TOPIC..."
  gcloud pubsub topics create "$PUBSUB_TOPIC"
fi

cat <<EOF

$(log "Setup complete.")
  Console password (save it): $(secret_value console-password)

Next: bash deploy/deploy.sh
EOF
