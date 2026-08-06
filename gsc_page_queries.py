#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gsc_page_queries.py — מיפוי URL ← שאילתות אמיתיות, לגיבוי עמודת "שאילתות יעד" ב-content-ledger.

למה זה קיים: עמודת שאילתות היעד ריקה בכל שורות הלדג'ר, ולכן שער ה-dedup עובד ברמת
כותרת ולא ברמת שאילתה. כל סשן מגלה מחדש אשכולות שכבר כוסו. מילוי מ-H1 היה ניחוש;
המקור הדטרמיניסטי הוא GSC עם dimensions=[page, query].

רץ ב-GitHub Actions (gsc-page-queries.yml) עם secret GSC_SA_JSON.
מקומית: GSC_SA_FILE=/path/to/key.json python3 gsc_page_queries.py

פלט:
  cats/{alias}_page_queries.json   — גולמי, לכל עמוד כל השאילתות עם clicks/impressions/position
  cats/ledger_target_queries.md    — טבלת גיבוי מוכנה: URL | שאילתות יעד | חשיפות | מיקום ממוצע

קונבנציות זהות ל-gsc_pull.py ול-ledger_performance.py: webmasters v3, auto-detect של
פורמט ה-property (csb/plrom=sc-domain, marom=URL-prefix).
"""
import datetime as dt
import json
import os
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path

import httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build

# httplib2 לא קורא REQUESTS_CA_BUNDLE — נדרש ל-sandbox של Claude, לא מזיק ב-Actions
httplib2.CA_CERTS = "/etc/ssl/certs/ca-certificates.crt"

OUT_DIR = Path(os.environ.get("LP_OUT_DIR", "cats"))
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
MONTHS = int(os.environ.get("GPQ_MONTHS", "16"))       # GSC שומר עד 16 חודשים
TOP_N = int(os.environ.get("GPQ_TOP_N", "5"))          # שאילתות לשורת ledger
MIN_IMPR = int(os.environ.get("GPQ_MIN_IMPR", "10"))   # רעש מתחת לזה
PAGE_SIZE = 25000


def get_credentials():
    raw = os.environ.get("GSC_SA_JSON")
    if raw:
        return service_account.Credentials.from_service_account_info(
            json.loads(raw), scopes=SCOPES)
    key_file = os.environ.get("GSC_SA_FILE")
    if key_file and Path(key_file).exists():
        return service_account.Credentials.from_service_account_file(key_file, scopes=SCOPES)
    print("שגיאה: אין GSC_SA_JSON (secret) ואין GSC_SA_FILE", file=sys.stderr)
    sys.exit(1)


def fetch_all(svc, prop, start, end):
    """page+query, עם pagination. מחזיר רשימת rows גולמית."""
    rows, start_row = [], 0
    while True:
        resp = svc.searchanalytics().query(siteUrl=prop, body={
            "startDate": str(start), "endDate": str(end),
            "dimensions": ["page", "query"],
            "rowLimit": PAGE_SIZE, "startRow": start_row,
        }).execute()
        batch = resp.get("rows", [])
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        start_row += PAGE_SIZE


def decode(url):
    """permalink עברי מגיע מקודד; מפענחים להשוואה מול הלדג'ר."""
    try:
        return urllib.parse.unquote(url)
    except Exception:
        return url


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    creds = get_credentials()
    svc = build("webmasters", "v3", credentials=creds, cache_discovery=False)

    props = svc.sites().list().execute().get("siteEntry", [])
    # v1.1: הדפסת כל ה-properties. הגרסה הקודמת סיננה בשקט לפי alias, ולכן
    # property של ערוץ יוטיוב (youtube.com/channel/UC...) נזרק בלי הודעה.
    print(f"properties שה-service account רואה ({len(props)}):")
    for e in props:
        print(f"   {e.get('permissionLevel','?'):22s} {e['siteUrl']}")
    targets = {}
    for e in props:
        u = e["siteUrl"]
        low = u.lower()
        if "youtube.com" in low:
            targets["yt_" + (u.rstrip("/").split("/")[-1] or "channel")] = u
            continue
        for a in ("csb", "marom", "plrom"):
            if a in low:
                targets[a] = u
    if not targets:
        print("שגיאה: לא נמצא אף property מתאים", file=sys.stderr)
        return 1
    print("נמשכים: " + ", ".join(sorted(targets)) + "\n")

    end = dt.date.today()
    start = end - dt.timedelta(days=MONTHS * 30)
    lines = ["# מיפוי URL ← שאילתות יעד (מקור: GSC, dimensions=[page, query])", "",
             f"טווח: {start} עד {end} | top {TOP_N} שאילתות לעמוד | סף חשיפות: {MIN_IMPR}", ""]

    for alias, prop in sorted(targets.items()):
        rows = fetch_all(svc, prop, start, end)
        by_page = defaultdict(list)
        for r in rows:
            page, query = r["keys"][0], r["keys"][1]
            if r.get("impressions", 0) < MIN_IMPR:
                continue
            by_page[decode(page)].append({
                "query": query,
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "position": round(r.get("position", 0), 1),
            })

        raw_out = OUT_DIR / f"{alias}_page_queries.json"
        raw_out.write_text(json.dumps(by_page, ensure_ascii=False, indent=1), encoding="utf-8")

        lines += [f"## {alias} ({len(by_page)} עמודים)", "",
                  "| URL | שאילתות יעד | חשיפות | מיקום ממוצע |",
                  "|-----|--------------|--------|--------------|"]
        ranked = sorted(by_page.items(),
                        key=lambda kv: -sum(q["impressions"] for q in kv[1]))
        for page, qs in ranked:
            top = sorted(qs, key=lambda q: -q["impressions"])[:TOP_N]
            impr = sum(q["impressions"] for q in qs)
            pos = round(sum(q["position"] * q["impressions"] for q in qs) / max(impr, 1), 1)
            lines.append(f"| {page} | {'; '.join(q['query'] for q in top)} | {impr} | {pos} |")
        lines.append("")
        print(f"{alias}: {len(rows)} שורות גולמיות, {len(by_page)} עמודים מעל הסף")

    out_md = OUT_DIR / "ledger_target_queries.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"נכתב: {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
