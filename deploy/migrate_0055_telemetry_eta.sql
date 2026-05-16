-- Migration 0.5.5 — Add ETA forecast columns to telemetry
--
-- Idempotent. Apply: psql -U wp_sm -d wp_state_machine -f deploy/migrate_0055_telemetry_eta.sql
--
-- Stores forecast minutes for next demand while in BEREIT state, so the
-- forecast quality can later be measured vs. the real time-to-next-demand.

ALTER TABLE public.telemetry
    ADD COLUMN IF NOT EXISTS ww_eta_min   REAL,
    ADD COLUMN IF NOT EXISTS heat_eta_min REAL;

COMMENT ON COLUMN public.telemetry.ww_eta_min   IS 'Forecast minutes until WW falls below F:2 DIFF.EIN. NULL outside BEREIT.';
COMMENT ON COLUMN public.telemetry.heat_eta_min IS 'Forecast minutes until puffer falls below F:8 DIFF.EIN. NULL outside BEREIT or when betriebsart=Standby.';
