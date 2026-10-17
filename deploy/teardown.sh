#!/usr/bin/env bash
# Save credit or tear down (SPEC section 13). Run from the repo root:
#   bash deploy/teardown.sh           # stop Cloud SQL (biggest idle cost)
#   bash deploy/teardown.sh --start   # resume Cloud SQL
#   bash deploy/teardown.sh --delete  # delete all created resources (asks first)
set -euo pipefail
# shellcheck source=deploy/lib.sh
. "$(dirname "$0")/lib.sh"
load_config

ACTION="${1:-stop}"

case "$ACTION" in
  stop)
    log "Stopping Cloud SQL instance $SQL_INSTANCE (Cloud Run scales to zero on its own)..."
    gcloud sql instances patch "$SQL_INSTANCE" --activation-policy=NEVER --quiet
    log "Done. Resume later with: bash deploy/teardown.sh --start"
    ;;
  --start)
    log "Starting Cloud SQL instance $SQL_INSTANCE..."
    gcloud sql instances patch "$SQL_INSTANCE" --activation-policy=ALWAYS --quiet
    ;;
  --delete)
    warn "This deletes Cloud Run services, Pub/Sub subscriptions, the Cloud SQL"
    warn "instance, the bucket and the BigQuery dataset for project $PROJECT_ID."
    read -r -p "Type the project id ($PROJECT_ID) to confirm: " confirm
    [ "$confirm" = "$PROJECT_ID" ] || die "confirmation did not match; nothing deleted."
    for svc in portal scorer console; do
      gcloud run services delete "$svc" --region "$REGION" --quiet 2>/dev/null || true
    done
    for sub in session-events-scorer session-events-bq; do
      gcloud pubsub subscriptions delete "$sub" --quiet 2>/dev/null || true
    done
    gcloud pubsub topics delete "$PUBSUB_TOPIC" --quiet 2>/dev/null || true
    gcloud sql instances delete "$SQL_INSTANCE" --quiet 2>/dev/null || true
    gcloud storage rm -r "gs://$BUCKET" 2>/dev/null || true
    bq --project_id="$PROJECT_ID" rm -r -f -d "$BQ_DATASET" 2>/dev/null || true
    log "Deleted. (Secrets and the Artifact Registry repo were left in place.)"
    ;;
  *)
    die "usage: teardown.sh [stop|--start|--delete]"
    ;;
esac
