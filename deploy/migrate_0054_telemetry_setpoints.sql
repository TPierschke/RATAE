-- Migration 0.5.4 — Add setpoint columns to telemetry table
--
-- Idempotent: all statements use ADD COLUMN IF NOT EXISTS.
-- Apply: psql -U wp_sm -d wp_state_machine -f deploy/migrate_0054_telemetry_setpoints.sql
--
-- New columns track the six CMI function setpoints alongside sensor snapshots,
-- enabling time-series comparison of setpoints vs. actual measured values.

ALTER TABLE public.telemetry
    ADD COLUMN IF NOT EXISTS normal_soll    REAL,
    ADD COLUMN IF NOT EXISTS absenk_soll   REAL,
    ADD COLUMN IF NOT EXISTS raum_ist      REAL,
    ADD COLUMN IF NOT EXISTS ww_soll_normal REAL,
    ADD COLUMN IF NOT EXISTS ww_soll_legio REAL,
    ADD COLUMN IF NOT EXISTS ww_ist        REAL;

-- Verify: run \d public.telemetry and confirm the six new columns appear.
