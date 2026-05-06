-- WP State Machine — Postgres Schema
-- Ziel: 192.168.178.10 (Debian 12), separate DB von ThoPAS
-- Init: bash deploy/postgres-init.sh
-- Apply: psql -U wp_sm -d wp_state_machine -f storage/schema.sql

-- TimescaleDB Extension (falls installiert, sonst weglassen)
-- CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------------
-- Telemetrie-Tabelle (Hypertable wenn TimescaleDB verfuegbar)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS telemetry (
    id          BIGSERIAL,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    vorlauf     REAL,
    ruecklauf   REAL,
    warmwasser  REAL,
    aussen      REAL,
    heissgas    REAL,
    fluessigkeit REAL,
    saugleitung REAL,
    verdichter  BOOLEAN,
    ventil_ww   BOOLEAN,
    heizstab_hz BOOLEAN,
    heizstab_ww BOOLEAN,
    alarm       BOOLEAN,
    betriebsart SMALLINT,
    wp_state    VARCHAR(20),
    PRIMARY KEY (id, ts)
);

-- Hypertable (nur wenn TimescaleDB aktiv)
-- SELECT create_hypertable('telemetry', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS telemetry_ts_idx ON telemetry (ts DESC);

-- ---------------------------------------------------------------------------
-- State-History (Snapshots bei State-Wechsel)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS state_history (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    old_state   VARCHAR(20),
    new_state   VARCHAR(20) NOT NULL,
    betriebsart SMALLINT,
    vorlauf     REAL,
    aussen      REAL,
    details     JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS state_history_ts_idx ON state_history (ts DESC);

-- ---------------------------------------------------------------------------
-- Function Audits (Schreib-Versuche — Whitelist, DRY_RUN, CMI-Response)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS function_audits (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    address         VARCHAR(20) NOT NULL,
    value           REAL,
    whitelist_ok    BOOLEAN NOT NULL,
    dry_run         BOOLEAN NOT NULL,
    cmi_called      BOOLEAN NOT NULL DEFAULT FALSE,
    cmi_response    TEXT,
    success         BOOLEAN,
    reason          TEXT,
    caller          VARCHAR(100)  -- z.B. "api/rest" oder "telegram"
);

CREATE INDEX IF NOT EXISTS function_audits_ts_idx ON function_audits (ts DESC);
CREATE INDEX IF NOT EXISTS function_audits_address_idx ON function_audits (address);

-- ---------------------------------------------------------------------------
-- Alarms
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS alarms (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    active          BOOLEAN NOT NULL,
    telegram_fwd    BOOLEAN NOT NULL DEFAULT FALSE,
    details         TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS alarms_ts_idx ON alarms (ts DESC);

-- ---------------------------------------------------------------------------
-- Heartbeats (Self-Monitoring)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS heartbeats (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    module      VARCHAR(50) NOT NULL DEFAULT 'main',
    details     JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS heartbeats_ts_idx ON heartbeats (ts DESC);
