-- 0004_risk_signals: goals, the risk profile and tax context, policy versions, the decision log, the month-end
-- series grid, cron claims, content-addressed signal snapshots, the ping outbox, the signal registry with role
-- bindings, the append-only backtest trial log, backtest evidence bundles, the daily shadow ledger (rule
-- evaluations), outcomes and vendor restatements (PLAN.md wave 2, package A10. design-risk-first.md 2.3, 6, 8, 9
-- with the grafts in design-judgement.md 2.1).
--
-- Conventions (as 0001-0003): every decimal is TEXT (never a float), every timestamp is ISO-8601 TEXT stamped by
-- the service layer (no clock in SQL), and no market values or scheme codes are seeded here.
--
-- Append-only ledgers are enforced in SQL with BEFORE triggers that RAISE(ABORT): no UPDATE of frozen columns, no
-- DELETE, and no INSERT over an existing key. The last one is needed because INSERT OR REPLACE deletes the old row
-- WITHOUT firing delete triggers (SQLite fires them only with recursive_triggers on). It also means an append-only
-- insert must not rely on ON CONFLICT DO NOTHING (the BEFORE INSERT trigger fires first): the repositories use
-- INSERT … SELECT … WHERE NOT EXISTS instead. The one sanctioned way to delete
-- ledger rows is the user's own "erase all my data" (SEC-81): iip.store.ledger.erase_user_rows inserts the single
-- row of ledger_erase_gate inside the erase transaction, deletes, and removes the row again before COMMIT. The gate
-- guards against accidental mutation by application code. It is not a defence against someone who can run
-- arbitrary SQL (they could drop a trigger).
--
-- Trigger bodies hold exactly one statement and no CASE expression: the migration splitter (store/db.py) keeps a
-- CREATE TRIGGER together up to the first segment ending in END.
-- Every statement must work on SQLite and libSQL (tested on both drivers).

CREATE TABLE ledger_erase_gate (
    id          INTEGER PRIMARY KEY CHECK (id = 1)
);

-- ---------------------------------------------------------------------------------------------- goals and profile

CREATE TABLE goals (
    goal_id             TEXT PRIMARY KEY,
    name                TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    target_amount       TEXT,           -- INR, Decimal string, NULL while the user has not set it
    target_date         TEXT CHECK (target_date IS NULL OR target_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    priority            INTEGER NOT NULL CHECK (priority >= 1),
    objective           TEXT CHECK (objective IN ('A','B','C','D','E') OR objective IS NULL),
    loss_budget_inr     TEXT,           -- B_g: largest fall in INR the user would sit through without selling
    recovery_months     INTEGER CHECK (recovery_months IS NULL OR recovery_months >= 0),  -- T_g
    h_safe_years        TEXT,           -- PARAMETER set by the user (goal-date safety window), Decimal string
    policy_version_id   INTEGER REFERENCES policy_versions(policy_version_id),
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- A holding (instrument + folio, '' when the source has no folio) split across goals by fraction (0 < f <= 1).
-- The repository rejects a holding whose fractions add up to more than 1. Unmapped = the "Unassigned" goal.
CREATE TABLE holding_goal_map (
    instrument_id       TEXT NOT NULL REFERENCES instruments(instrument_id) ON DELETE CASCADE,
    folio               TEXT NOT NULL DEFAULT '',
    goal_id             TEXT NOT NULL REFERENCES goals(goal_id) ON DELETE CASCADE,
    fraction            TEXT NOT NULL,  -- Decimal string in (0, 1]
    mapped_at           TEXT NOT NULL,
    PRIMARY KEY (instrument_id, folio, goal_id)
);
CREATE INDEX ix_holding_goal_map_goal ON holding_goal_map(goal_id);

-- One row: the inputs of the L1 emergency-fund gate. NULL = not provided, and the gate abstains.
CREATE TABLE risk_profile (
    profile_id                  INTEGER PRIMARY KEY CHECK (profile_id = 1),
    essential_monthly_expenses  TEXT,
    emergency_months            INTEGER CHECK (emergency_months IS NULL OR emergency_months BETWEEN 0 AND 60),
    savings_balance             TEXT,
    sweep_fd_balance            TEXT,
    set_at                      TEXT NOT NULL
);

-- Per financial year ('2026-27'). ltcg_used_assumed = 1 means "assume the exemption is already used" (the labelled,
-- conservative default) and then ltcg_used_inr must be NULL.
CREATE TABLE user_tax_context (
    fy                  TEXT PRIMARY KEY CHECK (fy GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
    regime              TEXT CHECK (regime IN ('new','old') OR regime IS NULL),
    slab_rate           TEXT,           -- fraction, Decimal string
    residency           TEXT CHECK (residency IN ('resident','non_resident') OR residency IS NULL),
    ltcg_used_inr       TEXT,
    ltcg_used_assumed   INTEGER NOT NULL DEFAULT 1 CHECK (ltcg_used_assumed IN (0, 1)),
    set_at              TEXT NOT NULL,
    CHECK (ltcg_used_assumed = 0 OR ltcg_used_inr IS NULL)
);

-- The user's targets, bands, limits and c_* parameters. Append-only: a change is a new version with its decision date.
CREATE TABLE policy_versions (
    policy_version_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_json         TEXT NOT NULL,  -- canonical JSON (sorted keys), Decimal values as strings
    policy_hash         TEXT NOT NULL UNIQUE,  -- sha256 of policy_json
    decided_at          TEXT NOT NULL,  -- the date the user made the decision
    created_at          TEXT NOT NULL
);
CREATE TRIGGER policy_versions_no_update BEFORE UPDATE ON policy_versions
BEGIN SELECT RAISE(ABORT, 'append-only constraint: policy_versions'); END;
CREATE TRIGGER policy_versions_no_replace BEFORE INSERT ON policy_versions
WHEN EXISTS (SELECT 1 FROM policy_versions WHERE policy_version_id = NEW.policy_version_id OR policy_hash = NEW.policy_hash)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: policy_versions row exists'); END;
CREATE TRIGGER policy_versions_no_delete BEFORE DELETE ON policy_versions
WHEN NOT EXISTS (SELECT 1 FROM ledger_erase_gate)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: policy_versions'); END;

-- "I did this" / "not now" / "disagree" per card. Append-only, except that a later CAS may confirm (1) or contradict
-- (0) a 'done' entry exactly once (cas_confirmed goes from NULL to a value, never back).
CREATE TABLE decisions_log (
    decision_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id             TEXT NOT NULL,
    snapshot_id         TEXT,
    goal_id             TEXT,           -- no FK: the record outlives a deleted goal
    decision            TEXT NOT NULL CHECK (decision IN ('done','not_now','disagree')),
    note                TEXT CHECK (note IS NULL OR length(note) <= 2000),
    decided_at          TEXT NOT NULL,
    cas_confirmed       INTEGER CHECK (cas_confirmed IN (0, 1) OR cas_confirmed IS NULL),
    cas_checked_at      TEXT,
    cas_import_ref      TEXT,
    CHECK ((cas_confirmed IS NULL) = (cas_checked_at IS NULL)),
    CHECK (cas_confirmed IS NULL OR decision = 'done')
);
CREATE INDEX ix_decisions_log_card ON decisions_log(card_id, decided_at);
CREATE TRIGGER decisions_log_no_update BEFORE UPDATE OF decision_id, card_id, snapshot_id, goal_id, decision, note,
    decided_at ON decisions_log
BEGIN SELECT RAISE(ABORT, 'append-only constraint: decisions_log'); END;
CREATE TRIGGER decisions_log_cas_once BEFORE UPDATE OF cas_confirmed, cas_checked_at, cas_import_ref ON decisions_log
WHEN OLD.cas_confirmed IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'append-only constraint: decisions_log cas_confirmed is set once'); END;
CREATE TRIGGER decisions_log_no_replace BEFORE INSERT ON decisions_log
WHEN EXISTS (SELECT 1 FROM decisions_log WHERE decision_id = NEW.decision_id)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: decisions_log row exists'); END;
CREATE TRIGGER decisions_log_no_delete BEFORE DELETE ON decisions_log
WHEN NOT EXISTS (SELECT 1 FROM ledger_erase_gate)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: decisions_log'); END;

-- ---------------------------------------------------------------------------------------------- market-derived data

-- Month-end NAV per scheme (refreshed by J3). Every value points at the observation it came from.
CREATE TABLE series_grid (
    instrument_id       TEXT NOT NULL REFERENCES instruments(instrument_id) ON DELETE CASCADE,
    month               TEXT NOT NULL CHECK (month GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]'),
    nav_date            TEXT NOT NULL,  -- the last NAV date on or before month end
    nav                 TEXT NOT NULL,  -- Decimal string exactly as published
    source_obs_id       INTEGER REFERENCES observations(obs_id),
    refreshed_at        TEXT NOT NULL,
    PRIMARY KEY (instrument_id, month),
    CHECK (substr(nav_date, 1, 7) = month)
);

-- A frozen vendor snapshot no longer matches the next download (design-risk-first.md 2.3). Append-only.
CREATE TABLE restatements (
    restatement_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id           TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    frozen_snapshot_hash TEXT NOT NULL,
    new_content_hash    TEXT NOT NULL,
    first_diff_date     TEXT,
    rows_changed        INTEGER NOT NULL CHECK (rows_changed >= 0),
    detected_at         TEXT NOT NULL,
    CHECK (frozen_snapshot_hash <> new_content_hash)
);
CREATE INDEX ix_restatements_series ON restatements(series_id, detected_at);
CREATE TRIGGER restatements_no_update BEFORE UPDATE ON restatements
BEGIN SELECT RAISE(ABORT, 'append-only constraint: restatements'); END;
CREATE TRIGGER restatements_no_replace BEFORE INSERT ON restatements
WHEN EXISTS (SELECT 1 FROM restatements WHERE restatement_id = NEW.restatement_id)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: restatements row exists'); END;
CREATE TRIGGER restatements_no_delete BEFORE DELETE ON restatements
WHEN NOT EXISTS (SELECT 1 FROM ledger_erase_gate)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: restatements'); END;

-- ---------------------------------------------------------------------------------------------- automation

-- One claim per job and data as-of date (run_key), taken in ONE conditional statement (ledger.claim_cron_run).
CREATE TABLE cron_runs (
    job                 TEXT NOT NULL CHECK (job IN ('navall','navall-continue','history','snapshot','watchdog')),
    run_key             TEXT NOT NULL,
    state               TEXT NOT NULL CHECK (state IN ('running','done','noop','failed')),
    attempts            INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    detail_code         TEXT,           -- codes and counts only, never values
    PRIMARY KEY (job, run_key)
);

-- Engine output: immutable and content-addressed (snapshot_id = sha256 of engine version, rules version and input
-- manifest hash). ABSTAIN is stored too. Today reads the newest row in one statement (ix_signal_snapshots_latest).
CREATE TABLE signal_snapshots (
    snapshot_id         TEXT PRIMARY KEY,
    as_of_date          TEXT NOT NULL,  -- newest observation date used, from the data
    engine_version      TEXT NOT NULL,
    rules_version       TEXT NOT NULL,
    input_manifest_hash TEXT NOT NULL,
    verdict             TEXT NOT NULL,
    card_set_hash       TEXT NOT NULL,  -- hash of the L1-L5 card_id set: a ping fires only when it changes
    payload_json        TEXT NOT NULL,
    created_at          TEXT NOT NULL
);
CREATE INDEX ix_signal_snapshots_latest ON signal_snapshots(as_of_date, created_at);
CREATE TRIGGER signal_snapshots_no_update BEFORE UPDATE ON signal_snapshots
BEGIN SELECT RAISE(ABORT, 'append-only constraint: signal_snapshots'); END;
CREATE TRIGGER signal_snapshots_no_replace BEFORE INSERT ON signal_snapshots
WHEN EXISTS (SELECT 1 FROM signal_snapshots WHERE snapshot_id = NEW.snapshot_id)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: signal_snapshots row exists'); END;
CREATE TRIGGER signal_snapshots_no_delete BEFORE DELETE ON signal_snapshots
WHEN NOT EXISTS (SELECT 1 FROM ledger_erase_gate)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: signal_snapshots'); END;

-- Ping outbox: at most one send per (message, channel). A 'sending' row past its lease is reaped to 'failed' and
-- never resent (losing a ping is the safe direction).
CREATE TABLE notification_outbox (
    outbox_key          TEXT NOT NULL,  -- the snapshot_id, or 'watchdog:<run_key>'
    channel             TEXT NOT NULL,
    kind                TEXT NOT NULL CHECK (kind IN ('report','watchdog')),
    snapshot_id         TEXT REFERENCES signal_snapshots(snapshot_id),
    state               TEXT NOT NULL CHECK (state IN ('pending','sending','sent','failed')),
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    claimed_at          TEXT,
    PRIMARY KEY (outbox_key, channel),
    CHECK (state <> 'sending' OR claimed_at IS NOT NULL)
);
CREATE INDEX ix_notification_outbox_state ON notification_outbox(state, claimed_at);

-- ---------------------------------------------------------------------------------------------- signal research

-- Registry: one row per (rule_id, version). The spec (committed YAML, roles only) and its hash are frozen at
-- registration: only the state may change afterwards.
CREATE TABLE signal_rules (
    rule_id             TEXT NOT NULL,
    version             INTEGER NOT NULL CHECK (version >= 1),
    class               TEXT NOT NULL CHECK (class IN ('P','D','S')),
    family              TEXT NOT NULL,
    spec_yaml           TEXT NOT NULL,
    spec_hash           TEXT NOT NULL,
    registered_at       TEXT NOT NULL,
    state               TEXT NOT NULL CHECK (state IN ('PRE_REGISTERED','ABSTAIN','NO_SIGNAL','ACCEPTED','SUSPENDED','RETIRED')),
    state_reason        TEXT,
    state_changed_at    TEXT NOT NULL,
    PRIMARY KEY (rule_id, version)
);
CREATE TRIGGER signal_rules_spec_frozen BEFORE UPDATE OF rule_id, version, class, family, spec_yaml, spec_hash,
    registered_at ON signal_rules
BEGIN SELECT RAISE(ABORT, 'append-only constraint: signal_rules spec is frozen at registration'); END;
CREATE TRIGGER signal_rules_no_replace BEFORE INSERT ON signal_rules
WHEN EXISTS (SELECT 1 FROM signal_rules WHERE rule_id = NEW.rule_id AND version = NEW.version)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: signal_rules row exists'); END;
CREATE TRIGGER signal_rules_no_delete BEFORE DELETE ON signal_rules
WHEN NOT EXISTS (SELECT 1 FROM ledger_erase_gate)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: signal_rules'); END;

-- Role -> instrument binding: user config in the database, never in the public repo.
CREATE TABLE rule_role_bindings (
    role                TEXT PRIMARY KEY,   -- e.g. index_fund.nifty50.direct
    instrument_id       TEXT NOT NULL REFERENCES instruments(instrument_id),
    rule_of_choice      TEXT NOT NULL,      -- how the instrument was chosen, e.g. longest_history>lowest_ter
    bound_at            TEXT NOT NULL
);

-- Trial log: every configuration ever evaluated, including abandoned ones (gate G8 counts rows per family).
-- The identity columns (params, data snapshot hash and the rest) can never change, and no row can be deleted. The
-- result columns are filled in once the trial has run.
CREATE TABLE backtest_trials (
    trial_id            TEXT PRIMARY KEY,
    rule_id             TEXT NOT NULL,
    version             INTEGER NOT NULL,
    family              TEXT NOT NULL,
    params_json         TEXT NOT NULL,
    universe_id         TEXT NOT NULL,
    horizon             TEXT NOT NULL,
    benchmark_id        TEXT NOT NULL,
    data_snapshot_hash  TEXT NOT NULL,
    code_version        TEXT NOT NULL,
    rules_version       TEXT NOT NULL,
    seed                TEXT NOT NULL,
    oos_edge_hash       TEXT,
    n_periods           INTEGER,
    sr_hat              TEXT,
    skew                TEXT,
    kurt                TEXT,
    status              TEXT NOT NULL CHECK (status IN ('active','retired','vaulted_pass','vaulted_fail')),
    created_at          TEXT NOT NULL
);
CREATE INDEX ix_backtest_trials_family ON backtest_trials(family);
CREATE TRIGGER backtest_trials_no_update BEFORE UPDATE OF trial_id, rule_id, version, family, params_json,
    universe_id, horizon, benchmark_id, data_snapshot_hash, code_version, rules_version, seed, created_at
    ON backtest_trials
BEGIN SELECT RAISE(ABORT, 'append-only constraint: backtest_trials'); END;
CREATE TRIGGER backtest_trials_no_replace BEFORE INSERT ON backtest_trials
WHEN EXISTS (SELECT 1 FROM backtest_trials WHERE trial_id = NEW.trial_id)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: backtest_trials row exists'); END;
CREATE TRIGGER backtest_trials_no_delete BEFORE DELETE ON backtest_trials
WHEN NOT EXISTS (SELECT 1 FROM ledger_erase_gate)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: backtest_trials'); END;

-- Evidence bundle per run: manifest, gate panel and statistics. NO raw market data (safe to store hosted).
CREATE TABLE backtest_runs (
    run_id              TEXT PRIMARY KEY,
    trial_id            TEXT NOT NULL REFERENCES backtest_trials(trial_id),
    manifest_json       TEXT NOT NULL,
    output_hash         TEXT NOT NULL,
    gates_json          TEXT NOT NULL,
    stats_json          TEXT NOT NULL,
    verdict             TEXT NOT NULL,
    vault_opened        INTEGER NOT NULL DEFAULT 0 CHECK (vault_opened IN (0, 1)),
    created_at          TEXT NOT NULL
);
CREATE INDEX ix_backtest_runs_trial ON backtest_runs(trial_id);
CREATE TRIGGER backtest_runs_no_update BEFORE UPDATE ON backtest_runs
BEGIN SELECT RAISE(ABORT, 'append-only constraint: backtest_runs'); END;
CREATE TRIGGER backtest_runs_no_replace BEFORE INSERT ON backtest_runs
WHEN EXISTS (SELECT 1 FROM backtest_runs WHERE run_id = NEW.run_id)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: backtest_runs row exists'); END;
CREATE TRIGGER backtest_runs_no_delete BEFORE DELETE ON backtest_runs
WHEN NOT EXISTS (SELECT 1 FROM ledger_erase_gate)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: backtest_runs'); END;

-- Shadow forward ledger: one row per rule, version, data date and scope (a goal or a role), written daily by J4 for
-- every registered rule including PRE_REGISTERED and ABSTAIN ones. Never shown as an action. Append-only.
CREATE TABLE rule_evaluations (
    rule_id             TEXT NOT NULL,
    version             INTEGER NOT NULL,
    as_of_date          TEXT NOT NULL,
    scope_id            TEXT NOT NULL,
    state               TEXT NOT NULL,
    condition_met       INTEGER CHECK (condition_met IN (0, 1) OR condition_met IS NULL),
    payload_json        TEXT NOT NULL,
    input_hash          TEXT NOT NULL,
    snapshot_id         TEXT NOT NULL,
    evaluated_at        TEXT NOT NULL,
    PRIMARY KEY (rule_id, version, as_of_date, scope_id)
);
CREATE TRIGGER rule_evaluations_no_update BEFORE UPDATE ON rule_evaluations
BEGIN SELECT RAISE(ABORT, 'append-only constraint: rule_evaluations'); END;
CREATE TRIGGER rule_evaluations_no_replace BEFORE INSERT ON rule_evaluations
WHEN EXISTS (SELECT 1 FROM rule_evaluations WHERE rule_id = NEW.rule_id AND version = NEW.version AND as_of_date = NEW.as_of_date AND scope_id = NEW.scope_id)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: rule_evaluations row exists'); END;
CREATE TRIGGER rule_evaluations_no_delete BEFORE DELETE ON rule_evaluations
WHEN NOT EXISTS (SELECT 1 FROM ledger_erase_gate)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: rule_evaluations'); END;

-- Scored once, at the rule's horizon, from realised NAVs. Absence of a row = not yet due or not yet scored.
CREATE TABLE outcomes (
    rule_id             TEXT NOT NULL,
    version             INTEGER NOT NULL,
    as_of_date          TEXT NOT NULL,
    scope_id            TEXT NOT NULL,
    horizon_end         TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('scored','unscorable')),
    edge_after_cost_tax TEXT,           -- Decimal string, only when scored
    unscorable_reason   TEXT,
    inputs_hash         TEXT NOT NULL,
    scored_at           TEXT NOT NULL,
    PRIMARY KEY (rule_id, version, as_of_date, scope_id),
    FOREIGN KEY (rule_id, version, as_of_date, scope_id)
        REFERENCES rule_evaluations(rule_id, version, as_of_date, scope_id),
    CHECK (horizon_end >= as_of_date),
    CHECK ((status = 'scored' AND edge_after_cost_tax IS NOT NULL AND unscorable_reason IS NULL)
        OR (status = 'unscorable' AND edge_after_cost_tax IS NULL AND unscorable_reason IS NOT NULL))
);
CREATE TRIGGER outcomes_no_update BEFORE UPDATE ON outcomes
BEGIN SELECT RAISE(ABORT, 'append-only constraint: outcomes'); END;
CREATE TRIGGER outcomes_no_replace BEFORE INSERT ON outcomes
WHEN EXISTS (SELECT 1 FROM outcomes WHERE rule_id = NEW.rule_id AND version = NEW.version AND as_of_date = NEW.as_of_date AND scope_id = NEW.scope_id)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: outcomes row exists'); END;
CREATE TRIGGER outcomes_no_delete BEFORE DELETE ON outcomes
WHEN NOT EXISTS (SELECT 1 FROM ledger_erase_gate)
BEGIN SELECT RAISE(ABORT, 'append-only constraint: outcomes'); END;
