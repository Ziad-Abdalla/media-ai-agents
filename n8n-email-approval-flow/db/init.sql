-- Tables the n8n workflows read and write. Runs once, when the Postgres volume is first created.
-- All names, shows and equipment below are made up for the demo (synthetic data).

-- What the production company can book: studios, equipment, crew and locations it controls.
-- Claude picks one of these codes from the email; the clash check counts units per code.
CREATE TABLE resources (
    code             TEXT PRIMARY KEY,
    kind             TEXT NOT NULL CHECK (kind IN ('studio', 'equipment', 'crew', 'location')),
    name_en          TEXT NOT NULL,
    name_ar          TEXT NOT NULL,
    units            INTEGER NOT NULL CHECK (units > 0),   -- how many we own (or crew we have)
    odoo_res_model_id INTEGER,                              -- filled by scripts/odoo_link.py, optional
    odoo_res_id      INTEGER
);

INSERT INTO resources (code, kind, name_en, name_ar, units) VALUES
    ('STUDIO-1',          'studio',    'Studio 1 (sound stage)',               'استوديو 1 (مسرح صوتي)',          1),
    ('STUDIO-2',          'studio',    'Studio 2 (green screen)',              'استوديو 2 (شاشة خضراء)',         1),
    ('CAM-ALEXA-LF',      'equipment', 'ARRI Alexa Mini LF camera kit',        'طقم كاميرا ARRI Alexa Mini LF',  3),
    ('LENS-SIG-PRIME',    'equipment', 'ARRI Signature Prime lens set',        'طقم عدسات ARRI Signature Prime', 2),
    ('CRANE-JIB-30',      'equipment', 'Camera crane (30 ft jib)',             'رافعة كاميرا (ذراع 30 قدم)',     1),
    ('STEADICAM',         'equipment', 'Steadicam rig',                        'حامل ستيدي كام',                 1),
    ('DRONE-INSPIRE-3',   'equipment', 'DJI Inspire 3 drone',                  'طائرة درون DJI Inspire 3',       1),
    ('LIGHT-SKYPANEL',    'equipment', 'ARRI SkyPanel lighting kit',           'طقم إضاءة ARRI SkyPanel',        4),
    ('CREW-DRONE-PILOT',  'crew',      'Licensed drone pilot',                 'طيار درون مرخّص',                1),
    ('CREW-STEADICAM-OP', 'crew',      'Steadicam operator',                   'مشغّل ستيدي كام',                2),
    ('LOC-TURAIF',        'location',  'Al-Turaif district exterior (Diriyah)', 'حي الطريف (الدرعية) - تصوير خارجي', 1);

-- Switches a manager can flip with one SQL line, no restart needed.
CREATE TABLE app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO app_settings (key, value) VALUES
    ('odoo_sync', 'off'),                 -- 'on' = also write approved bookings into Odoo
    ('minutes_saved_per_request', '6');   -- assumption used for the "time saved" estimate in the weekly report

-- One row per incoming email. The primary key on message_id is the duplicate guard:
-- if the same email is delivered twice, the second insert does nothing
-- (unless the first run failed: then the repeat gets a fresh try).
-- The extracted fields are copied here too, so the clash check can see requests
-- still waiting for the manager, and the KPIs can be counted with plain SQL.
CREATE TABLE email_log (
    message_id    TEXT PRIMARY KEY,
    mailpit_id    TEXT,
    from_address  TEXT,
    subject       TEXT,
    status        TEXT NOT NULL DEFAULT 'received',  -- received | approved | rejected | expired | invalid_click | needs_info | ignored | failed
                                                      -- (a cancelled booking keeps 'approved'; see bookings.cancelled_at)
    execution_id  TEXT,                               -- the n8n run handling it, so the error workflow can mark it failed
    route         TEXT,                               -- ready | needs_info | not_booking (set after the AI check)
    language      TEXT,                               -- ar | en, from the email text (code, not AI)
    resource_code TEXT REFERENCES resources (code),
    quantity      INTEGER,
    start_date    DATE,
    end_date      DATE,
    production    TEXT,
    clash         BOOLEAN NOT NULL DEFAULT false,     -- the clash check found a conflict
    received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at    TIMESTAMPTZ,                        -- when the manager clicked (or it expired)
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Approved bookings only. UNIQUE(message_id) means one email can never become two bookings.
CREATE TABLE bookings (
    id              SERIAL PRIMARY KEY,
    message_id      TEXT NOT NULL UNIQUE REFERENCES email_log (message_id),
    request_type    TEXT NOT NULL,          -- studio | equipment | crew | location | other
    resource_code   TEXT REFERENCES resources (code),   -- empty when the item is not in the catalogue
    item            TEXT NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 1,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    production      TEXT NOT NULL,
    requester_name  TEXT,
    requester_email TEXT NOT NULL,
    language        TEXT,
    notes           TEXT,
    had_clash       BOOLEAN NOT NULL DEFAULT false,      -- approved even though the clash check warned
    odoo_sync       TEXT NOT NULL DEFAULT 'not_sent',    -- not_sent | skipped_no_target | synced | failed | rolled_back
    odoo_activity_id INTEGER,
    odoo_error      TEXT,
    approved_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    cancelled_at    TIMESTAMPTZ,                         -- set by scripts/cancel_booking.py; a cancelled
    cancel_reason   TEXT                                 -- booking no longer counts in the clash check
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

-- One row per successful Claude call: tokens and cost, so we know what each booking costs.
-- A call that fails (Claude stopped early, bad JSON) goes to workflow_errors instead.
CREATE TABLE ai_usage (
    id            SERIAL PRIMARY KEY,
    message_id    TEXT,
    model         TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd      NUMERIC(12, 8) NOT NULL,
    route         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Filled by the separate "Booking errors" workflow whenever a workflow fails.
CREATE TABLE workflow_errors (
    id            SERIAL PRIMARY KEY,
    workflow_name TEXT,
    execution_id  TEXT,
    failed_node   TEXT,
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Every weekly summary that was sent, with the numbers it showed.
CREATE TABLE report_log (
    id         SERIAL PRIMARY KEY,
    sent_to    TEXT NOT NULL,
    kpis       JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The KPIs for the last 7 days, in one row. The weekly email and show_results.py both read this,
-- so the numbers in the report and on screen always come from the same query.
-- Two windows, on purpose:
--   request KPIs (how many came in, how many were complete, clashes, time saved) count emails
--   RECEIVED in the last 7 days;
--   decision KPIs (approved, rejected, expired, time to decision) count decisions MADE in the
--   last 7 days, so a request that arrived 8 days ago and was decided this week still counts.
-- An invalid_click (an edited or mangled link) is not a manager decision: it is counted on its
-- own and left out of the approval rate.
CREATE VIEW kpi_last_7_days AS
WITH received AS (
    SELECT
        count(*)                                                    AS emails_handled,
        count(*) FILTER (WHERE route IN ('ready', 'needs_info'))    AS booking_requests,
        count(*) FILTER (WHERE route = 'ready')                     AS auto_routed,
        count(*) FILTER (WHERE route = 'needs_info')                AS needs_info,
        count(*) FILTER (WHERE route = 'not_booking')               AS not_booking,
        count(*) FILTER (WHERE clash)                               AS clashes_flagged
    FROM email_log WHERE received_at >= now() - interval '7 days'
), decided AS (
    SELECT
        count(*) FILTER (WHERE status = 'approved')                 AS approved,
        count(*) FILTER (WHERE status = 'rejected')                 AS rejected,
        count(*) FILTER (WHERE status = 'expired')                  AS expired,
        count(*) FILTER (WHERE status = 'invalid_click')            AS invalid_clicks,
        avg(extract(epoch FROM decided_at - received_at) / 60)
            FILTER (WHERE status IN ('approved', 'rejected'))      AS avg_minutes_to_decision,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM decided_at - received_at) / 60)
            FILTER (WHERE status IN ('approved', 'rejected'))      AS median_minutes_to_decision
    FROM email_log WHERE decided_at >= now() - interval '7 days'
), ai AS (
    SELECT count(*) AS ai_calls, coalesce(sum(cost_usd), 0) AS ai_cost_usd
    FROM ai_usage WHERE created_at >= now() - interval '7 days'
)
SELECT
    r.emails_handled, r.booking_requests, r.auto_routed, r.needs_info, r.not_booking,
    d.approved, d.rejected, d.expired, d.invalid_clicks,
    (SELECT count(*) FROM email_log WHERE status = 'received' AND route = 'ready') AS waiting_for_manager,
    r.clashes_flagged,
    (SELECT count(*) FROM bookings WHERE cancelled_at >= now() - interval '7 days') AS cancelled,
    round(100.0 * r.auto_routed / NULLIF(r.booking_requests, 0), 1)           AS auto_routed_pct,
    round(100.0 * d.approved / NULLIF(d.approved + d.rejected + d.expired, 0), 1) AS approval_rate_pct,
    round(d.avg_minutes_to_decision::numeric, 1)                              AS avg_minutes_to_decision,
    round(d.median_minutes_to_decision::numeric, 1)                           AS median_minutes_to_decision,
    a.ai_calls,
    round(a.ai_cost_usd, 6)                                                   AS ai_cost_usd,
    -- This week's AI spend divided by this week's approvals: close enough for a weekly trend.
    round(a.ai_cost_usd / NULLIF(d.approved, 0), 6)                           AS ai_cost_per_booking_usd,
    -- Only complete requests save the desk's time; needs_info ones still need a person.
    r.auto_routed * (SELECT value::int FROM app_settings WHERE key = 'minutes_saved_per_request')
                                                                              AS est_minutes_saved,
    (SELECT count(*) FROM workflow_errors WHERE created_at >= now() - interval '7 days') AS errors
FROM received r, decided d, ai a;
