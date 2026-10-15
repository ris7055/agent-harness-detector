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
_Filled in once D1 lands._

## Privacy
The behaviour collector records timing and movement only. It never records key values, field contents or passwords. IP addresses are stored as salted hashes. The bank in the demo ("Bank Seroja") is fictional.
