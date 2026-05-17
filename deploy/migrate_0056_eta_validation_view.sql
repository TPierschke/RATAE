-- Migration 0.5.6 — Validation view: forecast ETA vs actual time-to-next-demand
--
-- For every BEREIT snapshot we recorded a ww_eta_min / heat_eta_min prediction.
-- This view joins each BEREIT row with the next observed transition into
-- WARMWASSER or HEIZUNG and reports actual_min + error_min (actual - eta).
--
-- Idempotent. Apply: psql -U wp_sm -d wp_state_machine -f deploy/migrate_0056_eta_validation_view.sql

DROP VIEW IF EXISTS public.eta_validation;

CREATE VIEW public.eta_validation AS
WITH transitions AS (
    SELECT ts, wp_state,
           LAG(wp_state) OVER (ORDER BY ts) AS prev_state
    FROM public.telemetry
    WHERE wp_state IS NOT NULL
),
ww_starts AS (
    SELECT ts FROM transitions
    WHERE prev_state IS DISTINCT FROM wp_state AND wp_state = 'WARMWASSER'
),
heat_starts AS (
    SELECT ts FROM transitions
    WHERE prev_state IS DISTINCT FROM wp_state AND wp_state = 'HEIZUNG'
)
SELECT
    t.ts AS bereit_ts,
    t.warmwasser,
    t.vorlauf,
    t.vorlauf_soll,
    t.ww_soll_normal,
    t.betriebsart,

    -- WW forecast vs actual
    t.ww_eta_min AS ww_eta,
    ROUND( EXTRACT(EPOCH FROM (
        (SELECT MIN(w.ts) FROM ww_starts w WHERE w.ts > t.ts) - t.ts
    )) / 60.0 )::int AS ww_actual_min,
    ROUND( EXTRACT(EPOCH FROM (
        (SELECT MIN(w.ts) FROM ww_starts w WHERE w.ts > t.ts) - t.ts
    )) / 60.0 - t.ww_eta_min )::int AS ww_error_min,

    -- Heizung forecast vs actual
    t.heat_eta_min AS heat_eta,
    ROUND( EXTRACT(EPOCH FROM (
        (SELECT MIN(h.ts) FROM heat_starts h WHERE h.ts > t.ts) - t.ts
    )) / 60.0 )::int AS heat_actual_min,
    ROUND( EXTRACT(EPOCH FROM (
        (SELECT MIN(h.ts) FROM heat_starts h WHERE h.ts > t.ts) - t.ts
    )) / 60.0 - t.heat_eta_min )::int AS heat_error_min
FROM public.telemetry t
WHERE t.wp_state = 'BEREIT'
  AND (t.ww_eta_min IS NOT NULL OR t.heat_eta_min IS NOT NULL)
ORDER BY t.ts DESC;

COMMENT ON VIEW public.eta_validation IS
'Per BEREIT-Snapshot: forecast ww_eta_min/heat_eta_min vs actual time to next WARMWASSER/HEIZUNG transition. error_min = actual - eta (positive = forecast was too short).';

-- Aggregate quality summary: mean / median absolute error per forecast type.
DROP VIEW IF EXISTS public.eta_validation_summary;

CREATE VIEW public.eta_validation_summary AS
SELECT
    'WW'  AS kind,
    COUNT(ww_eta) FILTER (WHERE ww_actual_min IS NOT NULL)               AS n,
    ROUND(AVG(ww_eta)               FILTER (WHERE ww_actual_min IS NOT NULL))::int AS mean_eta_min,
    ROUND(AVG(ww_actual_min)        FILTER (WHERE ww_actual_min IS NOT NULL))::int AS mean_actual_min,
    ROUND(AVG(ABS(ww_error_min))    FILTER (WHERE ww_actual_min IS NOT NULL))::int AS mean_abs_error_min,
    ROUND(AVG(ww_error_min)         FILTER (WHERE ww_actual_min IS NOT NULL))::int AS mean_signed_error_min
FROM public.eta_validation
UNION ALL
SELECT
    'Heizung',
    COUNT(heat_eta) FILTER (WHERE heat_actual_min IS NOT NULL),
    ROUND(AVG(heat_eta)             FILTER (WHERE heat_actual_min IS NOT NULL))::int,
    ROUND(AVG(heat_actual_min)      FILTER (WHERE heat_actual_min IS NOT NULL))::int,
    ROUND(AVG(ABS(heat_error_min))  FILTER (WHERE heat_actual_min IS NOT NULL))::int,
    ROUND(AVG(heat_error_min)       FILTER (WHERE heat_actual_min IS NOT NULL))::int
FROM public.eta_validation;

COMMENT ON VIEW public.eta_validation_summary IS
'Aggregated forecast quality: signed bias + mean absolute error per forecast type.';
