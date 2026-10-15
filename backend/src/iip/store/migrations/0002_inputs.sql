-- 0002_inputs: user-entered, cited data inputs that unblock analysis (Track 1).
-- CPI and the 91-day T-bill risk-free series live in `observations` (kinds 'cpi' and 'yield'); this migration adds
-- the per-scheme factsheet facts and bank FD card-rate tables. Rows are append-only: corrections are new rows and the
-- latest one is used. All decimal values are TEXT (no float storage).

CREATE TABLE fund_facts (
    fact_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id       TEXT NOT NULL REFERENCES instruments(instrument_id) ON DELETE CASCADE,
    as_of_month         TEXT NOT NULL CHECK (as_of_month GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]'),
    as_of_date          TEXT NOT NULL,  -- last calendar day of as_of_month (the portfolio date)
    modified_duration   TEXT,           -- years
    macaulay_duration   TEXT,           -- years
    ytm                 TEXT,           -- portfolio yield to maturity, fraction, as published
    average_maturity_years TEXT,        -- years
    expense_ratio       TEXT,           -- fraction
    expense_ratio_kind  TEXT CHECK (expense_ratio_kind IN ('TER','BER') OR expense_ratio_kind IS NULL),
    lowest_rating       TEXT,           -- lowest credit rating held, as published
    share_below_aaa     TEXT,           -- fraction of the portfolio rated below AAA
    share_sovereign_cash TEXT,          -- fraction in sovereign paper and cash/equivalents
    citation_url        TEXT NOT NULL CHECK (citation_url LIKE 'https://%'),
    citation_note       TEXT NOT NULL DEFAULT '',
    verified_on         TEXT NOT NULL,  -- date the user read the factsheet (never before as_of_date)
    entered_at          TEXT NOT NULL,
    CHECK (expense_ratio IS NULL OR expense_ratio_kind IS NOT NULL),
    CHECK (verified_on >= as_of_date)
);
CREATE INDEX ix_fund_facts_latest ON fund_facts(instrument_id, as_of_date, entered_at);

CREATE TABLE fd_card_rate_tables (
    table_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_key     TEXT NOT NULL,  -- slug of the institution name, matched to deposit_terms.institution
    institution         TEXT NOT NULL,
    as_of               TEXT NOT NULL,  -- date the card rates applied from (citation date)
    premature_rate_basis TEXT NOT NULL CHECK (premature_rate_basis IN ('period_card','min(booked,period_card)')),
    citation_url        TEXT NOT NULL CHECK (citation_url LIKE 'https://%'),
    citation_note       TEXT NOT NULL DEFAULT '',
    entered_at          TEXT NOT NULL
);
CREATE INDEX ix_fd_card_rate_tables_latest ON fd_card_rate_tables(institution_key, as_of, entered_at);

CREATE TABLE fd_card_rate_buckets (
    table_id            INTEGER NOT NULL REFERENCES fd_card_rate_tables(table_id) ON DELETE CASCADE,
    min_days            INTEGER NOT NULL CHECK (min_days >= 1),
    max_days            INTEGER NOT NULL,
    rate                TEXT NOT NULL,  -- fraction p.a., card rate for deposits of this tenure
    PRIMARY KEY (table_id, min_days),
    CHECK (max_days >= min_days)
);
