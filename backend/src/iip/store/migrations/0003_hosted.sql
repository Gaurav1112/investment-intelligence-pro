-- 0003_hosted: state that must outlive one process (ADR-0013). Serverless instances share no memory, so in hosted
-- mode sessions, rate limits, refresh claims, the single-backfill lease and resumable-job progress live in the
-- database. Every claim is ONE conditional statement (atomic in SQLite/libSQL; no interactive transaction needed).
-- Local mode creates these tables too but keeps its in-memory equivalents, except import_snapshots (both modes may
-- read it; only hosted mode writes it).

CREATE TABLE web_sessions (
    id_hash     TEXT PRIMARY KEY,  -- SHA-256 of the session cookie value (the raw value is never stored)
    csrf        TEXT NOT NULL,
    created     REAL NOT NULL,     -- epoch seconds
    last_seen   REAL NOT NULL
);

CREATE TABLE rate_hits (
    key         TEXT NOT NULL,
    at          REAL NOT NULL
);
CREATE INDEX ix_rate_hits ON rate_hits(key, at);

CREATE TABLE refresh_claims (
    source_key  TEXT PRIMARY KEY,  -- e.g. amfi.navall or amfi.navhistory:<scheme code>
    claimed_at  REAL NOT NULL
);

CREATE TABLE leases (
    name        TEXT PRIMARY KEY,
    holder      TEXT NOT NULL,
    expires_at  REAL NOT NULL      -- a killed function never releases, so the lease lapses instead
);

CREATE TABLE job_progress (
    job_key     TEXT PRIMARY KEY,  -- navall | backfill:<scheme code>
    state_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Hosted substitute for the pre-import FILE backup (reliability-design §7.1): the portfolio's transactions as they
-- were just before an import was applied. User data: erased with everything else.
CREATE TABLE import_snapshots (
    snapshot_id   TEXT PRIMARY KEY,
    portfolio_id  TEXT NOT NULL,
    tag           TEXT NOT NULL,
    taken_at      TEXT NOT NULL,
    row_count     INTEGER NOT NULL,
    rows_json     TEXT NOT NULL
);
