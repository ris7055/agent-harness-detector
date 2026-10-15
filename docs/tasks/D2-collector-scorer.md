# D2 — Behaviour collector, features, scorer, live decisions

**Branch:** `feat/d2-scorer` · **Depends on:** D1 merged · **Target:** day 2 morning (Oct 16)
**Spec sections:** §5, §6, §7.1 (decision wiring), §7.2, §7.3, §8.3 (analytics sink)

## Build
1. `services/portal/static/collector.js` exactly per §5: all event types and payloads in §5.2 (privacy rules!), `seq` in `sessionStorage`, 50 ms mousemove throttle, 2 s batching, `sendBeacon` on pagehide, **awaited flush before form submit** (max 800 ms) that also sets `hg_last_seq`. No external libraries. Keep it < 300 lines and readable.
2. Portal `POST /api/events`: validate `EventBatch`; forward per `EVENT_TRANSPORT` (`http` → scorer `/v1/events`; `pubsub` → publish to `PUBSUB_TOPIC` with attribute `session_id`). Respond 204 fast; never let a scorer error break the page.
3. `core/harnessguard_core/features.py`: `FEATURE_NAMES` + `compute_features(events, until_seq=None)` implementing **every** feature in §6, missing → `-1`. Unit tests with hand-built fixture event lists: a "human-like" fixture (curvy mouse, varied key timing) and a "bot-like" fixture (no premove clicks, centre clicks, programmatic input, webdriver=true) — assert the key features differ in the expected direction and that the function is deterministic.
4. `core/harnessguard_core/rules.py`: baseline scorer per §7.3 returning `(score, top_reasons)`.
5. `core/harnessguard_core/analytics.py`: `AnalyticsSink` with `JsonlSink` (local, `data/analytics/*.jsonl`) and `BigQuerySink` (`insert_rows_json`), chosen by `ANALYTICS_SINK`; calls never raise into request handlers.
6. Scorer service: `/v1/events`, `/pubsub/events`, `/v1/decide`, `/v1/sessions/{id}/score`, `/healthz` per §7.2. Model loading per §7.3 (`MODEL_URI` empty → rules; local path or `gs://` supported; feature-name mismatch → rules + loud log). Case creation on step_up/block. Leave `/v1/cases/{id}/explain` as a stub returning 501 (D3 implements). Internal auth header `X-HG-Internal` (secret from env `INTERNAL_TOKEN`) on `/v1/*`; `/pubsub/events` accepts `?token=` matching `PUBSUB_PUSH_TOKEN`.
7. Portal: replace the D1 `decide()` stub with a call to scorer `/v1/decide` (2 s timeout, fail-open to `step_up`). Keep `FORCE_DECISION` working as a demo override when set.

## Acceptance criteria
- [ ] Browsing the portal locally produces rows in `session_events` within ~2 s; no key or input values anywhere in the DB (add a test that scans stored payloads for forbidden keys `key`, `value`, `password`).
- [ ] `sessions.risk_score` updates while browsing (visible via `GET /v1/sessions/{id}/score`).
- [ ] A transfer by a normal human click-through is usually `allow` under rules scoring; a quick scripted check (`tests/` using httpx to post a bot-like batch then decide) returns `step_up` or `block` and creates a `cases` row.
- [ ] `/v1/decide` p95 latency < 300 ms locally excluding the seq wait (log it in `decisions.latency_ms`).
- [ ] `EVENT_TRANSPORT=pubsub` code path exists and is unit-tested with a mocked publisher; `/pubsub/events` decodes a sample push envelope.
- [ ] `pytest` passes; README updated.
