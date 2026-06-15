#!/usr/bin/env python3
"""
DIB Daily Runner — Four Seasons Hotel Austin
Orchestrates OSINT collection and PDF generation for both the
Full Intelligence Brief and the Staff Quick Reference (1-Pager).

Run manually: python dib_daily_runner.py
Run for specific date: python dib_daily_runner.py 2026-06-02

Called daily by scheduled task at 05:00 CDT.
"""

import os
import sys
import json
import requests
import subprocess
from datetime import datetime, timezone, timedelta

# ─── Config ───────────────────────────────────────────────────────────────────
CDT      = timezone(timedelta(hours=-5))   # CDT = UTC-5 (CST = UTC-6, use -5 for CDT)
WS       = "/home/user/workspace"
NWS_URL  = "https://forecast.weather.gov/MapClick.php?CityName=Austin&state=TX&site=EWX&textField1=30.2676&textField2=-97.743"
APD_URL  = "https://cbsaustin.com"
EVENTS_URL = "https://americanarenas.com/city/austin-events/june/"

# ─── Date ─────────────────────────────────────────────────────────────────────
if len(sys.argv) > 1:
    report_date = datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(tzinfo=CDT)
else:
    report_date = datetime.now(CDT)

DATE_STR  = report_date.strftime("%B %-d, %Y")
DATE_FILE = report_date.strftime("%Y%m%d")
DAY_STR   = report_date.strftime("%A")

print(f"\n{'='*60}")
print(f"DIB Daily Runner — {DAY_STR}, {DATE_STR}")
print(f"{'='*60}\n")

# ─── Step 1: Generate Full DIB ────────────────────────────────────────────────
# ─── Step 0: Generate Map PNG ────────────────────────────────────────────────
print("[0/3] Generating Threat Proximity Map...")
map_out = os.path.join(WS, f"dib_map_{DATE_FILE}.png")
# Only attempt map if the content module already exists
# (map_generator is called inside the date-specific PDF generator anyway)
_content_mod_path = os.path.join(WS, f"dib_content_{DATE_FILE}.py")
if os.path.exists(_content_mod_path):
    try:
        sys.path.insert(0, WS)
        import importlib
        content_mod = importlib.import_module(f"dib_content_{DATE_FILE}")
        from map_generator import generate_map
        map_result = generate_map(DATE_FILE, content_mod)
        if map_result:
            print(f"  \u2713 Map PNG: {map_out}")
        else:
            print(f"  \u2717 Map generation returned None (PDF will fall back gracefully)")
    except Exception as _me:
        print(f"  \u2717 Map generation skipped: {_me} (non-fatal)")
else:
    print(f"  ⏭ Skipped — content module not yet created for {DATE_FILE}")

print("\n[1/3] Generating Full Intelligence Brief...")
# Auto-create date-specific generator if it doesn't exist yet
date_script = os.path.join(WS, f"generate_dib_{DATE_FILE}.py")
full_out    = os.path.join(WS, f"DIB_FourSeasons_Austin_{DATE_FILE}.pdf")

if not os.path.exists(date_script):
    # Find the most recent existing date-specific generator to use as template
    import glob as _glob
    existing = sorted(_glob.glob(os.path.join(WS, "generate_dib_2026*.py")))
    if existing:
        prev_script = existing[-1]
        prev_date   = os.path.basename(prev_script).replace("generate_dib_","").replace(".py","")
        prev_dt     = datetime.strptime(prev_date, "%Y%m%d")
        prev_day    = prev_dt.strftime("%A")
        prev_dstr   = prev_dt.strftime("%B %-d, %Y")
        curr_day    = report_date.strftime("%A")
        curr_dstr   = report_date.strftime("%B %-d, %Y")
        with open(prev_script, "r") as _f:
            tmpl = _f.read()
        # Replace date references
        tmpl = tmpl.replace(prev_date, DATE_FILE)
        tmpl = tmpl.replace(prev_dstr, curr_dstr)
        tmpl = tmpl.replace(prev_day,  curr_day)
        tmpl = tmpl.replace(f"dib_content_{prev_date}", f"dib_content_{DATE_FILE}")
        with open(date_script, "w") as _f:
            _f.write(tmpl)
        print(f"  Auto-created {os.path.basename(date_script)} from {os.path.basename(prev_script)}")
    else:
        print(f"  WARNING: No template found — falling back to generate_dib.py (content will be stale)")
        date_script = os.path.join(WS, "generate_dib.py")

full_script = date_script
print(f"  Using: {os.path.basename(full_script)}")

result = subprocess.run(
    [sys.executable, full_script],
    capture_output=True, text=True, cwd=WS
)
if result.returncode == 0:
    print(f"  ✓ Full DIB: {full_out}")
    if os.path.exists(full_out):
        size = os.path.getsize(full_out)
        print(f"    Size: {size:,} bytes")
else:
    print(f"  ✗ Full DIB FAILED:\n{result.stderr}")

# ─── Step 2: Generate 1-Pager ────────────────────────────────────────────────
print("\n[2/3] Generating Staff Quick Reference (1-Pager)...")
one_out = os.path.join(WS, f"DIB_1Pager_FourSeasons_Austin_{DATE_FILE}.pdf")

if os.path.exists(one_out):
    # Date-specific generator already produced the 1-pager in Step 1 — skip
    size2 = os.path.getsize(one_out)
    print(f"  ✓ 1-Pager already produced by date-specific generator: {size2:,} bytes")
else:
    # Fallback: run standalone generate_1pager.py (baseline — content may be stale)
    one_script = os.path.join(WS, "generate_1pager.py")
    result2 = subprocess.run(
        [sys.executable, one_script, report_date.strftime("%Y-%m-%d")],
        capture_output=True, text=True, cwd=WS
    )
    if result2.returncode == 0:
        print(f"  ✓ 1-Pager (standalone): {one_out}")
        if os.path.exists(one_out):
            size2 = os.path.getsize(one_out)
            print(f"    Size: {size2:,} bytes")
    else:
        print(f"  ✗ 1-Pager FAILED:\n{result2.stderr}")

# ─── Step 3: Generate data.json + update GitHub Pages ───────────────────────
print("\n[3/3] Updating GitHub Pages site...")
json_script = os.path.join(WS, "generate_dib_json.py")
push_script = os.path.join(WS, "dib_github_push.py")

json_result = subprocess.run(
    [sys.executable, json_script, DATE_FILE],
    capture_output=True, text=True, cwd=WS
)
if json_result.returncode == 0:
    print(f"  ✓ data.json generated")
    print(json_result.stdout.strip())
else:
    print(f"  ✗ data.json FAILED:\n{json_result.stderr}")

push_result = subprocess.run(
    [sys.executable, push_script, DATE_FILE],
    capture_output=True, text=True, cwd=WS
)
if push_result.returncode == 0:
    print(f"  ✓ GitHub Pages updated")
    print(push_result.stdout.strip())
else:
    print(f"  ✗ GitHub push FAILED:\n{push_result.stderr}")

# ─── Step 4: Release Validation ─────────────────────────────────────────────
print("\n[4/4] Running release validation...")
validate_script = os.path.join(WS, "dib_validate_release.py")
validate_result = subprocess.run(
    [sys.executable, validate_script, DATE_FILE],
    capture_output=False, text=True, cwd=WS   # let output stream live
)
if validate_result.returncode != 0:
    print("\n  ⚠  VALIDATION FAILED — review issues above before releasing brief.")
else:
    print("\n  ✅  Validation passed — brief is cleared for release.")

# ─── Summary ──────────────────────────────────────────────────────────────────
print(f"\n{'─'*60}")
print(f"DIB Package Complete — {DATE_STR}")
print(f"{'─'*60}")
files_produced = []
for path in [full_out, one_out]:
    exists = os.path.exists(path)
    status = "✓" if exists else "✗"
    print(f"  {status} {os.path.basename(path)}")
    if exists:
        files_produced.append(path)

print(f"  ✓ GitHub Pages: https://rpr0m3th3us6-a11y.github.io/fs-austin-dib/")
print(f"\nFiles in workspace: {WS}")
print("Done.\n")
