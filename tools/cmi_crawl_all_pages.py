#!/usr/bin/env python3
"""
CMI full menupage BFS crawler.

Crawls ALL pages reachable from the CMI root menupage and stores them in Postgres.
Schema: deploy/migrate_0058_cmi_cartography.sql

Usage:
    python3 tools/cmi_crawl_all_pages.py [--dry-run] [--reset]

Options:
    --dry-run   Crawl and print, do not write to DB.
    --reset     Truncate all cmi_* tables before crawl (full re-crawl).

Requires: psycopg2, requests (or urllib from stdlib)
DB URL from env WPSM_POSTGRES_URL or default below.
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import sys
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin
from urllib.request import Request, urlopen

CMI_HOST     = "192.168.178.45"
CMI_ROOT     = "3E005800"
RATE_LIMIT_S = 3.0  # seconds between requests — deliberately slow, CMI is sensitive
TIMEOUT_S    = 10

DB_URL = os.environ.get(
    "WPSM_POSTGRES_URL",
    "postgresql://wp_sm:ee007d8d88dc5bcb2e6986e8eb428285@192.168.178.10:5432/wp_state_machine"
)

AUTH_HEADER = {
    "Authorization": "Basic " + base64.b64encode(b"admin:admin").decode()
}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def fetch_page(page_id: str) -> tuple[int, str]:
    """Fetch one menupage. Returns (http_status, html)."""
    url = f"http://{CMI_HOST}/menupage.cgi?page={page_id}"
    req = Request(url, headers=AUTH_HEADER)
    try:
        with urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"  FETCH ERROR {page_id}: {exc}")
        return 0, ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_LINK_RE    = re.compile(r'menupage\.cgi\?page=([0-9A-Fa-f]{8})')
_CHANGE_RE  = re.compile(r'id="a([0-9A-Fa-f]{8,12})"')
_H1_RE      = re.compile(r'<h1[^>]*>([^<]+)</h1>', re.I)


def extract_links(html: str) -> list[str]:
    return list(dict.fromkeys(_LINK_RE.findall(html)))  # unique, order-preserving


def extract_changeadr(html: str) -> list[str]:
    return list(dict.fromkeys(_CHANGE_RE.findall(html)))


def extract_title(html: str) -> Optional[str]:
    m = _H1_RE.search(html)
    return m.group(1).strip() if m else None


def strip_tags(html: str) -> str:
    return re.sub(r'<[^>]+>', ' ', html)


def extract_values(page_id: str, html: str) -> list[dict]:
    """
    Extract label/value pairs from page text.
    Looks for patterns like 'LABEL:  VALUE unit' in stripped text.
    """
    text = strip_tags(html)
    rows: list[dict] = []

    # Match lines that look like "KEY: VALUE [unit]"
    for line in text.splitlines():
        line = line.strip().replace('\xa0', ' ')
        if not line or len(line) > 200:
            continue
        # Pattern: "Label text:  <value> <unit>"
        m = re.match(r'^([A-ZÄÖÜ][^:]{1,40}):\s*(.+)$', line)
        if not m:
            continue
        label = m.group(1).strip()
        rest  = m.group(2).strip()
        if not rest or rest.startswith('http') or 'function' in rest.lower():
            continue
        # Try to parse numeric value + unit
        nm = re.match(r'^(-?\d[\d\s]*[.,]?\d*)\s*([a-zA-Z°%/]*)\s*$', rest)
        if nm:
            raw_val  = rest
            num_str  = nm.group(1).replace(' ', '').replace(',', '.')
            unit_str = nm.group(2).strip() or None
            try:
                value_num = float(num_str)
            except ValueError:
                value_num = None
        else:
            raw_val   = rest[:120]
            value_num = None
            unit_str  = None

        rows.append({
            "page_id":   page_id,
            "label":     label[:120],
            "raw_value": raw_val,
            "value_num": value_num,
            "unit":      unit_str,
        })

    return rows


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db():
    try:
        import psycopg2
        return psycopg2.connect(DB_URL)
    except ImportError:
        print("psycopg2 not installed — run: pip install psycopg2-binary")
        sys.exit(1)
    except Exception as exc:
        print(f"DB connect error: {exc}")
        sys.exit(1)


def db_reset(cur):
    for t in ("cmi_page_values", "cmi_page_links", "cmi_changeadr", "cmi_pages", "cmi_crawl_runs"):
        cur.execute(f"TRUNCATE TABLE public.{t} CASCADE")
    print("DB tables truncated.")


def _strip_nul(s: Optional[str]) -> Optional[str]:
    return s.replace("\x00", "") if s else s


def db_upsert_page(cur, page_id: str, url: str, title: Optional[str],
                   raw_html: str, status: int):
    title    = _strip_nul(title)
    raw_html = _strip_nul(raw_html)
    cur.execute("""
        INSERT INTO public.cmi_pages (page_id, url, title, raw_html, crawled_at, http_status)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (page_id) DO UPDATE SET
            url        = EXCLUDED.url,
            title      = EXCLUDED.title,
            raw_html   = EXCLUDED.raw_html,
            crawled_at = EXCLUDED.crawled_at,
            http_status= EXCLUDED.http_status
    """, (page_id, url, title, raw_html, datetime.now(timezone.utc), status))


def db_upsert_values(cur, values: list[dict]):
    if not values:
        return
    cur.execute("DELETE FROM public.cmi_page_values WHERE page_id = %s",
                (values[0]["page_id"],))
    for v in values:
        v = {k: (_strip_nul(val) if isinstance(val, str) else val) for k, val in v.items()}
        cur.execute("""
            INSERT INTO public.cmi_page_values (page_id, label, raw_value, value_num, unit, crawled_at)
            VALUES (%(page_id)s, %(label)s, %(raw_value)s, %(value_num)s, %(unit)s, now())
        """, v)


def db_upsert_links(cur, parent: str, children: list[str]):
    for child in children:
        cur.execute("""
            INSERT INTO public.cmi_page_links (parent_page_id, child_page_id)
            VALUES (%s, %s) ON CONFLICT DO NOTHING
        """, (parent, child))


def db_upsert_changeadr(cur, page_id: str, addresses: list[str]):
    addresses = [_strip_nul(a) for a in addresses if a]
    for addr in addresses:
        cur.execute("""
            INSERT INTO public.cmi_changeadr (address, page_id, crawled_at)
            VALUES (%s, %s, now())
            ON CONFLICT (address) DO UPDATE SET
                page_id    = EXCLUDED.page_id,
                crawled_at = EXCLUDED.crawled_at
        """, (addr, page_id))


# ---------------------------------------------------------------------------
# Main crawl
# ---------------------------------------------------------------------------

def crawl(dry_run: bool = False, reset: bool = False) -> None:
    conn = None if dry_run else get_db()
    cur  = conn.cursor() if conn else None

    if reset and cur:
        db_reset(cur)
        conn.commit()

    run_start  = datetime.now(timezone.utc)
    visited:   set[str] = set()
    queue:     deque[str] = deque([CMI_ROOT])
    pages_new  = 0
    pages_upd  = 0
    errors     = 0

    print(f"CMI BFS crawl starting at {CMI_ROOT}  (dry_run={dry_run})")

    while queue:
        page_id = queue.popleft()
        if page_id in visited:
            continue
        visited.add(page_id)

        url    = f"http://{CMI_HOST}/menupage.cgi?page={page_id}"
        status, html = fetch_page(page_id)

        if status == 0:
            errors += 1
            print(f"  [{len(visited):>4}] {page_id}  ERROR")
            time.sleep(RATE_LIMIT_S)
            continue

        title      = extract_title(html)
        links      = extract_links(html)
        changeaddrs= extract_changeadr(html)
        values     = extract_values(page_id, html)

        new_links = [l for l in links if l not in visited]
        queue.extend(new_links)

        print(f"  [{len(visited):>4}] {page_id}  {title or '?':30}  "
              f"links={len(links):>3}  vals={len(values):>3}  change={len(changeaddrs):>3}")

        if not dry_run and cur:
            is_new = True  # simplified — upsert handles both
            db_upsert_page(cur, page_id, url, title, html, status)
            db_upsert_values(cur, values)
            db_upsert_links(cur, page_id, links)
            db_upsert_changeadr(cur, page_id, changeaddrs)
            if is_new:
                pages_new += 1
            else:
                pages_upd += 1
            conn.commit()

        time.sleep(RATE_LIMIT_S)

    total_pages = len(visited)
    print(f"\nDone. Pages visited: {total_pages}, errors: {errors}")

    if not dry_run and cur:
        cur.execute("""
            INSERT INTO public.cmi_crawl_runs
                (started_at, finished_at, pages_visited, pages_new, pages_updated, errors)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (run_start, datetime.now(timezone.utc), total_pages, pages_new, pages_upd, errors))
        conn.commit()
        conn.close()
        print("Results written to Postgres (cmi_pages, cmi_page_values, cmi_page_links, cmi_changeadr).")


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="CMI full menupage BFS crawler")
    ap.add_argument("--dry-run", action="store_true", help="Crawl only, no DB writes")
    ap.add_argument("--reset",   action="store_true", help="Truncate cmi_* tables first")
    args = ap.parse_args()

    crawl(dry_run=args.dry_run, reset=args.reset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
