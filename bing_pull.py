#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bing_pull.py — משיכת נתוני Bing Webmaster Tools ל-3 אתרי Pal Group.
מתלבש על דפוס gsc_pull.py: משיכה per-site, פלט ל-cats/, secrets מחוץ ל-repo.

פלט:
  cats/{alias}_bing.json        — גולמי (queries + pages) לכל אתר
  cats/bing_customer_language.md — מעובד, מאוחד, מוכן לקריאה ע"י content-machine שלב 0

מקור ה-API (מאומת מול Microsoft Learn + analyticsedge):
  endpoint: https://ssl.bing.com/webmaster/api.svc/json/METHOD?apikey=KEY&siteUrl=URL
  תגובה:   JSON עם node "d" (array). שגיאה: {"ErrorCode":N,"Message":...} בלי "d".
  quirks:  (1) AvgImpressionPosition/AvgClickPosition = מיקום אמיתי בשלמים. אין הכפלה ב-10.
               (אומת מול דאטה חי 2026-06: שאילתת מותג מדויקת "csb"/"מרום"/"פלרום" = מקום 4-6.
                ערכים רציפים 1,2,3,4,5..., לא כפולות של 10. מיקום מתחת ל-1 בלתי אפשרי -> אסור לחלק.)
           (2) תאריך בפורמט OData /Date(ms)/ -> regex
           (3) אין date range; חלון קבוע נכון לרגע המשיכה -> לשמור snapshots לאורך זמן
"""
import os, re, sys, glob, json, time
import datetime as dt
import requests

BASE = "https://ssl.bing.com/webmaster/api.svc/json"
TIMEOUT = 30
RETRIES = 3

# דומיין -> alias. מקור האמת לזיהוי אתר.
ALIAS = {
    "csb.co.il": "csb",
    "marom-serv.co.il": "marom",
    "plrom.co.il": "plrom",
}
SITE_NAME = {
    "csb": "CSB (csb.co.il)",
    "marom": "Marom (marom-serv.co.il)",
    "plrom": "Plrom (plrom.co.il)",
}

# Fallback ידני: אם GetUserSites לא מחזיר את ה-siteUrls בפורמט הצפוי,
# מלא כאן את ה-URL המאומת המדויק בכל אתר ב-Bing (כולל http/https + www אם רלוונטי).
# השאר ריק כדי להסתמך על גילוי אוטומטי.
MANUAL_SITES = {
    # "csb":   "https://csb.co.il/",
    # "marom": "https://marom-serv.co.il/",
    # "plrom": "https://plrom.co.il/",
}

OUT_DIR = os.environ.get("BING_OUT_DIR", "/home/claude/cats")


def get_api_key():
    key = os.environ.get("BING_API_KEY")
    if not key:
        for ext in ("txt", "key", "json"):
            cand = glob.glob(f"/home/claude/bing_secure/**/*.{ext}", recursive=True)
            if cand:
                raw = open(cand[0], encoding="utf-8").read().strip()
                # תמיכה גם בקובץ JSON עם שדה apikey
                if raw.startswith("{"):
                    try:
                        raw = json.loads(raw).get("apikey", "").strip()
                    except Exception:
                        raw = ""
                key = raw
                if key:
                    break
    if not key:
        sys.exit("חסר BING_API_KEY (env או /home/claude/bing_secure/). עצירה — לא כותב מהנחות.")
    return key


def call(method, api_key, **params):
    params["apikey"] = api_key
    last = None
    for attempt in range(RETRIES):
        try:
            r = requests.get(f"{BASE}/{method}", params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            last = e
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise RuntimeError(f"{method}: HTTP {r.status_code} — {r.text[:200]}")
        data = r.json()
        if isinstance(data, dict) and "d" in data:
            return data["d"]
        # שגיאת API מגיעה בלי node "d"
        raise RuntimeError(f"{method}: תגובה לא צפויה — {str(data)[:200]}")
    raise RuntimeError(f"{method}: נכשל אחרי {RETRIES} ניסיונות — {last}")


def parse_odata_date(s):
    if not s:
        return None
    m = re.search(r"/Date\((-?\d+)", s)
    if not m:
        return None
    return dt.datetime.fromtimestamp(int(m.group(1)) // 1000).date().isoformat()


def alias_for(url):
    for dom, al in ALIAS.items():
        if dom in (url or ""):
            return al
    return None


def discover_sites(api_key):
    """מחזיר [(alias, site_url)]. קודם GetUserSites, ואז MANUAL_SITES כהשלמה."""
    found = {}
    try:
        sites = call("GetUserSites", api_key)
        for s in sites:
            url = s.get("Url") or s.get("SiteUrl") or s.get("url") or ""
            al = alias_for(url)
            if al and al not in found:
                found[al] = url
    except Exception as e:
        print(f"אזהרה: GetUserSites נכשל ({e}). נופל ל-MANUAL_SITES.", file=sys.stderr)
    for al, url in MANUAL_SITES.items():
        found.setdefault(al, url)
    return [(al, found[al]) for al in ("csb", "marom", "plrom") if al in found]


def aggregate_queries(rows):
    """ה-API מחזיר שורה פר-יום פר-שאילתה. מצרף לפי שאילתה, מתקן position/10."""
    agg = {}
    for q in rows:
        key = q.get("Query", "")
        if not key:
            continue
        a = agg.setdefault(key, {"impr": 0, "clk": 0, "pos": []})
        a["impr"] += q.get("Impressions", 0) or 0
        a["clk"] += q.get("Clicks", 0) or 0
        p = q.get("AvgImpressionPosition")
        if p:
            a["pos"].append(p)  # AvgImpressionPosition = מיקום אמיתי בשלמים (לא מוכפל ב-10). אומת מול דאטה חי: שאילתת מותג מדויקת = מקום 4-6.
    out = []
    for k, v in agg.items():
        avg = round(sum(v["pos"]) / len(v["pos"]), 1) if v["pos"] else None
        out.append((k, v["impr"], v["clk"], avg))
    out.sort(key=lambda x: -x[1])
    return out


def aggregate_pages(rows):
    """GetPageStats מחזיר את ה-URL בשדה Query (quirk מתועד)."""
    agg = {}
    for p in rows:
        key = p.get("Query", "")
        if not key:
            continue
        a = agg.setdefault(key, {"impr": 0, "clk": 0})
        a["impr"] += p.get("Impressions", 0) or 0
        a["clk"] += p.get("Clicks", 0) or 0
    out = [(k, v["impr"], v["clk"]) for k, v in agg.items()]
    out.sort(key=lambda x: -x[1])
    return out


def build_report(per_site):
    today = dt.date.today().isoformat()
    md = [
        "# Bing Webmaster — נתונים חיים לבחירת נושא ושפת לקוח",
        f"עודכן: {today} | מקור: Bing Webmaster API (GetQueryStats + GetPageStats)",
        "הערה: Bing מחזיר חלון זמן קבוע נכון לרגע המשיכה, לא טווח נבחר.",
        "",
    ]
    for alias, q_rows, p_rows in per_site:
        md.append(f"## {SITE_NAME[alias]}")
        md.append("")
        md.append("### יהלומי Bing — שאילתות מובילות (לפי חשיפות)")
        md.append("| שאילתה | חשיפות | קליקים | מיקום ממוצע |")
        md.append("|---|---|---|---|")
        for k, impr, clk, pos in q_rows[:50]:
            md.append(f"| {k} | {impr} | {clk} | {pos if pos is not None else '-'} |")
        md.append("")
        md.append("### עמודים מובילים Bing (לפי חשיפות)")
        md.append("| עמוד | חשיפות | קליקים |")
        md.append("|---|---|---|")
        for k, impr, clk in p_rows[:30]:
            md.append(f"| {k} | {impr} | {clk} |")
        md.append("")
    return "\n".join(md)


def main():
    api_key = get_api_key()
    os.makedirs(OUT_DIR, exist_ok=True)
    targets = discover_sites(api_key)
    if not targets:
        sys.exit("לא נמצאו אתרי Pal מאומתים תחת ה-key. בדוק verification ב-Bing או מלא MANUAL_SITES.")

    per_site = []
    for alias, site_url in targets:
        print(f"מושך {alias} ({site_url}) ...")
        queries = call("GetQueryStats", api_key, siteUrl=site_url)
        pages = call("GetPageStats", api_key, siteUrl=site_url)

        with open(f"{OUT_DIR}/{alias}_bing.json", "w", encoding="utf-8") as f:
            json.dump(
                {"site": site_url, "pulled": dt.date.today().isoformat(),
                 "queries": queries, "pages": pages},
                f, ensure_ascii=False,
            )

        per_site.append((alias, aggregate_queries(queries), aggregate_pages(pages)))

    report = build_report(per_site)
    with open(f"{OUT_DIR}/bing_customer_language.md", "w", encoding="utf-8") as f:
        f.write(report)

    print(f"✓ נמשכו {len(targets)} אתרים. פלט: {OUT_DIR}/bing_customer_language.md + {{alias}}_bing.json")


if __name__ == "__main__":
    main()
