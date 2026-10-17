#!/usr/bin/env bash
# Build images and (re)deploy the three HarnessGuard Cloud Run services, then
# wire Pub/Sub (SPEC section 13). Run after deploy/setup.sh, from the repo root:
#   bash deploy/deploy.sh
set -euo pipefail
# shellcheck source=deploy/lib.sh
. "$(dirname "$0")/lib.sh"
load_config

TAG="$(date +%Y%m%d-%H%M%S)"
AR="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}"

log "Building images with Cloud Build (tag $TAG)..."
gcloud builds submit "$ROOT" --config "$ROOT/deploy/cloudbuild.yaml" \
  --substitutions "_AR_REPO=${AR_REPO},_REGION=${REGION},_TAG=${TAG}"

COMMON_ENV="ENV=cloud,GCP_PROJECT=${PROJECT_ID},GCP_REGION=${REGION}"
DB_ENV="DB_USER=${DB_USER},DB_NAME=${DB_NAME},INSTANCE_CONNECTION_NAME=${INSTANCE_CONNECTION_NAME}"
RUN_COMMON=(--region "$REGION" --service-account "$RUN_SA_EMAIL"
            --add-cloudsql-instances "$INSTANCE_CONNECTION_NAME"
            --min-instances=0 --max-instances=2 --allow-unauthenticated --quiet)

log "Deploying scorer..."
gcloud run deploy scorer --image "$AR/scorer:$TAG" "${RUN_COMMON[@]}" \
  --set-env-vars "${COMMON_ENV},${DB_ENV},EVENT_TRANSPORT=pubsub,ANALYTICS_SINK=bigquery,BQ_DATASET=${BQ_DATASET},MODEL_URI=gs://${BUCKET}/models/latest.json,BENCHMARK_URI=gs://${BUCKET}/benchmark/benchmark.json,LLM_MODE=vertex,GEMINI_MODEL=${GEMINI_MODEL},ALLOW_BELOW=${ALLOW_BELOW},BLOCK_ABOVE=${BLOCK_ABOVE}" \
  --set-secrets "DB_PASS=db-password:latest,INTERNAL_TOKEN=internal-token:latest,PUBSUB_PUSH_TOKEN=pubsub-push-token:latest,IP_HASH_SALT=ip-hash-salt:latest"
SCORER_URL="$(gcloud run services describe scorer --region "$REGION" --format='value(status.url)')"
log "  scorer: $SCORER_URL"

log "Deploying console..."
gcloud run deploy console --image "$AR/console:$TAG" "${RUN_COMMON[@]}" \
  --set-env-vars "${COMMON_ENV},${DB_ENV},BQ_DATASET=${BQ_DATASET},BENCHMARK_URI=gs://${BUCKET}/benchmark/benchmark.json" \
  --set-secrets "DB_PASS=db-password:latest,CONSOLE_PASSWORD=console-password:latest"
CONSOLE_URL="$(gcloud run services describe console --region "$REGION" --format='value(status.url)')"

log "Deploying portal..."
gcloud run deploy portal --image "$AR/portal:$TAG" "${RUN_COMMON[@]}" \
  --set-env-vars "${COMMON_ENV},${DB_ENV},EVENT_TRANSPORT=pubsub,PUBSUB_TOPIC=${PUBSUB_TOPIC},SCORER_URL=${SCORER_URL},ALLOW_DATA_COLLECTION=${ALLOW_DATA_COLLECTION}" \
  --set-secrets "DB_PASS=db-password:latest,SESSION_SECRET=session-secret:latest,IP_HASH_SALT=ip-hash-salt:latest,INTERNAL_TOKEN=internal-token:latest"
PORTAL_URL="$(gcloud run services describe portal --region "$REGION" --format='value(status.url)')"

# --- Pub/Sub: push subscription -> scorer, BigQuery subscription -> table -----
PUSH_TOKEN="$(secret_value pubsub-push-token)"
PUSH_ENDPOINT="${SCORER_URL}/pubsub/events?token=${PUSH_TOKEN}"
if gcloud pubsub subscriptions describe session-events-scorer >/dev/null 2>&1; then
  log "Updating push subscription session-events-scorer..."
  gcloud pubsub subscriptions modify-push-config session-events-scorer \
    --push-endpoint "$PUSH_ENDPOINT"
else
  log "Creating push subscription session-events-scorer..."
  gcloud pubsub subscriptions create session-events-scorer \
    --topic "$PUBSUB_TOPIC" --push-endpoint "$PUSH_ENDPOINT" \
    --ack-deadline 30 --min-retry-delay 10s
fi

# BigQuery subscription needs the Pub/Sub service agent to write the dataset.
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
PUBSUB_SA="service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"
for role in roles/bigquery.dataEditor roles/bigquery.metadataViewer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:$PUBSUB_SA" --role "$role" --condition=None >/dev/null
done
if gcloud pubsub subscriptions describe session-events-bq >/dev/null 2>&1; then
  skip "BigQuery subscription session-events-bq"
else
  log "Creating BigQuery subscription session-events-bq..."
  gcloud pubsub subscriptions create session-events-bq \
    --topic "$PUBSUB_TOPIC" \
    --bigquery-table "${PROJECT_ID}:${BQ_DATASET}.raw_event_batches" \
    --write-metadata
fi

cat <<EOF

$(log "Deploy complete.")
  Portal  (your Final Product Link): $PORTAL_URL
  Console (analyst dashboard):       $CONSOLE_URL
  Scorer  (internal):                $SCORER_URL

Open the portal and sign in as daniel / Seroja@2026.
Console password: run  gcloud secrets versions access latest --secret=console-password
Stop Cloud SQL when idle to save credit:  bash deploy/teardown.sh
EOF
