#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gbp_analyze.py — ניתוח ייצוא Google Business Profile.

למה זה קיים: לחברת שירות עם עשרה סניפים, הכרטיס העסקי הוא מקור ליד ישיר —
שיחות טלפון, בקשות ניווט, וחיפושים מקומיים. עד 2026-08-10 לא היה לנו עליו
שום נתון. GSC אומרת מי הגיע לאתר; GBP אומר מי התקשר בלי להיכנס לאתר בכלל.

GBP API דורש אישור ידני מגוגל שלוקח ימים עד שבועות, ולכן מתחילים מייצוא.

איך מייצאים (פעם בחודש, כ-3 דקות):
  1. business.google.com → בחר פרופיל
  2. Performance (או "ביצועים")
  3. בחר טווח תאריכים — מומלץ 6 חודשים
  4. Download / הורדה → CSV
  5. שמור בשם: gbp_{site}_{branch}.csv  (למשל gbp_csb_lod.csv)
  6. העלה את כל הקבצים לתיקייה אחת והרץ:
       python3 gbp_analyze.py --dir /path/to/exports

הסקריפט מזהה את מבנה הקובץ לבד, כי גוגל משנה כותרות בין גרסאות ובין שפות.
"""
import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

OUT = Path("cats")

# גוגל משנה שמות עמודות בין גרסאות ובין עברית לאנגלית.
# מיפוי לפי מילות מפתch ולא לפי שם מדויק.
FIELD_MAP = {
    "calls": ["call", "שיחות", "טלפון", "phone"],
    "directions": ["direction", "ניווט", "מסלול", "route"],
    "website": ["website", "אתר", "click"],
    "views_search": ["search", "חיפוש"],
    "views_maps": ["maps", "מפות"],
    "bookings": ["booking", "הזמנ"],
    "messages": ["message", "הודע"],
}


def detect(header):
    """זיהוי אילו עמודות קיימות ומה כל אחת מייצגת."""
    found = {}
    for i, col in enumerate(header):
        low = (col or "").strip().lower()
        if not low:
            continue
        for key, words in FIELD_MAP.items():
            if any(w in low for w in words) and key not in found:
                found[key] = i
                break
    date_idx = next((i for i, c in enumerate(header)
                     if any(w in (c or "").lower() for w in ("date", "תאריך", "יום"))), 0)
    return found, date_idx


def num(v):
    if v is None:
        return 0
    s = re.sub(r"[^\d.]", "", str(v))
    try:
        return float(s) if "." in s else int(s or 0)
    except ValueError:
        return 0


def parse_file(path):
    """מחזיר (meta, סכומים, סדרה יומית)."""
    # gbp_csb_lod → site=csb, branch=lod. הרגקס הקודם היה חמדן
    # ובלע את הסניף לתוך שם האתר (csb_lod כאתר).
    name = path.stem.lower()
    parts = [p for p in re.split(r"[_\-\s]+", name) if p and p != "gbp"]
    known = {"csb", "marom", "plrom"}
    site = next((p for p in parts if p in known), parts[0] if parts else "unknown")
    rest = [p for p in parts if p != site]
    branch = " ".join(rest) if rest else "main"

    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        delim = ";" if sample.count(";") > sample.count(",") else ","
        rows = list(csv.reader(f, delimiter=delim))
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if len(rows) < 2:
        return None

    # שורת הכותרת אינה תמיד הראשונה — גוגל מוסיפה שורות מטא למעלה
    hdr_i, fields, date_idx = 0, {}, 0
    for i, r in enumerate(rows[:8]):
        f_, d_ = detect(r)
        if len(f_) > len(fields):
            hdr_i, fields, date_idx = i, f_, d_
    if not fields:
        return None

    totals = defaultdict(int)
    daily = []
    for r in rows[hdr_i + 1:]:
        if len(r) <= max(fields.values()):
            continue
        day = {"date": (r[date_idx] or "").strip()}
        for k, idx in fields.items():
            v = num(r[idx])
            totals[k] += v
            day[k] = v
        daily.append(day)
    return {"site": site, "branch": branch, "file": path.name,
            "fields": list(fields), "totals": dict(totals),
            "days": len(daily), "daily": daily}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    a = ap.parse_args()
    d = Path(a.dir)
    files = sorted(list(d.glob("*.csv")) + list(d.glob("*.CSV")))
    if not files:
        print(f"❌ אין קבצי CSV ב-{d}", file=sys.stderr)
        return 1

    parsed, failed = [], []
    for f in files:
        try:
            r = parse_file(f)
        except Exception as e:
            r, err = None, str(e)[:80]
            failed.append((f.name, err))
            continue
        if r:
            parsed.append(r)
        else:
            failed.append((f.name, "לא זוהו עמודות מוכרות"))

    if not parsed:
        print("❌ אף קובץ לא נותח. שלח לי דוגמה ואתאים את הזיהוי", file=sys.stderr)
        for n, e in failed:
            print(f"   {n}: {e}", file=sys.stderr)
        return 1

    by_site = defaultdict(list)
    for r in parsed:
        by_site[r["site"]].append(r)

    L = ["# Google Business Profile — ביצועים", "",
         f"נוצר: {date.today()} | {len(parsed)} פרופילים", "",
         "**מה זה מוסיף:** GSC מודדת מי הגיע לאתר. כאן רואים מי **התקשר**, ",
         "ביקש ניווט או חיפש את הסניף — לידים שלא עוברים דרך האתר כלל.", ""]

    grand = defaultdict(int)
    for site, items in sorted(by_site.items()):
        L += [f"## {site}", "",
              "| סניף | שיחות | ניווט | קליקים לאתר | צפיות בחיפוש | צפיות במפות |",
              "|---|---|---|---|---|---|"]
        for r in sorted(items, key=lambda x: -x["totals"].get("calls", 0)):
            t = r["totals"]
            for k, v in t.items():
                grand[k] += v
            L.append(f"| {r['branch']} | {t.get('calls', 0)} | {t.get('directions', 0)} | "
                     f"{t.get('website', 0)} | {t.get('views_search', 0)} | "
                     f"{t.get('views_maps', 0)} |")
        L.append("")

        # יחס שיחה לצפייה — המדד שאומר אם הכרטיס עובד
        for r in items:
            t = r["totals"]
            views = t.get("views_search", 0) + t.get("views_maps", 0)
            calls = t.get("calls", 0)
            if views >= 100:
                rate = round(100 * calls / views, 2)
                flag = " ⚠️ נמוך" if rate < 2 else ""
                L.append(f"- **{r['branch']}**: {rate}% מהצופים התקשרו "
                         f"({calls} מתוך {views}){flag}")
        L.append("")

    L += ["---", "", "## סיכום", ""]
    for k, label in [("calls", "שיחות טלפון"), ("directions", "בקשות ניווט"),
                     ("website", "קליקים לאתר"),
                     ("views_search", "צפיות בחיפוש"), ("views_maps", "צפיות במפות")]:
        if grand.get(k):
            L.append(f"- **{label}:** {grand[k]:,}")
    L += ["", "**שיחה מהכרטיס היא ליד ישיר.** אם היחס מתחת ל-2%, הכרטיס ",
          "מקבל חשיפה ולא ממיר — בדוק תמונות, שעות פעילות, ביקורות ותיאור."]

    if failed:
        L += ["", "## קבצים שלא נותחו", ""]
        for n, e in failed:
            L.append(f"- `{n}` — {e}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "gbp_performance.md").write_text("\n".join(L), encoding="utf-8")
    (OUT / "gbp_data.json").write_text(
        json.dumps({"date": str(date.today()), "profiles": parsed},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"נותחו {len(parsed)} פרופילים | שיחות: {grand.get('calls', 0):,} | "
          f"ניווט: {grand.get('directions', 0):,}")
    if failed:
        print(f"⚠️  {len(failed)} קבצים לא נותחו", file=sys.stderr)
    print(f"נכתב: {OUT}/gbp_performance.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
