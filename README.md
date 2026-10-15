# HarnessGuard: AI-agent session detection for online banking

> AI Builder Cup 2026 · BFSI: Intelligent Risk, Fraud & Financial Experiences

Fraudsters now use **AI agent harnesses**, LLMs driving real browsers, to automate account takeover, mule activity and fake applications. HarnessGuard detects in real time whether a banking session is operated by a **human or an AI agent**, before money moves. At the risk point it takes a graduated action (allow, OTP step-up or block), and Gemini writes an analyst-ready explanation.

**Built on Google Cloud:** Cloud Run · Pub/Sub · Cloud SQL · BigQuery · BigQuery ML + Vertex AI Model Registry · Gemini on Vertex AI · Cloud Storage · Secret Manager.

## Status
🚧 In active development. See [`docs/SPEC.md`](docs/SPEC.md) for the full design and [`docs/tasks/`](docs/tasks/) for the build plan.

## Repository guide
- [`docs/SPEC.md`](docs/SPEC.md): architecture, telemetry schema, features, APIs, data model, ML pipeline, deployment
- [`AGENTS.md`](AGENTS.md): rules for AI coding agents working on this repo
- [`docs/tasks/`](docs/tasks/): build tasks D1–D6 with acceptance criteria
- [`docs/DEVIN_PROMPTS.md`](docs/DEVIN_PROMPTS.md): session prompts and Git workflow

## Quickstart (local)

Requires Docker Desktop and Python 3.11 (for tests).

```powershell
copy .env.example .env          # optional — compose has safe defaults
docker compose up --build       # db + portal:8080 + scorer:8081 + console:8082
```

- **Portal:** http://localhost:8080 — sign in as `daniel` / `Seroja@2026`
  (also `aisyah`, `meiling`, `ravi`, `demo` — same password, demo only)
- **Scorer:** http://localhost:8081 (`/healthz` stub for now)
- **Console:** http://localhost:8082 (`/healthz` stub for now)
- **Data collection mode:** http://localhost:8080/collect (set `ALLOW_DATA_COLLECTION=false` to disable)

Force a decision path without the scorer (demo/testing only):

```powershell
$env:FORCE_DECISION = "step_up"   # allow | step_up | block
docker compose up -d portal
```

Tests (starts its own throwaway Postgres container; or point
`HG_TEST_DATABASE_URL` at a disposable database to skip testcontainers):

```powershell
pip install -r requirements-dev.txt
pytest
```

## Privacy
The behaviour collector records timing and movement only. It never records key values, field contents or passwords. IP addresses are stored as salted hashes. The bank in the demo ("Bank Seroja") is fictional.
