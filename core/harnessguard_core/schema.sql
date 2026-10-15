-- HarnessGuard schema (SPEC section 8.1). Idempotent: safe to run on every startup.
CREATE TABLE IF NOT EXISTS users (
    id            serial PRIMARY KEY,
    username      text UNIQUE NOT NULL,
    password_hash text NOT NULL,
    full_name     text NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id             serial PRIMARY KEY,
    user_id        int NOT NULL REFERENCES users(id),
    account_number text UNIQUE NOT NULL,
    balance_cents  bigint NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payees (
    id             serial PRIMARY KEY,
    user_id        int NOT NULL REFERENCES users(id),
    name           text NOT NULL,
    bank           text NOT NULL,
    account_number text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS transfers (
    id           serial PRIMARY KEY,
    account_id   int NOT NULL REFERENCES accounts(id),
    session_id   uuid,
    to_name      text NOT NULL,
    to_bank      text NOT NULL,
    to_account   text NOT NULL,
    amount_cents bigint NOT NULL,
    reference    text NOT NULL DEFAULT '',
    status       text NOT NULL,  -- completed|pending_otp|blocked|failed_otp
    otp_code     text,
    otp_attempts int NOT NULL DEFAULT 0,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS loan_applications (
    id                   serial PRIMARY KEY,
    user_id              int NOT NULL REFERENCES users(id),
    session_id           uuid,
    amount_cents         bigint NOT NULL,
    tenure_months        int NOT NULL,
    monthly_income_cents bigint NOT NULL,
    employer             text NOT NULL,
    status               text NOT NULL,  -- approved|pending_otp|blocked|failed_otp
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    id            uuid PRIMARY KEY,
    user_id       int REFERENCES users(id),
    started_at    timestamptz NOT NULL DEFAULT now(),
    last_seen     timestamptz NOT NULL DEFAULT now(),
    user_agent    text,
    ip_hash       text,
    risk_score    real,
    risk_band     text,
    model_version text,
    event_count   int NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS session_events (
    session_id  uuid NOT NULL,
    seq         int NOT NULL,
    t_ms        real NOT NULL,
    wall_ms     bigint NOT NULL,
    type        text NOT NULL,
    page        text NOT NULL,
    data        jsonb NOT NULL DEFAULT '{}'::jsonb,
    received_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, seq)
);

-- GROUND TRUTH: never a model input (AGENTS.md rule 5)
CREATE TABLE IF NOT EXISTS session_labels (
    session_id uuid PRIMARY KEY,
    label      text NOT NULL,  -- human|agent
    variant    text,
    collector  text,
    task_id    text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decisions (
    id            serial PRIMARY KEY,
    session_id    uuid,
    action        text NOT NULL,
    score         real,
    band          text,
    decision      text NOT NULL,
    model_version text,
    latency_ms    int,
    features      jsonb,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cases (
    id           serial PRIMARY KEY,
    session_id   uuid,
    decision_id  int REFERENCES decisions(id),
    action       text,
    score        real,
    decision     text,
    status       text NOT NULL DEFAULT 'open',  -- open|confirmed_fraud|false_positive
    explanation  jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    reviewed_at  timestamptz
);

CREATE INDEX IF NOT EXISTS idx_session_events_session ON session_events(session_id);
CREATE INDEX IF NOT EXISTS idx_decisions_session ON decisions(session_id);
CREATE INDEX IF NOT EXISTS idx_cases_status_created ON cases(status, created_at);
CREATE INDEX IF NOT EXISTS idx_transfers_account ON transfers(account_id, created_at);
