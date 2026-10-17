# Deploying HarnessGuard to Google Cloud

Everything runs from **Google Cloud Shell** (the terminal in the Cloud Console —
it already has `gcloud`, `bq` and your login, so there are no keys to manage). You
do **not** need Docker or anything installed locally for this.

## 0. One-time: a project with billing

1. In the [Cloud Console](https://console.cloud.google.com), create (or pick) a
   project on the Google account that has **free trial credit**.
2. Make sure billing is enabled and set a **budget alert** (Billing → Budgets &
   alerts, e.g. US$20) so nothing surprises you.

## 1. Open Cloud Shell and clone

Click the **Activate Cloud Shell** icon (top right of the console), then:

```bash
git clone https://github.com/ris7055/agent-harness-detector.git
cd agent-harness-detector
cp deploy/config.env.example deploy/config.env
vim deploy/config.env     # set PROJECT_ID; the rest can stay default
```

`deploy/config.env` is gitignored — it never leaves your machine.

## 2. Create the infrastructure (once)

```bash
bash deploy/setup.sh
```

This enables the APIs and creates: an Artifact Registry repo, random secrets in
Secret Manager, a runtime service account with the right roles, a Cloud Storage
bucket, a small Cloud SQL (PostgreSQL 15) instance + database, the BigQuery
dataset + tables + view, and the Pub/Sub topic. It is **idempotent** — re-run it
any time; existing resources are left alone. It prints the **console password**
at the end (save it).

## 3. Build and deploy the services

```bash
bash deploy/deploy.sh
```

This builds the three images with Cloud Build and deploys `portal`, `scorer` and
`console` to Cloud Run, wires the Pub/Sub push subscription (→ scorer) and the
BigQuery subscription (→ `raw_event_batches`), and prints three URLs:

- **Portal** — your public demo bank. This is the **Final Product Link** for the
  submission. Sign in as `daniel` / `Seroja@2026`.
- **Console** — the analyst dashboard (minimal until task D5 lands).
- **Scorer** — internal; protected by a header/token.

Re-run `deploy/deploy.sh` any time to ship new code (it builds a fresh image tag
and updates the services in place).

## 4. Use it

- Browse the portal and make a transfer — the live risk score updates and
  sensitive actions go through allow / OTP / block.
- Point the red team at the live site from your laptop (see `redteam/README.md`):
  `python redteam/run.py --base-url https://<portal-url> --variant llm_headless --n 10 --i-own-this-target`

## 5. Logs

```bash
gcloud run services logs read portal --region <REGION> --limit 50
gcloud run services logs read scorer --region <REGION> --limit 50
```

## 6. Save credit **while still building**

Cloud Run scales to zero on its own. **Cloud SQL does not** — stop it when you are
not working _during development_:

```bash
bash deploy/teardown.sh            # stop Cloud SQL
bash deploy/teardown.sh --start    # resume before the next session
bash deploy/teardown.sh --delete   # remove everything (asks for confirmation)
```

## 7. Always-on (24/7) mode — for judging

The submission's **Final Product Link** must be live for judges to open at any
time, through to the Dec 4 finale. Once you submit, treat the deployment as
always-on:

- **Do NOT stop Cloud SQL.** `teardown.sh` (stop) or `--delete` would take the
  portal down. Leave the instance running the whole time.
- **The portal and console stay warm automatically.** `deploy.sh` gives them
  `min-instances=1`, so a judge opening the link gets no cold-start lag. (The
  scorer scales to zero; its first call after idle adds ~2 s, which is fine. To
  trim a little credit you can set `WARM_PORTAL=0 WARM_CONSOLE=0 bash
  deploy/deploy.sh`, at the cost of a brief wake-up on the first visit.)
- **Keep credit alive past Dec 4.** Keep the budget alert on. If the 90-day free
  trial would expire before the finale, upgrade the project to pay-as-you-go
  (Billing → upgrade) so services don't pause — the ongoing cost is still only
  a few dollars a month.
- **Verify it's up** any time:
  ```bash
  curl -s "$(gcloud run services describe portal --region <REGION> --format='value(status.url)')/healthz"
  gcloud sql instances describe <SQL_INSTANCE> --format='value(state)'   # want RUNNABLE
  ```
- **Put these in your submission** so judges can actually use it: the portal URL
  with login `daniel` / `Seroja@2026`, the console URL with the console
  password, and the `/collect` link to try it as a fresh user.

## Rough cost

With the smallest Cloud SQL tier (`db-f1-micro`), Cloud Run at `min-instances=0`,
Gemini Flash and no always-on Vertex endpoints, a few days of hackathon use is a
small fraction of the trial credit — mostly the Cloud SQL hours (so stop it when
idle). The console password is always retrievable:

```bash
gcloud secrets versions access latest --secret=console-password
```
