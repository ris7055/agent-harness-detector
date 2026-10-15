# HarnessGuard — Technical Specification

> AI Builder Cup 2026 · Challenge: **BFSI — Intelligent Risk, Fraud & Financial Experiences**
> Single source of truth for everyone building this repo (humans and AI coding agents).
> If code and this spec disagree, fix the code or open a note in `docs/REVIEW_NOTES.md` — do not silently change the design.

---

## 1. Problem and pitch

Fraudsters increasingly use **AI agent harnesses** — an LLM driving a real browser through Playwright/CDP (e.g. browser-use-style agents) — to automate account takeover, mule-account activity, card testing and fake loan applications. These agents defeat classic bot defences: they solve flows like a person, read the page semantically, and can spoof browser fingerprints.

**HarnessGuard** detects, in real time, whether an online-banking session is being operated by a **human or an AI agent**, *before money moves*, and explains why.

- **Input:** privacy-preserving behavioural telemetry from the bank's web page (mouse dynamics, keystroke *timing* — never key values, interaction rhythm, navigation pattern, browser-automation fingerprints).
- **Output:** a live risk score per session, an action at sensitive steps (allow / step-up OTP / block), and a Gemini-written analyst explanation with evidence.
- **Demo hook:** "Gemini attacks, Gemini explains" — a Gemini-driven browser agent tries to transfer money from a demo account; HarnessGuard catches it mid-flow; the analyst console explains why in plain language.

### Unique selling points (for the Opportunities slide)
1. Targets **LLM-driven agents**, not scripted bots — the gap CAPTCHAs and UA checks leave open.
2. **Behaviour over fingerprint**: we show (benchmark) that fingerprint-only detection collapses against a stealth agent, while behavioural features hold up.
3. **Decision at the point of risk**: scoring runs continuously, the decision is taken at the transfer confirmation, with graduated friction (OTP) instead of blanket blocking.
4. **Explainable**: every flag comes with a human-readable reason and evidence an analyst can verify (including a mouse-path replay).
5. **Privacy by design**: no keystroke values, no field contents, IP stored only as a salted hash.

---

## 2. System overview

```
 ┌──────────────────────── Browser ────────────────────────┐
 │  Bank Seroja (fictional) portal pages                    │
 │  + collector.js (behaviour + fingerprint telemetry)      │
 └───────────────┬──────────────────────────────────────────┘
                 │ POST /api/events (batched, every 2s + on submit)
                 ▼
 ┌──────────── portal (Cloud Run) ───────────┐
 │ FastAPI + Jinja: login, dashboard,        │
 │ transfer, OTP, loan, /collect mode        │
 │ publishes event batches ──────────────────┼──► Pub/Sub topic `session-events`
 │ on transfer submit: POST scorer /v1/decide│        │                 │
 └──────────────┬────────────────────────────┘        │ push sub        │ BigQuery sub
                │                                     ▼                 ▼
                │                      ┌──────── scorer (Cloud Run) ──┐  BigQuery
                │                      │ store events (Cloud SQL)     │  `raw_event_batches`
                │                      │ features.py → model → score  │
                └─────────────────────►│ /v1/decide → allow/OTP/block │──► BigQuery
                                       │ flagged → Gemini explanation │    `session_features`,
                                       │ → case in Cloud SQL          │    `decisions`
                                       └──────────────┬───────────────┘
                                                      ▼
                                       ┌──────── console (Cloud Run) ─┐
                                       │ Analyst dashboard: live      │
                                       │ sessions, cases, explanation,│
                                       │ mouse-path replay, benchmark │
                                       └──────────────────────────────┘
 Offline: redteam/ (Playwright + Gemini agents) generate attack sessions;
          ml/ builds dataset → trains XGBoost (+ BigQuery ML model registered in Vertex AI) → benchmark.
```

### Google Cloud services and their role

| Service | Role |
|---|---|
| **Cloud Run** | Three services: `portal`, `scorer`, `console`. |
| **Pub/Sub** | Topic `session-events`. Push subscription → `scorer /pubsub/events`. BigQuery subscription → `raw_event_batches` table (no code). |
| **Cloud SQL (PostgreSQL 15, smallest shared-core)** | Operational data: users, accounts, transfers, sessions, events, labels, cases, decisions. |
| **BigQuery** | Dataset `harness_detector`: raw event batches, per-decision feature snapshots, decisions, training features, benchmark results. |
| **BigQuery ML + Vertex AI Model Registry** | Boosted-tree classifier trained in BigQuery ML on `training_features`, registered to Vertex AI Model Registry (`model_registry='vertex_ai'`). Used as the cloud-native comparison model in the benchmark. **No always-on Vertex endpoint** (cost). |
| **Gemini on Vertex AI** | (1) Analyst explanation for flagged sessions (structured JSON). (2) The red-team browser agent's brain. |
| **Cloud Storage** | Bucket for the trained XGBoost model file and benchmark JSON. |
| **Secret Manager** | DB password, console password, session secret. |
| **Artifact Registry + Cloud Build** | Container images for the three services. |
| *Vertex AI Search* (stretch) | Retrieve the bank's step-up policy to cite in explanations. Only if time allows. |
| *Document AI* (future work only) | Agent-submitted loan applications with forged documents. Not built. |

Region: `asia-southeast1` (Singapore) unless the team decides otherwise. All names configurable in `deploy/config.env`.

---

## 3. Repository layout

```
agent-harness-detector/
├── AGENTS.md                  # rules for AI coding agents (read first)
├── README.md                  # project overview + quickstart (kept current)
├── docker-compose.yml         # full local stack
├── .env.example               # every env var, with safe local defaults
├── core/                      # shared Python package (installed in all services)
│   ├── pyproject.toml
│   └── harnessguard_core/
│       ├── config.py          # pydantic-settings, reads env
│       ├── db.py              # SQLAlchemy engine/session
│       ├── schema.sql         # idempotent DDL (CREATE TABLE IF NOT EXISTS ...)
│       ├── models.py          # SQLAlchemy models or thin query helpers
│       ├── events.py          # pydantic models for event batches (section 5)
│       ├── features.py        # session events → feature dict (section 6) — ONE implementation, used online and offline
│       ├── rules.py           # rule-based baseline scorer
│       └── analytics.py       # BigQuery sink (cloud) / JSONL sink (local)
├── services/
│   ├── portal/                # FastAPI + Jinja + static/collector.js
│   ├── scorer/                # FastAPI: ingest, score, decide, explain
│   └── console/               # FastAPI + Jinja + Chart.js analyst dashboard
├── redteam/                   # Playwright + Gemini attack agents (run from laptop)
├── ml/                        # dataset builder, training, benchmark, BQML SQL
├── deploy/                    # config.env.example, setup.sh, deploy.sh, cloudbuild.yaml
├── data/                      # local-only outputs (gitignored except .gitkeep)
├── tests/                     # pytest
└── docs/
    ├── SPEC.md                # this file
    ├── tasks/                 # one file per build task (D1..D6)
    ├── DEVIN_PROMPTS.md       # prompts to start each build session
    └── REVIEW_NOTES.md        # reviewer findings
```

Each service has its own `Dockerfile` and `requirements.txt`; images are built with the **repo root as build context** so they can `pip install ./core`.

---

## 4. Tech stack (fixed — do not substitute)

- **Python 3.11**, **FastAPI**, **Uvicorn**, **Jinja2** templates, **SQLAlchemy 2.x** with **psycopg 3**.
- Frontend: server-rendered HTML + **Tailwind via CDN** + vanilla JS. **Chart.js via CDN** in the console. No React/Next.js, no Node build step.
- DB: **PostgreSQL 15** (Cloud SQL in cloud, `postgres:15` container locally). Schema via idempotent `core/harnessguard_core/schema.sql` applied on service startup. No Alembic.
- ML: **xgboost**, **scikit-learn**, **pandas**, **shap** optional (XGBoost `pred_contribs=True` is enough).
- Gemini: **`google-genai`** SDK. `LLM_MODE=vertex` uses Vertex AI with the service account; `LLM_MODE=apikey` uses a Gemini API key (local dev / red team); `LLM_MODE=mock` returns deterministic canned output (tests, offline dev). Model name from `GEMINI_MODEL` env (default `gemini-2.5-flash`; the team may switch to the newest GA Flash model available in their region — never hardcode the name elsewhere).
- GCP clients: `google-cloud-pubsub`, `google-cloud-bigquery`, `google-cloud-storage`.
- Red team: **Playwright for Python** (Chromium).
- Tests: **pytest**, **httpx** TestClient.

---

## 5. Telemetry: collector.js and the event schema

`services/portal/static/collector.js` is included on every portal page.

### 5.1 Session identity
- On first page load the portal sets an HTTP-only cookie `hg_sid` (UUID4) and creates a `sessions` row. The collector reads the session id from a `<meta name="hg-session" content="...">` tag.
- `seq` is a per-session monotonic counter kept in `sessionStorage` (survives page navigation within the tab).

### 5.2 What is captured (privacy rules are mandatory)
| Event `type` | Payload fields | Notes |
|---|---|---|
| `fingerprint` | `webdriver` (bool), `ua`, `languages_count`, `plugins_count`, `hardware_concurrency`, `device_memory`, `screen_w`, `screen_h`, `inner_w`, `inner_h`, `outer_w`, `outer_h`, `dpr`, `timezone`, `touch_points`, `has_chrome_obj` (bool), `webgl_renderer`, `notification_permission` | Once per page load. |
| `page` | `path`, `referrer_path` | On load. |
| `mousemove` | `x`, `y` | Throttled to one sample per 50 ms. |
| `click` | `x`, `y`, `target_id`, `target_tag`, `target_rect` `{x,y,w,h}`, `is_trusted`, `button` | |
| `keydown` / `keyup` | `key_class` ∈ `char`, `digit`, `backspace`, `tab`, `enter`, `other`; `field_id`; `is_trusted` | **Never the key value.** |
| `input` | `field_id`, `value_length` | **Never the value.** Used to detect programmatic fills (value changes with no key events). |
| `paste` | `field_id` | |
| `focus` / `blur` | `field_id` | |
| `scroll` | `scroll_y` | Throttled 100 ms. |
| `visibility` | `state` | |
| `submit` | `form_id` | |

Every event: `{ "seq": int, "t": float /* performance.now() ms since page load */, "wall": int /* Date.now() */, "type": str, "page": str, "data": {...} }`.

### 5.3 Transport
- Batches are POSTed to the portal's same-origin `POST /api/events` every **2 s**, on `visibilitychange`/`pagehide` (via `navigator.sendBeacon`), and **synchronously flushed before any form submit** (the submit handler awaits the flush, max 800 ms, then submits).
- Batch body (`core/harnessguard_core/events.py: EventBatch`):
```json
{ "session_id": "uuid", "page_load_id": "uuid", "sent_at": 1760000000000,
  "events": [ { "seq": 1, "t": 12.5, "wall": 1760000000000, "type": "page", "page": "/login", "data": {"path": "/login", "referrer_path": ""} } ] }
```
- Every form that triggers a decision includes a hidden input `hg_last_seq` with the last seq sent, so the scorer can wait until it has seen that seq (section 7.3).
- Portal `/api/events` validates the batch, then forwards it according to `EVENT_TRANSPORT`:
  - `http` (local): POST to `${SCORER_URL}/v1/events`.
  - `pubsub` (cloud): publish JSON to topic `session-events` with attribute `session_id`.

---

## 6. Features (`core/harnessguard_core/features.py`)

`compute_features(events: list[Event], until_seq: int | None = None) -> dict[str, float]` — pure function, no I/O, deterministic. Missing data → feature value `-1` (never NaN). This **same function** is used by the scorer online and by `ml/build_dataset.py` offline.

**Fingerprint (`fp_`)** — taken from the latest `fingerprint` event:
`fp_webdriver`, `fp_headless_ua` (UA contains `HeadlessChrome`), `fp_plugins_zero`, `fp_outer_zero` (outer_w==0 or outer_h==0), `fp_languages_count`, `fp_no_chrome_obj`, `fp_swiftshader` (webgl_renderer contains `SwiftShader`/`llvmpipe`), `fp_inner_eq_outer` (window chrome missing).

**Mouse (`mouse_`)**:
`mouse_move_count`, `mouse_moves_per_sec`, `mouse_path_len`, `mouse_straightness_mean` (per segment between clicks: displacement / path length; 1.0 = perfectly straight), `mouse_speed_mean`, `mouse_speed_cv`, `mouse_accel_std`, `mouse_angle_change_mean`, `mouse_pause_count` (gaps > 300 ms while on page).

**Clicks (`click_`)**:
`click_count`, `click_no_premove_ratio` (clicks with no mousemove in the preceding 500 ms), `click_center_offset_mean` (distance of click point from target rect centre, normalised by rect half-diagonal; bots ≈ 0), `click_center_offset_std`, `click_untrusted_ratio`.

**Keyboard (`key_`)**:
`key_count`, `key_interval_mean`, `key_interval_cv` (inter-keydown intervals within a field), `key_hold_mean`, `key_hold_cv` (keydown→keyup), `key_backspace_ratio`, `key_tab_ratio`, `key_untrusted_ratio`.

**Input (`input_`)**:
`input_programmatic_ratio` (input events where value_length increased by ≥ 2 with no keydown in the same field within 100 ms), `paste_count`, `input_fields_touched`.

**Timing / navigation (`time_`, `nav_`)**:
`time_total_s`, `time_to_first_interaction_s` (per page, mean), `time_page_dwell_mean_s`, `time_page_dwell_cv`, `time_action_interval_cv` (intervals between clicks/keydowns/submits), `actions_per_sec`, `nav_page_count`, `nav_direct_to_sensitive` (reached `/transfer` without visiting `/dashboard` first), `focus_without_click_ratio`, `scroll_count`, `visibility_hidden_count`.

Feature list is the contract: keep `FEATURE_NAMES` (ordered list) in `features.py`; the model, BigQuery schema and console all read from it. Adding a feature = append to the list + unit test.

---

## 7. Services and APIs

### 7.1 portal (port 8080)
Pages (all server-rendered, fictional brand **"Bank Seroja"** with a visible "DEMO — fictional bank" ribbon):
- `GET /` → redirect to `/login`.
- `GET/POST /login` — username + password (seeded demo users, section 8.2). Session cookie auth (signed with `SESSION_SECRET`).
- `GET /dashboard` — balance, last 5 transactions, buttons to Transfer / Apply for loan.
- `GET/POST /transfer` — recipient name, recipient bank (select: 6 fictional bank names), recipient account number, amount (RM), reference. POST validates and shows `/transfer/review`.
- `POST /transfer/confirm` — **decision point**: calls `POST {SCORER_URL}/v1/decide` with `{session_id, action:"transfer", last_seq, context:{amount_cents, to_account, new_payee: bool}}`. Result:
  - `allow` → execute transfer, show success page.
  - `step_up` → create `pending_otp` transfer, show `/otp` page. Demo OTP is shown in a dismissible banner ("SMS simulation: your code is 482913"). Correct OTP → complete; 3 wrong → block.
  - `block` → transfer `blocked`, show "Transfer held for review — reference CASE-xxxx".
  - Scorer unreachable or timeout (2 s) → **fail-open to `step_up`** and log.
- `GET/POST /loan` — simple loan application form (amount, tenure, income, employer). Decision point action `"loan_apply"`; same allow/step_up/block flow (no money moves).
- `POST /api/events` — section 5.3.
- `GET /collect` — **data collection mode** (section 9.1). Not linked from bank pages.
- `GET /healthz`.

### 7.2 scorer (port 8081)
- `POST /v1/events` — body `EventBatch`. Inserts events into `session_events` (ignore duplicate `(session_id, seq)`), updates `sessions.last_seen`, recomputes features + score (debounced: at most once per 1 s per session), updates `sessions.risk_score`, `risk_band`, `model_version`.
- `POST /pubsub/events` — Pub/Sub push envelope; base64-decode `message.data` → same handler. Return 204 on success, 400 on malformed (so Pub/Sub does not retry poison messages forever).
- `POST /v1/decide` — body `{session_id, action, last_seq, context}`.
  1. Wait up to 1.5 s (poll 100 ms) until `session_events` has `seq >= last_seq`.
  2. Compute features up to now; score with the active model (fallback: rules).
  3. Band: `score < ALLOW_BELOW (0.50)` → `allow`; `< BLOCK_ABOVE (0.85)` → `step_up`; else `block`. Thresholds from env. Context can only raise friction: `amount_cents >= 500000` with score ≥ 0.35 → at least `step_up`.
  4. Insert `decisions` row (with latency_ms). If `step_up` or `block` → create `cases` row and enqueue explanation (FastAPI `BackgroundTasks`; never block the decision on Gemini).
  5. Write feature snapshot + decision to analytics sink.
  6. Respond `{decision, score, band, case_id|null, model_version, latency_ms, top_reasons:[{feature, value, contribution}]}` — p95 latency target < 300 ms excluding the seq wait.
- `GET /v1/sessions/{id}/score` — current score, band, top reasons.
- `POST /v1/cases/{id}/explain` — (re)generate Gemini explanation.
- `GET /healthz`.

### 7.3 Scoring
- `rules.py` baseline: weighted sum of clear signals (`fp_webdriver`, `fp_headless_ua`, `click_no_premove_ratio`, `click_center_offset_mean < 0.1`, `input_programmatic_ratio`, `key_interval_cv < 0.15`, `mouse_straightness_mean > 0.97`), squashed to [0,1]. Used until a model exists and as a benchmark baseline.
- Model: XGBoost binary classifier (`agent=1`). Loaded at startup from `MODEL_URI` (`gs://...` or local path), with its `model_meta.json` (`version`, `feature_names`, `trained_at`, `metrics`). If the feature list mismatches → refuse to load, use rules, log loudly.
- Reasons: XGBoost `pred_contribs=True` → top 5 features by positive contribution.

### 7.4 Gemini explainer (`services/scorer/explain.py`)
Input to the model: action + context, score, band, top reasons with values, a compact fingerprint summary, and reference ranges for humans (from `model_meta.json` → per-feature human median/IQR). Prompt asks for **JSON only** (use `response_mime_type="application/json"` with a response schema):
```json
{ "verdict": "likely_ai_agent | likely_human | uncertain",
  "confidence": "low | medium | high",
  "summary": "one or two sentences an analyst can read in 5 seconds",
  "evidence": ["bullet with the concrete number and how it compares to typical humans", "..."],
  "recommended_action": "allow | step_up | block_and_review",
  "analyst_next_steps": ["..."] }
```
Rules in the prompt: never invent signals not in the input; cite numbers; be concise. Store in `cases.explanation` (jsonb). On any Gemini error store `{"error": "..."}` and keep the case — the console shows the raw top reasons instead.

### 7.5 console (port 8082)
Protected by a single shared password (`CONSOLE_PASSWORD`, cookie session). Pages:
- `/` **Live sessions**: table auto-refreshing every 3 s (fetch JSON endpoint) — session id (short), user, started, pages, current score with colour band, last action, label if known (data-collection sessions only, shown as a small grey tag).
- `/cases` list (open first) and `/cases/{id}` **case detail**: decision, score gauge, Gemini summary + evidence + next steps, top-reason bar chart (Chart.js), fingerprint table, **mouse-path replay** (canvas: draw the mousemove trajectory per page over a page-sized box, clicks as dots, animated playback button), event timeline. Buttons: "Confirm fraud" / "False positive" → updates `cases.status` (analyst feedback).
- `/log` **Detection log**: chronological audit trail of every decision (newest first, auto-refresh 3 s): time, session (link), user, action (transfer/loan), amount, score, band, decision, model version, latency ms, top 3 reasons. Filters: decision, band, time range, user. "Export CSV" button. Each row expands to the event-level timeline. Data from `decisions` joined with `sessions`/`cases`.
- `/benchmark`: renders `benchmark.json` (from `BENCHMARK_URI`) — metrics table per model, per-variant detection rates, ROC curve, early-detection curve, latency.
- JSON endpoints under `/api/...` for the auto-refresh.

---

## 8. Data model

### 8.1 Cloud SQL / Postgres (`schema.sql`)
```sql
users(id serial pk, username text unique, password_hash text, full_name text)
accounts(id serial pk, user_id int fk, account_number text unique, balance_cents bigint)
payees(id serial pk, user_id int fk, name text, bank text, account_number text, created_at timestamptz)
transfers(id serial pk, account_id int fk, session_id uuid, to_name text, to_bank text, to_account text,
          amount_cents bigint, reference text, status text /* completed|pending_otp|blocked|failed_otp */,
          otp_code text, otp_attempts int default 0, created_at timestamptz)
loan_applications(id serial pk, user_id int fk, session_id uuid, amount_cents bigint, tenure_months int,
          monthly_income_cents bigint, employer text, status text, otp_code text,
          otp_attempts int default 0, created_at timestamptz)
sessions(id uuid pk, user_id int null, started_at timestamptz, last_seen timestamptz, user_agent text,
         ip_hash text, risk_score real, risk_band text, model_version text, event_count int default 0)
session_events(session_id uuid, seq int, t_ms real, wall_ms bigint, type text, page text, data jsonb,
               received_at timestamptz, primary key(session_id, seq))
session_labels(session_id uuid pk, label text /* human|agent */, variant text, collector text,
               task_id text, created_at timestamptz)          -- GROUND TRUTH: never a model input
decisions(id serial pk, session_id uuid, action text, score real, band text, decision text,
          model_version text, latency_ms int, features jsonb, created_at timestamptz)
cases(id serial pk, session_id uuid, decision_id int, action text, score real, decision text,
      status text /* open|confirmed_fraud|false_positive */, explanation jsonb, created_at timestamptz,
      reviewed_at timestamptz)
```
Indexes on `session_events(session_id)`, `decisions(session_id)`, `cases(status, created_at)`.

### 8.2 Seed data (`core/.../seed.py`, idempotent)
Users `aisyah`, `daniel`, `meiling`, `ravi`, `demo` — password `Seroja@2026` for all (demo only, documented), each with one account, RM 5,000–25,000 balance and 5 past transactions. Six fictional recipient banks: "Bank Mawar", "Teratai Bank", "Kenanga Digital", "Bank Cempaka", "Melur Islamic", "Orkid Bank".

### 8.3 BigQuery dataset `harness_detector`
- `raw_event_batches` — written by the Pub/Sub BigQuery subscription (`subscription_name, message_id, publish_time, data STRING, attributes STRING`).
- `v_events` — view: JSON-parses `data` and unnests events.
- `session_features` — one row per decision: `session_id, decided_at, action, model_version, score, decision, <one FLOAT64 column per FEATURE_NAMES>`.
- `training_features` — written by `ml/build_dataset.py`: `session_id, label INT64, variant, collector, task_id, split, <features>`.
- `benchmark_results` — one row per (model, metric, slice).

The analytics sink writes `session_features` with `insert_rows_json`, best-effort and off the request path. Local mode writes JSONL to `data/analytics/`.

---

## 9. Data collection and red team

### 9.1 Human sessions (`/collect`)
`/collect` shows: name/nickname field (stored as `collector`), a consent line ("we record mouse/keyboard timing, not what you type"), and a **Start task** button. It assigns a random task card, e.g. *"Log in as `daniel` / `Seroja@2026`, check your balance, then transfer RM 137.50 to Lim Wei Jie at Teratai Bank, account 8812 0045 3301, reference 'dinner'."*, writes a `session_labels` row (`label=human`, `task_id`), and opens the login page in the same session. Tasks: `transfer_known`, `transfer_new_payee`, `loan_apply`, `browse_only`. Parameters randomised from a fixed list in `core/.../tasks.py` — the **same task generator is used by the red team**, so humans and agents do identical tasks (no task confound).

### 9.2 Agent sessions (`redteam/`)
Run from a laptop against a portal URL. A run opens the portal with `?hg_label=agent&hg_variant=<v>&hg_task=<task_id>` on `/collect/agent` (an endpoint that records the label server-side and redirects to `/login`; only enabled when `ALLOW_DATA_COLLECTION=true`). Variants:

| Variant | Description |
|---|---|
| `script_fill` | Scripted Playwright, `page.fill()` + `page.click()`, headless. Classic bot baseline. |
| `script_type` | Scripted Playwright, `page.type(delay=60)`, headless. |
| `llm_headless` | **Gemini agent loop**: each step sends a compact accessibility/DOM summary + task to Gemini, receives one JSON action (`click`, `type`, `select`, `navigate`, `done`), executes with Playwright. Headless Chromium. |
| `llm_headed` | Same, headed Chromium. |
| `llm_stealth` | Same, headed, plus stealth: `navigator.webdriver` hidden, fake plugins/languages, realistic UA/viewport, humanised timing (random think-time 0.4–2.5 s, per-key delays from a log-normal), Bézier mouse movement to a random point inside the target. **The hardest adversary — must exist for the benchmark story.** |
| `browser_use` (optional) | The open-source `browser-use` library with Gemini, if it installs cleanly. |

`redteam/run.py --base-url URL --variant V --n N --task random --concurrency 2` — logs each run to `data/redteam_runs.jsonl` (variant, task, success/blocked/step_up, duration). Gemini for the red team uses `LLM_MODE=apikey` by default to save cloud credit.

---

## 10. ML pipeline (`ml/`)

1. `build_dataset.py --source postgres|bigquery` → loads events + `session_labels` (only labelled sessions), computes features **up to the first decision point** (or end of session if no decision), assigns a **grouped split**: humans grouped by `collector`, agents by `variant` × run batch — so the test set contains people and runs never seen in training. Also a held-out **variant split**: train without `llm_stealth`, test on it. Writes `data/training_features.parquet` and (cloud) `harness_detector.training_features`.
2. `train.py` → XGBoost (`max_depth=4, n_estimators=300, learning_rate=0.05, subsample=0.8`, `scale_pos_weight` for imbalance) → `data/model/model.json` + `model_meta.json` (version = UTC timestamp, feature_names, human per-feature median/IQR, metrics). `--upload gs://BUCKET/models/` uploads and updates `gs://BUCKET/models/latest.json` pointer.
3. `bqml/train.sql` → `CREATE OR REPLACE MODEL harness_detector.agent_clf OPTIONS(model_type='BOOSTED_TREE_CLASSIFIER', input_label_cols=['label'], model_registry='vertex_ai', vertex_ai_model_id='harnessguard_agent_clf')` on the train split; `bqml/evaluate.sql` → `ML.EVALUATE` on the test split.
4. `benchmark.py` → evaluates on the test split: **rules baseline**, **fingerprint-only XGBoost**, **behaviour-only XGBoost**, **full XGBoost**, and **BQML** (reads its `ML.PREDICT` output). Metrics: precision, recall, F1, ROC-AUC, **false-positive rate on humans**, detection rate per variant (especially `llm_stealth`), **early detection** (F1 using only the first 5/10/20/30 s of each session), decision latency p50/p95 (from `decisions`). Writes `data/benchmark.json` (+ upload to GCS, + `benchmark_results` table) and PNG charts in `data/charts/` for the slides.

Honesty rule: report the real numbers and dataset sizes; never train on test sessions; no synthetic "human" sessions.

---

## 11. Configuration (`.env.example`)

```
ENV=local                      # local|cloud
DATABASE_URL=postgresql+psycopg://hg:hg@db:5432/harnessguard
SESSION_SECRET=change-me
CONSOLE_PASSWORD=change-me
SCORER_URL=http://scorer:8081
EVENT_TRANSPORT=http           # http|pubsub
GCP_PROJECT=
GCP_REGION=asia-southeast1
PUBSUB_TOPIC=session-events
BQ_DATASET=harness_detector
ANALYTICS_SINK=jsonl           # jsonl|bigquery
MODEL_URI=                     # empty → rules; local path or gs://.../latest.json
BENCHMARK_URI=./data/benchmark.json
LLM_MODE=mock                  # mock|apikey|vertex
GEMINI_MODEL=gemini-2.5-flash
GEMINI_API_KEY=
ALLOW_BELOW=0.50
BLOCK_ABOVE=0.85
ALLOW_DATA_COLLECTION=true
IP_HASH_SALT=change-me
INTERNAL_TOKEN=change-me       # portal → scorer header X-HG-Internal
PUBSUB_PUSH_TOKEN=change-me    # ?token= on the Pub/Sub push URL
FORCE_DECISION=                # demo/testing override: allow|step_up|block (empty = use scorer)
```

---

## 12. Local development

```
cp .env.example .env
docker compose up --build        # db + portal:8080 + scorer:8081 + console:8082
# portal  http://localhost:8080   console http://localhost:8082
pytest
```
Red team locally: `pip install -r redteam/requirements.txt && playwright install chromium`, then `python redteam/run.py --base-url http://localhost:8080 --variant script_fill --n 3`.

---

## 13. Cloud deployment (run by a human from Google Cloud Shell)

`deploy/config.env.example` → copy to `deploy/config.env` (gitignored): `PROJECT_ID, REGION, AR_REPO, SQL_INSTANCE, DB_NAME, DB_USER, BUCKET, ...`.

- `deploy/setup.sh` (idempotent, safe to re-run): enable APIs (run, cloudbuild, artifactregistry, sqladmin, pubsub, bigquery, aiplatform, storage, secretmanager); create Artifact Registry repo; create Cloud SQL instance (`db-f1-micro`, PostgreSQL 15, no HA, 10 GB HDD), database and user; create secrets (generate random values if absent); create bucket; create BigQuery dataset + tables + view; create Pub/Sub topic; create runtime service account `harnessguard-run` with roles: `cloudsql.client`, `pubsub.publisher`, `bigquery.dataEditor`, `bigquery.jobUser`, `storage.objectAdmin` (bucket-scoped), `aiplatform.user`, `secretmanager.secretAccessor`; create the BigQuery subscription (grant the Pub/Sub service agent BigQuery write on the dataset).
- `deploy/deploy.sh`: `gcloud builds submit --config deploy/cloudbuild.yaml` (builds 3 images) → `gcloud run deploy` each service with `--add-cloudsql-instances`, `--set-secrets`, `--set-env-vars`, `--service-account`, `--min-instances=0 --max-instances=2`, `--allow-unauthenticated` for portal and console; scorer also unauthenticated **but** requires header `X-HG-Internal: <secret>` on `/v1/*` except Pub/Sub push, which uses a push-auth OIDC token verified against the subscription service account (simpler acceptable fallback for the prototype: a `?token=` secret in the push URL). Then create/update the push subscription to the scorer URL and print all three URLs.
- `deploy/teardown.sh`: stops Cloud SQL (`--activation-policy=NEVER`) to save credit; `--delete` flag deletes everything.
- Cost guardrails: Cloud SQL smallest tier and stop it when idle; `min-instances=0`; Gemini Flash only; no Vertex endpoints.

---

## 14. Demo script (3-minute video)

1. (0:00) Problem: AI agents now operate banking sessions; CAPTCHAs don't stop them.
2. (0:25) Human logs into Bank Seroja, transfers RM 120 → allowed. Console shows the session green.
3. (0:55) `python redteam/run.py --variant llm_stealth` — Gemini agent logs in and attempts a RM 4,800 transfer to a new payee.
4. (1:30) Portal shows "held for review". Console: case opens live, Gemini explanation, mouse-path replay (straight jumps vs human curves).
5. (2:10) Benchmark page: fingerprint-only fails on stealth, behaviour model holds; early detection within N seconds; latency.
6. (2:40) Architecture + Google Cloud services, close.

---

## 15. Out of scope

Real banking integrations, real OTP/SMS, mobile apps, multi-tenant auth, Document AI, production-grade security hardening. Mention as future work.
