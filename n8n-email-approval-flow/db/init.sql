-- Tables the n8n workflow reads and writes. Runs once, when the Postgres volume is first created.

-- One row per incoming email. The primary key on message_id is the duplicate guard:
-- if the same email is delivered twice, the second insert does nothing.
CREATE TABLE email_log (
    message_id   TEXT PRIMARY KEY,
    mailpit_id   TEXT,
    from_address TEXT,
    subject      TEXT,
    status       TEXT NOT NULL DEFAULT 'received',  -- received | approved | rejected | expired | needs_info | ignored
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Approved bookings only. UNIQUE(message_id) means one email can never become two bookings.
CREATE TABLE bookings (
    id              SERIAL PRIMARY KEY,
    message_id      TEXT NOT NULL UNIQUE REFERENCES email_log (message_id),
    request_type    TEXT NOT NULL,          -- equipment | location | other
    item            TEXT NOT NULL,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    production      TEXT NOT NULL,
    requester_name  TEXT,
    requester_email TEXT NOT NULL,
    notes           TEXT,
    approved_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Replies drafted for requests that are missing details. A person reviews and sends them.
CREATE TABLE reply_drafts (
    id          SERIAL PRIMARY KEY,
    message_id  TEXT NOT NULL REFERENCES email_log (message_id),
    to_address  TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per Claude call: tokens and cost, so we know what each booking costs.
CREATE TABLE ai_usage (
    id            SERIAL PRIMARY KEY,
    message_id    TEXT,
    model         TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd      NUMERIC(12, 8) NOT NULL,
    stop_reason   TEXT,
    route         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Filled by the separate "Booking errors" workflow whenever the main workflow fails.
CREATE TABLE workflow_errors (
    id            SERIAL PRIMARY KEY,
    workflow_name TEXT,
    execution_id  TEXT,
    failed_node   TEXT,
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
