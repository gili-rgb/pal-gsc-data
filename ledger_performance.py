#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ledger_performance.py — סגירת לולאת המדידה: הצלבת content-ledger.md (Pal-state)
מול נתוני GSC חיים, לכל מאמר שפורסם.

לכל שורת ledger הסקריפט מושך:
  1. ביצועי העמוד עצמו (קליקים/חשיפות/מיקום) — 28 הימים האחרונים מול 28 הקודמים.
  2. מיקום נוכחי לכל שאילתת יעד שנרשמה בשורה.

פלט: cats/ledger-performance.md — הדוח שקובע אילו פורמטים עובדים.

רץ ב-GitHub Actions (gsc-ledger.yml) עם secret GSC_SA_JSON (תוכן קובץ ה-service account).
מקומית: GSC_SA_FILE=/path/to/key.json python3 ledger_performance.py
קונבנציות: webmasters v3 (לא searchconsole v1), auto-detect של פורמט ה-property
(csb/plrom=sc-domain, marom=URL-prefix) — זהה ל-gsc_pull.py.
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

LEDGER_RAW = "https://raw.githubusercontent.com/gili-rgb/Pal-state/{branch}/content-ledger.md"
OUT_DIR = Path(os.environ.get("LP_OUT_DIR", "cats"))
OUT_MD = OUT_DIR / "ledger-performance.md"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
WINDOW = 28  # ימים לחלון השוואה


def get_credentials():
    raw = os.environ.get("GSC_SA_JSON")
    if raw:
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    key_file = os.environ.get("GSC_SA_FILE")
    if key_file and Path(key_file).exists():
        return service_account.Credentials.from_service_account_file(key_file, scopes=SCOPES)
    print("שגיאה: אין GSC_SA_JSON (secret) ואין GSC_SA_FILE", file=sys.stderr)
    sys.exit(1)


def fetch_ledger() -> str:
    for branch in ("main", "master"):
        r = requests.get(LEDGER_RAW.format(branch=branch), timeout=15)
        if r.ok:
            return r.text
    print("שגיאה: content-ledger.md לא נמשך מ-Pal-state", file=sys.stderr)
    sys.exit(1)


def parse_ledger(md: str):
    """שורות בפורמט: | YYYY-MM-DD | אתר | URL | H1 | שאילתות; |  (+עמודת type אופציונלית)"""
    rows = []
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= {"|", "-", " ", ":"}:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5 or not re.match(r"\d{4}-\d{2}-\d{2}", cells[0]):
            continue
        rows.append({
            "date": cells[0],
            "site": cells[1].lower(),
            "url": cells[2],
            "h1": cells[3],
            "queries": [q.strip() for q in cells[4].split(";") if q.strip()],
        })
    return rows


def norm_alias(site: str) -> str:
    s = site.lower()
    if "csb" in s or "סי" in s:
        return "csb"
    if "marom" in s or "מרום" in s:
        return "marom"
    if "plrom" in s or "פלרום" in s:
        return "plrom"
    return s


def query_gsc(svc, prop, body):
    return svc.searchanalytics().query(siteUrl=prop, body=body).execute().get("rows", [])


def page_stats(svc, prop, url, start, end):
    rows = query_gsc(svc, prop, {
        "startDate": str(start), "endDate": str(end),
        "dimensions": ["page"],
        "dimensionFilterGroups": [{"filters": [
            {"dimension": "page", "operator": "equals", "expression": url}]}],
        "rowLimit": 1,
    })
    if not rows:
        # ניסיון שני: URL מקודד/מפוענח (עברית ב-GSC מופיעה percent-encoded)
        alt = urllib.parse.unquote(url) if "%" in url else urllib.parse.quote(url, safe=":/")
        if alt != url:
            rows = query_gsc(svc, prop, {
                "startDate": str(start), "endDate": str(end),
                "dimensions": ["page"],
                "dimensionFilterGroups": [{"filters": [
                    {"dimension": "page", "operator": "equals", "expression": alt}]}],
                "rowLimit": 1,
            })
    if rows:
        r = rows[0]
        return r["clicks"], r["impressions"], round(r["position"], 1)
    return 0, 0, None


def query_position(svc, prop, q, start, end):
    rows = query_gsc(svc, prop, {
        "startDate": str(start), "endDate": str(end),
        "dimensions": ["query"],
        "dimensionFilterGroups": [{"filters": [
            {"dimension": "query", "operator": "equals", "expression": q}]}],
        "rowLimit": 1,
    })
    if rows:
        r = rows[0]
        return round(r["position"], 1), r["impressions"], r["clicks"]
    return None, 0, 0


def fmt(v):
    return "-" if v is None else str(v)


def main() -> int:
    creds = get_credentials()
    svc = build("webmasters", "v3", credentials=creds, cache_discovery=False)
    sites = svc.sites().list().execute().get("siteEntry", [])
    props = {}
    for s in sites:
        u = s["siteUrl"]
        for a in ("csb", "marom", "plrom"):
            if a in u:
                props[a] = u
    print("Properties:", props)

    ledger = parse_ledger(fetch_ledger())
    if not ledger:
        print("ledger ריק — אין מה למדוד. ממלאים את content-ledger.md קודם.", file=sys.stderr)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        OUT_MD.write_text("# Ledger Performance\n\nה-ledger ריק — אין נתונים עדיין.\n", encoding="utf-8")
        return 0

    # GSC data מתעכב ~2-3 ימים
    end = dt.date.today() - dt.timedelta(days=3)
    start = end - dt.timedelta(days=WINDOW - 1)
    prev_end = start - dt.timedelta(days=1)
    prev_start = prev_end - dt.timedelta(days=WINDOW - 1)

    lines = [
        "# Ledger Performance — ביצועי מאמרים שפורסמו",
        "",
        f"עודכן: {dt.date.today().isoformat()} | חלון: {start} עד {end} מול {prev_start} עד {prev_end}",
        "",
        "מקור: content-ledger.md (Pal-state) מוצלב מול GSC. delta = חלון נוכחי מול קודם.",
        "",
    ]
    for alias in ("csb", "marom", "plrom"):
        arts = [r for r in ledger if norm_alias(r["site"]) == alias]
        if not arts:
            continue
        prop = props.get(alias)
        lines += [f"## {alias.upper()} ({len(arts)} מאמרים)", ""]
        if not prop:
            lines += ["_property לא נמצא ב-GSC — דולג_", ""]
            continue
        lines += ["| פורסם | H1 | קליקים (28ד) | Δ | חשיפות | Δ | מיקום עמוד |",
                  "|---|---|---|---|---|---|---|"]
        for art in arts:
            c, i, p = page_stats(svc, prop, art["url"], start, end)
            pc, pi, _ = page_stats(svc, prop, art["url"], prev_start, prev_end)
            lines.append(f"| {art['date']} | {art['h1'][:55]} | {c} | {c - pc:+d} | {i} | {i - pi:+d} | {fmt(p)} |")
        lines += [""]
        # שאילתות יעד
        lines += ["**שאילתות יעד (מיקום נוכחי, כלל-אתר):**", "",
                  "| שאילתה | מיקום | חשיפות | קליקים | מאמר |",
                  "|---|---|---|---|---|"]
        for art in arts:
            for q in art["queries"]:
                pos, imp, clk = query_position(svc, prop, q, start, end)
                lines.append(f"| {q} | {fmt(pos)} | {imp} | {clk} | {art['h1'][:40]} |")
        lines += [""]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"נכתב {OUT_MD} | {len(ledger)} שורות ledger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
