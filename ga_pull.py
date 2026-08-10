#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ga_pull.py — נתוני התנהגות והמרה לכל עמוד, מ-GA4.

למה זה קיים: עד 2026-08-10 כל המערכת מדדה **דירוג וחשיפות**. GSC אומרת מי
לחץ; היא לא אומרת מה קרה אחרי. השאלה "האם המאמרים ממירים" נענתה בהערכה
ולא בנתונים, וזה פער שהיה צריך לעלות הרבה קודם.

GA4 סוגר את הלולאה: כמה נשארו, כמה זמן, וכמה המשיכו לעמוד יצירת קשר או
לאזור האישי. יחד עם GSC מתקבלת התמונה המלאה:
    חשיפות → CTR → כניסה → מעורבות → המרה

הרצה ב-Actions עם secret GSC_SA_JSON (אותו service account, הרשאת Viewer
ב-GA4 Property Access Management).

פלט:
  cats/{alias}_ga.json  — לכל עמוד: משתמשים, מעורבות, זמן, המרות
  cats/ga_performance.md — טבלה קריאה, ממוינת לפי פוטנציאל
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

import httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build

httplib2.CA_CERTS = "/etc/ssl/certs/ca-certificates.crt"

OUT_DIR = Path(os.environ.get("LP_OUT_DIR", "cats"))
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
DAYS = int(os.environ.get("GA_DAYS", "90"))

PROPERTIES = {
    "csb": "465172387",
    "marom": "351474550",
    "plrom": "462885597",
}

# עמודים שכניסה אליהם היא כוונת המרה. מקור: מבנה האתרים ומפת הקישורים.
CONVERSION_PATHS = [
    "/צור-קשר", "/contact", "myarea", "/product/", "/bosch-categories",
    "/siemens-categories", "/constructa-categories", "/gaggenau",
    "-אביזרים-וחלפים", "/brands/",
]


def die(msg):
    print(f"❌ ga_pull נכשל: {msg}", file=sys.stderr)
    sys.exit(1)


def get_service():
    raw = os.environ.get("GSC_SA_JSON")
    if raw:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(raw), scopes=SCOPES)
    else:
        key = os.environ.get("GSC_SA_FILE")
        if not key or not Path(key).exists():
            die("אין GSC_SA_JSON ואין GSC_SA_FILE")
        creds = service_account.Credentials.from_service_account_file(key, scopes=SCOPES)
    return build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)


def run_report(svc, prop, dims, mets, start, end, limit=100000):
    body = {
        "dateRanges": [{"startDate": str(start), "endDate": str(end)}],
        "dimensions": [{"name": d} for d in dims],
        "metrics": [{"name": m} for m in mets],
        "limit": limit,
    }
    r = svc.properties().runReport(property=f"properties/{prop}", body=body).execute()
    rows = []
    for row in r.get("rows", []):
        item = {d: v["value"] for d, v in zip(dims, row.get("dimensionValues", []))}
        for m, v in zip(mets, row.get("metricValues", [])):
            raw = v["value"]
            item[m] = float(raw) if "." in raw else int(raw or 0)
        rows.append(item)
    return rows


def is_conversion(path):
    return any(c in path for c in CONVERSION_PATHS)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    svc = get_service()
    end = dt.date.today()
    start = end - dt.timedelta(days=DAYS)

    lines = ["# ביצועי עמודים — GA4", "",
             f"טווח: {start} עד {end} ({DAYS} ימים). מקור: `ga_pull.py`, אוטומטי.", "",
             "**מה זה מוסיף על GSC:** GSC עוצרת בלחיצה. כאן רואים מה קרה אחריה — ",
             "מעורבות, זמן, וכמה המשיכו לעמוד המרה.", ""]

    all_data = {}
    for alias, prop in PROPERTIES.items():
        try:
            pages = run_report(
                svc, prop, ["pagePath"],
                ["screenPageViews", "activeUsers", "userEngagementDuration",
                 "engagementRate", "bounceRate"], start, end)
        except Exception as e:
            print(f"⚠️  {alias}: {str(e)[:160]}", file=sys.stderr)
            continue

        # מסלולי כניסה → יעד, כדי לדעת לאן מגיעים מהמאמר
        try:
            paths = run_report(
                svc, prop, ["landingPage", "pagePath"], ["sessions"],
                start, end, limit=50000)
        except Exception:
            paths = []

        onward = {}
        for r in paths:
            lp, pp = r.get("landingPage", ""), r.get("pagePath", "")
            if lp and pp and lp != pp and is_conversion(pp):
                onward[lp] = onward.get(lp, 0) + r.get("sessions", 0)

        rows = []
        for p in pages:
            path = p.get("pagePath", "")
            views = p.get("screenPageViews", 0)
            if views < 5:
                continue
            eng = round(p.get("engagementRate", 0) * 100, 1)
            secs = p.get("userEngagementDuration", 0)
            users = p.get("activeUsers", 1) or 1
            rows.append({
                "path": urllib.parse.unquote(path),
                "views": views,
                "users": p.get("activeUsers", 0),
                "engagement_rate": eng,
                "avg_seconds": round(secs / users, 1),
                "bounce_rate": round(p.get("bounceRate", 0) * 100, 1),
                "onward_to_conversion": onward.get(path, 0),
            })
        rows.sort(key=lambda r: -r["views"])
        all_data[alias] = {"property": prop, "days": DAYS, "pages": rows}

        weak = [r for r in rows if r["views"] >= 50 and r["onward_to_conversion"] == 0]
        print(f"{alias}: {len(rows)} עמודים | "
              f"{len(weak)} עם תנועה ואפס המשך להמרה")

        lines += [f"## {alias} ({len(rows)} עמודים)", "",
                  "| עמוד | צפיות | מעורבות | זמן ממוצע | המשך להמרה |",
                  "|---|---|---|---|---|"]
        for r in rows[:40]:
            lines.append(f"| {r['path'][:52]} | {r['views']} | {r['engagement_rate']}% | "
                         f"{r['avg_seconds']}ש | {r['onward_to_conversion']} |")
        lines.append("")
        if weak:
            lines += [f"**{len(weak)} עמודים עם 50+ צפיות ואפס המשך לעמוד המרה:**", ""]
            for r in weak[:15]:
                lines.append(f"- `{r['path'][:60]}` — {r['views']} צפיות, "
                             f"מעורבות {r['engagement_rate']}%")
            lines.append("")

    if not all_data:
        die("אף property לא נמשך. ודא הרשאת Viewer ל-service account ב-GA4")

    for alias, d in all_data.items():
        (OUT_DIR / f"{alias}_ga.json").write_text(
            json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / "ga_performance.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"נכתב: {OUT_DIR}/ga_performance.md + {len(all_data)} קבצי JSON")
    return 0


if __name__ == "__main__":
    sys.exit(main())
