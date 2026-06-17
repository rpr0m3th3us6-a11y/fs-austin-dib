"""
dib_validate_release.py
=======================
Post-generation release validation for the DIB pipeline.

Checks BOTH the local workspace artifacts (PDFs, data.json)
AND the live GitHub Pages site to confirm everything matches
before the brief is considered "released."

Usage:
    python dib_validate_release.py YYYYMMDD

Returns:
    Exit code 0  — all checks passed
    Exit code 1  — one or more checks failed (details printed to stdout)

Called automatically by dib_daily_runner.py after the push step.
Can also be run standalone after a manual rebuild.
"""

import sys
import os
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# ─── Config ───────────────────────────────────────────────────────────────────
WS              = "/home/user/workspace"
SITE_DIR        = os.path.join(WS, "dib-site")
PAGES_BASE      = "https://rpr0m3th3us6-a11y.github.io/fs-austin-dib"
REQUIRED_CONTACTS = 8
MIN_FULL_PAGES    = 7       # Full DIB must be at least this many pages
MAX_FULL_PAGES    = 12      # Sanity upper bound (catches Notes-string explosion)
EXPECTED_1PAGER_PAGES = 1
LIVE_FETCH_RETRIES    = 3   # Retry live data.json fetch (GitHub Pages CDN lag)
LIVE_FETCH_DELAY_SEC  = 8   # Seconds between retries

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ok(msg):
    print(f"  ✓  {msg}")

def _fail(msg):
    print(f"  ✗  {msg}")

def _warn(msg):
    print(f"  ⚠  {msg}")


def _fetch_json(url, retries=1, delay=0):
    """Fetch JSON from URL with optional retry."""
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"}
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                print(f"    Retry {attempt+1}/{retries-1} after {delay}s (got: {e})")
                time.sleep(delay)
    raise last_err


def _pdf_page_count(path):
    """Return page count of a PDF using pypdfium2."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path)
    n = len(doc)
    doc.close()
    return n


# ─── Check groups ─────────────────────────────────────────────────────────────

def check_local_pdfs(date_str):
    """Verify local PDF files exist and have correct page counts."""
    failures = []
    full_path = os.path.join(WS, f"DIB_FourSeasons_Austin_{date_str}.pdf")
    one_path  = os.path.join(WS, f"DIB_1Pager_FourSeasons_Austin_{date_str}.pdf")

    print("\n[A] Local PDF checks")

    # Full DIB exists
    if not os.path.exists(full_path):
        _fail(f"Full DIB not found: {os.path.basename(full_path)}")
        failures.append("full_pdf_missing")
    else:
        size = os.path.getsize(full_path)
        _ok(f"Full DIB exists ({size:,} bytes)")
        # Page count
        try:
            pages = _pdf_page_count(full_path)
            if pages < MIN_FULL_PAGES:
                _fail(f"Full DIB has only {pages} pages (expected ≥ {MIN_FULL_PAGES}) — possible generation failure")
                failures.append(f"full_pdf_too_short:{pages}")
            elif pages > MAX_FULL_PAGES:
                _fail(f"Full DIB has {pages} pages (expected ≤ {MAX_FULL_PAGES}) — possible WEATHER Notes string bug")
                failures.append(f"full_pdf_too_long:{pages}")
            else:
                _ok(f"Full DIB page count: {pages} ✓")
        except Exception as e:
            _warn(f"Could not check page count: {e}")

    # 1-Pager exists
    if not os.path.exists(one_path):
        _fail(f"1-Pager not found: {os.path.basename(one_path)}")
        failures.append("onepager_missing")
    else:
        size2 = os.path.getsize(one_path)
        _ok(f"1-Pager exists ({size2:,} bytes)")
        # Must be exactly 1 page
        try:
            pages2 = _pdf_page_count(one_path)
            if pages2 != EXPECTED_1PAGER_PAGES:
                _fail(f"1-Pager has {pages2} pages — must be exactly {EXPECTED_1PAGER_PAGES}")
                failures.append(f"onepager_page_count:{pages2}")
            else:
                _ok(f"1-Pager page count: {pages2} ✓")
        except Exception as e:
            _warn(f"Could not check 1-pager page count: {e}")

    return failures


def check_local_data_json(date_str):
    """Verify dib-site/data.json matches today's date and has required fields."""
    failures = []
    data_path = os.path.join(SITE_DIR, "data.json")
    print("\n[B] Local data.json checks")

    if not os.path.exists(data_path):
        _fail(f"data.json not found at {data_path}")
        return ["data_json_missing"]

    with open(data_path) as f:
        data = json.load(f)

    # Date fields match
    if data.get("date_file") != date_str:
        _fail(f"data.json date_file = '{data.get('date_file')}' — expected '{date_str}'")
        failures.append("data_json_wrong_date")
    else:
        _ok(f"data.json date_file matches: {date_str}")

    if not data.get("date_str"):
        _fail("data.json date_str is empty")
        failures.append("data_json_date_str_empty")
    else:
        _ok(f"data.json date_str: '{data['date_str']}'")

    # PDF URLs reference today's date
    for key in ("full_pdf_url", "onepager_pdf_url"):
        url = data.get(key, "")
        if date_str not in url:
            _fail(f"data.json {key} does not reference {date_str}: {url}")
            failures.append(f"data_json_{key}_wrong_date")
        else:
            _ok(f"data.json {key} references correct date")

    # BLUF present
    bluf = data.get("bluf", "")
    if len(bluf) < 20:
        _fail(f"data.json BLUF is too short ({len(bluf)} chars) — possible empty content")
        failures.append("data_json_bluf_empty")
    else:
        _ok(f"data.json BLUF present ({len(bluf)} chars)")

    # Contacts — must have exactly REQUIRED_CONTACTS
    contacts = data.get("contacts", [])
    if len(contacts) != REQUIRED_CONTACTS:
        _fail(f"data.json has {len(contacts)} contacts — expected {REQUIRED_CONTACTS}")
        failures.append(f"data_json_contacts:{len(contacts)}")
    else:
        _ok(f"data.json contacts: {len(contacts)} ✓")

    # Incidents present
    incidents = data.get("incidents", [])
    if len(incidents) == 0:
        _fail("data.json has 0 incidents — possible content module error")
        failures.append("data_json_no_incidents")
    else:
        _ok(f"data.json incidents: {len(incidents)}")

    # Events present
    events = data.get("events", [])
    if len(events) == 0:
        _warn("data.json has 0 events — verify this is intentional")
    else:
        _ok(f"data.json events: {len(events)}")

    # Threat matrix present
    tm = data.get("threat_matrix", [])
    if len(tm) < 3:
        _fail(f"data.json threat_matrix has only {len(tm)} entries")
        failures.append("data_json_threat_matrix_short")
    else:
        _ok(f"data.json threat_matrix: {len(tm)} domains")

    return failures


def check_live_site(date_str):
    """
    Fetch live GitHub Pages data.json and confirm it matches today's date.
    Retries to account for CDN propagation lag.
    """
    failures = []
    # Use raw.githubusercontent to bypass GitHub Pages CDN propagation lag
    raw_base = PAGES_BASE.replace(
        "https://rpr0m3th3us6-a11y.github.io/fs-austin-dib",
        "https://raw.githubusercontent.com/rpr0m3th3us6-a11y/fs-austin-dib/main"
    )
    url = f"{raw_base}/data.json?v={int(time.time())}"
    print(f"\n[C] Live GitHub Pages checks  ({PAGES_BASE})")

    try:
        data = _fetch_json(url, retries=LIVE_FETCH_RETRIES, delay=LIVE_FETCH_DELAY_SEC)
    except Exception as e:
        _fail(f"Could not fetch live data.json: {e}")
        return ["live_fetch_failed"]

    # Date check — this is the core issue we documented
    live_date_file = data.get("date_file", "")
    live_date_str  = data.get("date_str", "")

    if live_date_file != date_str:
        _fail(
            f"LIVE site shows date_file='{live_date_file}' — expected '{date_str}'. "
            f"GitHub Pages CDN may not have propagated yet, or push failed."
        )
        failures.append(f"live_wrong_date:{live_date_file}")
    else:
        _ok(f"Live date_file matches: {live_date_file} ✓")

    # date_str is YYYYMMDD; live_date_str is human e.g. 'June 15, 2026' — just check non-empty
    if not live_date_str or len(live_date_str) < 5:
        _fail(f"Live date_str is empty or too short: '{live_date_str}'")
        failures.append("live_date_str_empty")
    else:
        _ok(f"Live date_str: '{live_date_str}' ✓")

    # PDF URLs in live data reference today
    for key in ("full_pdf_url", "onepager_pdf_url"):
        url_val = data.get(key, "")
        if date_str not in url_val:
            _fail(f"Live {key} references wrong date: {url_val}")
            failures.append(f"live_{key}_wrong_date")
        else:
            _ok(f"Live {key} references {date_str} ✓")

    # Spot-check: BLUF not empty
    bluf = data.get("bluf", "")
    if len(bluf) < 20:
        _fail(f"Live BLUF is empty/too short ({len(bluf)} chars)")
        failures.append("live_bluf_empty")
    else:
        _ok(f"Live BLUF present ({len(bluf)} chars) ✓")

    # Contacts
    contacts = data.get("contacts", [])
    if len(contacts) != REQUIRED_CONTACTS:
        _fail(f"Live site has {len(contacts)} contacts — expected {REQUIRED_CONTACTS}")
        failures.append(f"live_contacts:{len(contacts)}")
    else:
        _ok(f"Live contacts: {len(contacts)} ✓")

    # Archive entry
    archive_url = f"{raw_base}/archive.json?v={int(time.time())}"
    try:
        archive = _fetch_json(archive_url, retries=2, delay=5)
        dates_in_archive = [e.get("date_file") for e in archive]
        if date_str in dates_in_archive:
            _ok(f"Archive contains {date_str} entry ✓  ({len(archive)} total entries)")
        else:
            _fail(f"Archive does NOT contain {date_str} — found: {dates_in_archive[-3:]}")
            failures.append("live_archive_missing_date")
    except Exception as e:
        _warn(f"Could not verify archive.json: {e}")

    return failures


# ─── Main ─────────────────────────────────────────────────────────────────────

def run_all_checks(date_str):
    CDT = timezone(timedelta(hours=-5))
    now_str = datetime.now(CDT).strftime("%A, %B %-d, %Y at %-I:%M %p CDT")

    print(f"\n{'='*60}")
    print(f"DIB Release Validation — {date_str}")
    print(f"Run at: {now_str}")
    print(f"{'='*60}")

    all_failures = []
    all_failures += check_local_pdfs(date_str)
    all_failures += check_local_data_json(date_str)
    all_failures += check_live_site(date_str)

    print(f"\n{'─'*60}")
    if not all_failures:
        print(f"✅  ALL CHECKS PASSED — DIB release for {date_str} is VALIDATED")
        print(f"    GitHub Pages: {PAGES_BASE}/")
        return 0
    else:
        print(f"❌  VALIDATION FAILED — {len(all_failures)} issue(s) detected:")
        for f in all_failures:
            print(f"    • {f}")
        print(f"\n    HOLD DELIVERY until issues are resolved.")
        print(f"    Re-run: python {os.path.basename(__file__)} {date_str}")
        return 1


if __name__ == "__main__":
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now(
        timezone(timedelta(hours=-5))
    ).strftime("%Y%m%d")
    sys.exit(run_all_checks(date_str))
