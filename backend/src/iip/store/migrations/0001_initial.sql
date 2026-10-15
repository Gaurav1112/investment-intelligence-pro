-- 0001_initial: core schema (system-design.md §3). All decimal values are TEXT (no float storage).
CREATE TABLE sources (
    source_id      TEXT PRIMARY KEY,
    owner          TEXT NOT NULL,
    official       INTEGER NOT NULL CHECK (official IN (0, 1)),
    url            TEXT NOT NULL,
    terms_url      TEXT,
    licence_note   TEXT NOT NULL,
    mode           TEXT NOT NULL CHECK (mode IN ('live', 'manual', 'disabled')),
    freshness_slo_days INTEGER NOT NULL
);

CREATE TABLE ingestion_runs (
    run_id         TEXT PRIMARY KEY,
    source_id      TEXT NOT NULL REFERENCES sources(source_id),
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    status         TEXT NOT NULL CHECK (status IN ('running', 'ok', 'partial', 'failed', 'held')),
    rows_ok        INTEGER NOT NULL DEFAULT 0,
    rows_rejected  INTEGER NOT NULL DEFAULT 0,
    raw_sha256     TEXT,
    error          TEXT
);

CREATE TABLE issuers (
    issuer_id      TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    issuer_type    TEXT NOT NULL CHECK (issuer_type IN ('sovereign','state','bank','small_finance_bank','nbfc','hfc','psu','corporate','amc','post_office'))
);

CREATE TABLE instruments (
    instrument_id  TEXT PRIMARY KEY,
    kind           TEXT NOT NULL CHECK (kind IN ('mf_scheme','tbill','gsec','sdl','corp_bond','fd','small_savings','cash')),
    name           TEXT NOT NULL,
    issuer_id      TEXT REFERENCES issuers(issuer_id),
    isin           TEXT,
    amfi_code      TEXT UNIQUE,
    currency       TEXT NOT NULL DEFAULT 'INR' CHECK (currency = 'INR'),
    origin         TEXT NOT NULL CHECK (origin IN ('source','manual','fixture')),
    created_at     TEXT NOT NULL
);

CREATE TABLE mf_schemes (
    instrument_id  TEXT PRIMARY KEY REFERENCES instruments(instrument_id) ON DELETE CASCADE,
    amc            TEXT NOT NULL,
    category_raw   TEXT NOT NULL,
    sebi_category  TEXT,
    plan           TEXT CHECK (plan IN ('direct','regular') OR plan IS NULL),
    option_type    TEXT,
    benchmark      TEXT,
    riskometer     TEXT,
    prc            TEXT,
    exit_load_json TEXT,
    expense_ratio  TEXT,
    expense_ratio_kind TEXT CHECK (expense_ratio_kind IN ('TER','BER') OR expense_ratio_kind IS NULL),
    expense_as_of  TEXT
);

CREATE TABLE bond_terms (
    instrument_id  TEXT PRIMARY KEY REFERENCES instruments(instrument_id) ON DELETE CASCADE,
    face_value     TEXT NOT NULL,
    coupon_rate    TEXT NOT NULL,
    coupon_freq    INTEGER NOT NULL CHECK (coupon_freq IN (0, 1, 2, 4, 12)),
    issue_date     TEXT,
    maturity_date  TEXT NOT NULL,
    daycount       TEXT NOT NULL,
    listed         INTEGER NOT NULL DEFAULT 1,
    call_schedule_json TEXT,
    credit_rating  TEXT,
    rating_agency  TEXT,
    rating_date    TEXT
);

CREATE TABLE deposit_terms (
    instrument_id  TEXT PRIMARY KEY REFERENCES instruments(instrument_id) ON DELETE CASCADE,
    institution    TEXT NOT NULL,
    rate           TEXT NOT NULL,
    compounding    TEXT NOT NULL,
    tenure_days    INTEGER NOT NULL,
    premature_penalty TEXT,
    dicgc_eligible INTEGER NOT NULL CHECK (dicgc_eligible IN (0, 1)),
    rate_as_of     TEXT NOT NULL,
    citation_url   TEXT
);

CREATE TABLE observations (
    obs_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id      TEXT NOT NULL,
    kind           TEXT NOT NULL CHECK (kind IN ('nav','price','yield','rate','cpi','rating','expense','index')),
    value          TEXT NOT NULL,
    unit           TEXT NOT NULL,
    currency       TEXT,
    observation_date TEXT NOT NULL,
    publication_time TEXT,
    retrieved_at   TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    source_url     TEXT NOT NULL,
    quality_status TEXT NOT NULL CHECK (quality_status IN ('ok','stale','suspect','rejected','fixture','manual')),
    convention     TEXT,
    raw_sha256     TEXT NOT NULL,
    ingestion_run_id TEXT,
    superseded_by  INTEGER REFERENCES observations(obs_id)
);
CREATE INDEX ix_obs_series_date ON observations(series_id, observation_date);
-- Exactly one current (non-superseded) observation per series/date/source.
CREATE UNIQUE INDEX ux_obs_current ON observations(series_id, observation_date, source_id) WHERE superseded_by IS NULL;

CREATE TABLE profiles (
    profile_id     TEXT PRIMARY KEY,
    data_json      TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE portfolios (
    portfolio_id   TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    nature         TEXT NOT NULL CHECK (nature IN ('actual','hypothetical')),
    created_at     TEXT NOT NULL
);

CREATE TABLE transactions (
    txn_id         TEXT PRIMARY KEY,
    portfolio_id   TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
    instrument_id  TEXT NOT NULL REFERENCES instruments(instrument_id),
    txn_date       TEXT NOT NULL,
    txn_type       TEXT NOT NULL CHECK (txn_type IN ('buy','sell','dividend','coupon','maturity','fee')),
    units          TEXT,
    amount         TEXT NOT NULL,
    price          TEXT,
    source         TEXT NOT NULL CHECK (source IN ('manual','csv_import')),
    import_batch   TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE watchlist (
    instrument_id  TEXT PRIMARY KEY REFERENCES instruments(instrument_id) ON DELETE CASCADE,
    note           TEXT,
    added_at       TEXT NOT NULL
);

CREATE TABLE alerts (
    alert_id       TEXT PRIMARY KEY,
    kind           TEXT NOT NULL,
    severity       TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
    subject_id     TEXT,
    message        TEXT NOT NULL,
    source_id      TEXT,
    observation_ref TEXT,
    created_at     TEXT NOT NULL,
    dedupe_key     TEXT NOT NULL UNIQUE,
    acknowledged_at TEXT
);

CREATE TABLE runs (
    run_id         TEXT PRIMARY KEY,
    kind           TEXT NOT NULL,
    input_hash     TEXT NOT NULL,
    versions_json  TEXT NOT NULL,
    params_json    TEXT NOT NULL,
    output_hash    TEXT NOT NULL,
    output_json    TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE audit_events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    at             TEXT NOT NULL,
    action         TEXT NOT NULL,
    subject        TEXT,
    detail         TEXT
);

CREATE TABLE settings (
    key            TEXT PRIMARY KEY,
    value_json     TEXT NOT NULL
);
