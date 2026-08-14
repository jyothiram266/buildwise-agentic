-- ===========================================================================
-- BuildWise Agentic AI — canonical schema (architecture Section 8 + governance)
--
-- Two things in here are load-bearing rather than cosmetic:
--   1. chunks.audience_scope is a role array with a GIN index, because the ACL
--      filter must be a SQL predicate (design rule #2). If this becomes a
--      post-query filter in Python, the rule is broken.
--   2. agent_trace is append-only, enforced by trigger. Audit you can edit is
--      not audit.
-- ===========================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- pgvector is preferred but optional: some managed Postgres instances do not
-- allow it. `scripts/migrate.py` records which mode was applied in system_meta
-- and the retrieval layer adapts.
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pgvector unavailable; falling back to array embeddings';
END
$$;

CREATE TABLE IF NOT EXISTS system_meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Property inventory
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    project_id          TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    city                TEXT NOT NULL,
    locality            TEXT,
    type                TEXT NOT NULL CHECK (type IN ('apartments', 'villas', 'commercial')),
    launch_date         DATE,
    planned_possession  DATE,
    status              TEXT NOT NULL CHECK (status IN ('pre_launch', 'under_construction', 'ready', 'completed')),
    rera_id             TEXT,
    amenities           TEXT[] NOT NULL DEFAULT '{}',
    description         TEXT
);

CREATE TABLE IF NOT EXISTS towers (
    tower_id      TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    floors        INT NOT NULL,
    units_total   INT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'under_construction',
    planned_possession DATE,
    -- A revised date only becomes disclosable when revised_approved is true.
    -- The customer-facing construction path reads this flag, never the date alone
    -- (PRD FR-CON-6). Seed data deliberately contains one of each.
    revised_possession DATE,
    revised_approved   BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_towers_project ON towers(project_id);

CREATE TABLE IF NOT EXISTS units (
    unit_id       TEXT PRIMARY KEY,
    tower_id      TEXT NOT NULL REFERENCES towers(tower_id) ON DELETE CASCADE,
    project_id    TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    config        TEXT NOT NULL,
    carpet_area   INT NOT NULL,
    floor         INT NOT NULL,
    facing        TEXT,
    status        TEXT NOT NULL CHECK (status IN ('available', 'held', 'booked', 'sold')),
    price_ref     TEXT NOT NULL,
    base_price    BIGINT NOT NULL,
    all_in_price  BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_units_lookup ON units(project_id, config, status);
CREATE INDEX IF NOT EXISTS idx_units_price ON units(all_in_price);

-- ---------------------------------------------------------------------------
-- Customers and bookings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
    customer_id   TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    contact_email TEXT,
    contact_phone TEXT,
    kyc_status    TEXT NOT NULL CHECK (kyc_status IN ('pending', 'submitted', 'verified')),
    city          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bookings (
    booking_id        TEXT PRIMARY KEY,
    customer_id       TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    unit_id           TEXT NOT NULL REFERENCES units(unit_id),
    project_id        TEXT NOT NULL REFERENCES projects(project_id),
    stage             TEXT NOT NULL CHECK (stage IN ('kyc_pending','booked','agreement','registered','loan_disbursed','possession_taken')),
    agreement_status  TEXT NOT NULL DEFAULT 'not_started',
    booked_on         DATE,
    possession_date   DATE,
    possession_date_approved BOOLEAN NOT NULL DEFAULT TRUE,
    total_value       BIGINT NOT NULL,
    sales_owner       TEXT
);
CREATE INDEX IF NOT EXISTS idx_bookings_customer ON bookings(customer_id);
CREATE INDEX IF NOT EXISTS idx_bookings_project ON bookings(project_id);

CREATE TABLE IF NOT EXISTS payment_milestones (
    milestone_id  TEXT PRIMARY KEY,
    booking_id    TEXT NOT NULL REFERENCES bookings(booking_id) ON DELETE CASCADE,
    label         TEXT NOT NULL,
    amount        BIGINT NOT NULL,
    due_date      DATE NOT NULL,
    paid_on       DATE,
    status        TEXT NOT NULL CHECK (status IN ('paid','due','overdue')),
    receipt_ref   TEXT,
    seq           INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pay_booking ON payment_milestones(booking_id);

CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,
    booking_id    TEXT NOT NULL REFERENCES bookings(booking_id) ON DELETE CASCADE,
    type          TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('submitted','pending','expired')),
    submitted_on  DATE,
    expires_on    DATE,
    stage         TEXT NOT NULL,
    notes         TEXT
);
CREATE INDEX IF NOT EXISTS idx_docs_booking ON documents(booking_id);

-- ---------------------------------------------------------------------------
-- Construction progress
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS milestones (
    milestone_id   TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    tower_id       TEXT REFERENCES towers(tower_id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    seq            INT NOT NULL DEFAULT 0,
    planned_date   DATE NOT NULL,
    actual_date    DATE,
    pct_complete   NUMERIC(5,2) NOT NULL DEFAULT 0,
    status         TEXT NOT NULL CHECK (status IN ('completed','in_progress','pending'))
);
CREATE INDEX IF NOT EXISTS idx_ms_tower ON milestones(tower_id);

CREATE TABLE IF NOT EXISTS site_reports (
    report_id         TEXT PRIMARY KEY,
    project_id        TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    tower_id          TEXT REFERENCES towers(tower_id) ON DELETE SET NULL,
    week_of           DATE NOT NULL,
    author            TEXT NOT NULL,
    raw_note          TEXT NOT NULL,
    internal_summary  TEXT,
    customer_summary  TEXT,
    approval_status   TEXT NOT NULL DEFAULT 'draft' CHECK (approval_status IN ('draft','approved','rejected')),
    contains_injection_probe BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_reports_project ON site_reports(project_id, week_of DESC);

CREATE TABLE IF NOT EXISTS vendors (
    vendor_id     TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    trade         TEXT NOT NULL,
    contact       TEXT
);

CREATE TABLE IF NOT EXISTS work_packages (
    work_package_id TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    tower_id        TEXT REFERENCES towers(tower_id) ON DELETE SET NULL,
    vendor_id       TEXT NOT NULL REFERENCES vendors(vendor_id),
    scope           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS blockers (
    blocker_id           TEXT PRIMARY KEY,
    project_id           TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    vendor_id            TEXT REFERENCES vendors(vendor_id),
    work_package_id      TEXT REFERENCES work_packages(work_package_id),
    category             TEXT NOT NULL,
    description          TEXT NOT NULL,
    impacted_milestones  TEXT[] NOT NULL DEFAULT '{}',
    severity             TEXT NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    raised_on            DATE NOT NULL,
    resolved_on          DATE,
    raised_by            TEXT
);
CREATE INDEX IF NOT EXISTS idx_blockers_project ON blockers(project_id);

-- ---------------------------------------------------------------------------
-- Operations: tickets and leads
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id      TEXT PRIMARY KEY,
    unit_id        TEXT REFERENCES units(unit_id),
    project_id     TEXT REFERENCES projects(project_id),
    raised_by      TEXT NOT NULL,
    category       TEXT NOT NULL,
    priority       TEXT NOT NULL CHECK (priority IN ('P1','P2','P3','P4')),
    complaint_text TEXT NOT NULL,
    assigned_team  TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('open','assigned','in_progress','resolved','closed')),
    warranty_flag  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    sla_due        TIMESTAMPTZ NOT NULL,
    resolved_at    TIMESTAMPTZ,
    case_id        TEXT
);
CREATE INDEX IF NOT EXISTS idx_tickets_unit ON tickets(unit_id);
CREATE INDEX IF NOT EXISTS idx_tickets_sla ON tickets(status, sla_due);

CREATE TABLE IF NOT EXISTS ticket_events (
    event_id    BIGSERIAL PRIMARY KEY,
    ticket_id   TEXT NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    detail      TEXT,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS leads (
    lead_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    contact_email   TEXT,
    contact_phone   TEXT,
    interest_config TEXT,
    budget_max      BIGINT,
    city            TEXT,
    project_interest TEXT,
    score           INT NOT NULL DEFAULT 0,
    stage           TEXT NOT NULL DEFAULT 'new',
    site_visit_done BOOLEAN NOT NULL DEFAULT FALSE,
    last_contact    DATE,
    next_action     TEXT,
    next_action_due DATE,
    owner           TEXT,
    source          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_leads_owner ON leads(owner, next_action_due);

-- ---------------------------------------------------------------------------
-- Cases and governance
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cases (
    case_id           TEXT PRIMARY KEY,
    actor_id          TEXT NOT NULL,
    role              TEXT NOT NULL,
    channel           TEXT NOT NULL,
    intent            TEXT,
    secondary_intent  TEXT,
    entities          JSONB NOT NULL DEFAULT '{}',
    sentiment         TEXT,
    risk_tier         INT,
    status            TEXT NOT NULL DEFAULT 'open',
    masked_input      TEXT NOT NULL,
    response_mode     TEXT,
    response_text     TEXT,
    response_citations JSONB NOT NULL DEFAULT '[]',
    findings          JSONB NOT NULL DEFAULT '[]',
    confidence        NUMERIC(4,3),
    degraded          BOOLEAN NOT NULL DEFAULT FALSE,
    cost_tokens       INT NOT NULL DEFAULT 0,
    cost_usd          NUMERIC(10,5) NOT NULL DEFAULT 0,
    latency_ms        INT NOT NULL DEFAULT 0,
    thread_of         TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    first_response_at TIMESTAMPTZ,
    closed_at         TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_cases_actor ON cases(actor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status, risk_tier);
CREATE INDEX IF NOT EXISTS idx_cases_created ON cases(created_at DESC);

CREATE TABLE IF NOT EXISTS agent_trace (
    trace_id             TEXT PRIMARY KEY,
    case_id              TEXT NOT NULL,
    seq                  BIGSERIAL,
    agent                TEXT NOT NULL,
    prompt_version       TEXT,
    policy_version       TEXT,
    model                TEXT,
    inputs_hash          TEXT NOT NULL,
    retrieved_source_ids TEXT[] NOT NULL DEFAULT '{}',
    output               JSONB NOT NULL DEFAULT '{}',
    confidence           NUMERIC(4,3),
    risk_tier            INT,
    decision             TEXT,
    human_actor          TEXT,
    latency_ms           INT NOT NULL DEFAULT 0,
    tokens               INT NOT NULL DEFAULT 0,
    cost_usd             NUMERIC(10,5) NOT NULL DEFAULT 0,
    ts                   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_trace_case ON agent_trace(case_id, seq);

-- Append-only enforcement. Revoking privileges is not enough when the app owns
-- the table, so the guarantee is a trigger that refuses the operation outright.
CREATE OR REPLACE FUNCTION agent_trace_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'agent_trace is append-only: % is not permitted', TG_OP;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_agent_trace_no_update ON agent_trace;
CREATE TRIGGER trg_agent_trace_no_update
    BEFORE UPDATE OR DELETE ON agent_trace
    FOR EACH ROW EXECUTE FUNCTION agent_trace_append_only();

CREATE TABLE IF NOT EXISTS escalations (
    esc_id       TEXT PRIMARY KEY,
    case_id      TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    type         TEXT NOT NULL,
    owner_team   TEXT NOT NULL,
    sla_hours    INT NOT NULL,
    sla_due      TIMESTAMPTZ NOT NULL,
    brief        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved')),
    assigned_to  TEXT,
    resolution   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_esc_status ON escalations(status, sla_due);

CREATE TABLE IF NOT EXISTS review_queue (
    review_id         TEXT PRIMARY KEY,
    case_id           TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    risk_tier         INT NOT NULL,
    audience          TEXT NOT NULL,
    original_request  TEXT NOT NULL,
    reasoning_summary TEXT NOT NULL,
    citations         JSONB NOT NULL DEFAULT '[]',
    proposed_response TEXT NOT NULL,
    confidence        NUMERIC(4,3) NOT NULL,
    sla_due           TIMESTAMPTZ,
    status            TEXT NOT NULL DEFAULT 'pending',
    action            TEXT,
    acted_by          TEXT,
    acted_at          TIMESTAMPTZ,
    rejection_reason  TEXT,
    edited_text       TEXT,
    assigned_to       TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_queue(status, sla_due);

CREATE TABLE IF NOT EXISTS approval_tokens (
    token       TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    action_kind TEXT NOT NULL,
    risk_tier   INT NOT NULL,
    consumed    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS team_notifications (
    notification_id BIGSERIAL PRIMARY KEY,
    case_id         TEXT,
    team            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    message         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kb_gaps (
    gap_id      BIGSERIAL PRIMARY KEY,
    case_id     TEXT,
    query       TEXT NOT NULL,
    collections TEXT[] NOT NULL DEFAULT '{}',
    role        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Retrieval: chunks with ACL and freshness metadata
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents_corpus (
    source_id      TEXT PRIMARY KEY,
    source_name    TEXT NOT NULL,
    collection     TEXT NOT NULL,
    effective_date DATE,
    freshness_days INT NOT NULL DEFAULT 365,
    audience_scope TEXT[] NOT NULL DEFAULT '{}',
    project_id     TEXT,
    path           TEXT NOT NULL,
    content_hash   TEXT NOT NULL,
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id        TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL REFERENCES documents_corpus(source_id) ON DELETE CASCADE,
    source_name     TEXT NOT NULL,
    collection      TEXT NOT NULL,
    section_heading TEXT,
    chunk_index     INT NOT NULL DEFAULT 0,
    content         TEXT NOT NULL,
    effective_date  DATE,
    freshness_days  INT NOT NULL DEFAULT 365,
    audience_scope  TEXT[] NOT NULL DEFAULT '{}',
    project_id      TEXT,
    token_estimate  INT NOT NULL DEFAULT 0,
    flagged_injection BOOLEAN NOT NULL DEFAULT FALSE,
    content_hash    TEXT NOT NULL,
    embedding_arr   DOUBLE PRECISION[],
    tsv             TSVECTOR
);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
CREATE INDEX IF NOT EXISTS idx_chunks_audience ON chunks USING GIN (audience_scope);
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS idx_chunks_collection ON chunks(collection);

-- Add the pgvector column only when the extension actually loaded.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        BEGIN
            ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding vector(384);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'could not add vector column: %', SQLERRM;
        END;
        INSERT INTO system_meta(key, value) VALUES ('dense_mode', 'pgvector')
            ON CONFLICT (key) DO UPDATE SET value = 'pgvector', updated_at = now();
    ELSE
        INSERT INTO system_meta(key, value) VALUES ('dense_mode', 'array')
            ON CONFLICT (key) DO UPDATE SET value = 'array', updated_at = now();
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS conversation_turns (
    turn_id     BIGSERIAL PRIMARY KEY,
    actor_id    TEXT NOT NULL,
    case_id     TEXT NOT NULL,
    role        TEXT NOT NULL,
    text        TEXT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_turns_actor ON conversation_turns(actor_id, ts DESC);
