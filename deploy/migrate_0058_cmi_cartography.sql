-- Migration 0.5.8 — CMI Cartography: full menupage tree storage
--
-- Stores the result of a complete BFS crawl of the CMI menupage tree.
-- Idempotent (IF NOT EXISTS). Re-run after each crawl to upsert fresh data.
--
-- Apply: psql -U wp_sm -d wp_state_machine -f deploy/migrate_0058_cmi_cartography.sql

-- ---------------------------------------------------------------------------
-- cmi_pages: one row per visited menupage
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.cmi_pages (
    page_id     TEXT        PRIMARY KEY,               -- hex address, e.g. '3E06580E'
    url         TEXT        NOT NULL,                  -- full URL
    title       TEXT,                                  -- extracted h1/title text
    raw_html    TEXT,                                  -- full raw HTML response
    crawled_at  TIMESTAMPTZ NOT NULL DEFAULT now(),    -- last successful fetch
    http_status INT                                    -- HTTP response code
);

COMMENT ON TABLE public.cmi_pages IS
'One row per CMI menupage visited during BFS crawl. raw_html allows re-parsing without re-crawling.';

-- ---------------------------------------------------------------------------
-- cmi_page_values: key/value pairs extracted from each page
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.cmi_page_values (
    id          BIGSERIAL   PRIMARY KEY,
    page_id     TEXT        NOT NULL REFERENCES public.cmi_pages(page_id) ON DELETE CASCADE,
    label       TEXT        NOT NULL,   -- e.g. 'Betriebsdauer', 'MODUS', 'BEZ.'
    raw_value   TEXT,                   -- raw string as scraped
    value_num   REAL,                   -- numeric part if parseable
    unit        TEXT,                   -- e.g. 'hr', 'min', '°C', '%'
    crawled_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cmi_page_values_page ON public.cmi_page_values(page_id);
CREATE INDEX IF NOT EXISTS idx_cmi_page_values_label ON public.cmi_page_values(label);

COMMENT ON TABLE public.cmi_page_values IS
'Extracted label/value pairs from each CMI menupage. Repopulated on each crawl.';

-- ---------------------------------------------------------------------------
-- cmi_page_links: directed edge parent → child (page tree structure)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.cmi_page_links (
    parent_page_id  TEXT    NOT NULL,
    child_page_id   TEXT    NOT NULL,
    link_text       TEXT,              -- anchor text or aria label
    PRIMARY KEY (parent_page_id, child_page_id)
);

COMMENT ON TABLE public.cmi_page_links IS
'Directed links between CMI menupages. Represents the navigation tree.';

-- ---------------------------------------------------------------------------
-- cmi_changeadr: writable parameters found on pages (changeadr links)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.cmi_changeadr (
    address     TEXT        PRIMARY KEY,               -- e.g. '3E9001301C'
    page_id     TEXT        REFERENCES public.cmi_pages(page_id) ON DELETE SET NULL,
    label       TEXT,                                  -- surrounding label text
    current_raw TEXT,                                  -- raw value shown when scraped
    current_num REAL,                                  -- numeric if parseable
    unit        TEXT,
    crawled_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.cmi_changeadr IS
'All changeadr-addresses found during crawl — these are writable CMI parameters. Key reference for safety whitelist maintenance.';

-- ---------------------------------------------------------------------------
-- cmi_crawl_runs: audit log of crawl runs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.cmi_crawl_runs (
    id              BIGSERIAL   PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    pages_visited   INT,
    pages_new       INT,
    pages_updated   INT,
    errors          INT,
    notes           TEXT
);

COMMENT ON TABLE public.cmi_crawl_runs IS
'One row per crawl run. Use to track freshness and detect regressions.';
