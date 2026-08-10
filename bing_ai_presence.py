#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bing_ai_presence.py — אבחון נוכחות במנוע שמזין את ChatGPT ו-Copilot.

למה זה קיים, ולמה זה לא "עוד מקור נושאים":
מדידת ai_visibility (2026-08-09) הראתה 5/5 בשאילתות מותג ו-0/4 בשאילתות
טכניות. השאלה שנשארה פתוחה: **למה** מנוע AI לא מצטט אותנו שם.

Bing הוא המנוע שמאחורי ChatGPT ו-Copilot. אם אנחנו לא בעשירייה הראשונה
בו, זו הסיבה — ולא איכות התוכן. זה הופך "לא מצוטטים" מתעלומה לאבחנה.

הכלי מצליב שלושה מקורות שכבר בריפו:
    ai_visibility.json   — על אילו שאילתות Gemini לא ציטט אותנו
    {site}_bing.json     — איפה אנחנו מדורגים ב-Bing
    {site}_page_queries  — איפה אנחנו מדורגים בגוגל

ומחזיר לכל שאילתה: גוגל מול Bing מול ציטוט, ואבחנה.

כלל קריטי (מתועד בזיכרון): AvgImpressionPosition ב-Bing הוא מיקום אמיתי
בשלמים. אסור לחלק ב-10.

הרצה: python3 bing_ai_presence.py
פלט: cats/ai_presence.md
"""
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

CATS = Path(os.environ.get("LP_OUT_DIR", "cats"))
SITES = {"csb": "csb.co.il", "marom": "marom-serv.co.il", "plrom": "plrom.co.il"}
TOP = 10          # עשירייה ראשונה — מה שמנוע AI בפועל שואב ממנו


def load_bing(site):
    """מיצוע לפי שאילתה על פני כל התאריכים."""
    f = CATS / f"{site}_bing.json"
    if not f.exists():
        return {}
    d = json.load(open(f, encoding="utf-8"))
    agg = defaultdict(lambda: {"impr": 0, "clicks": 0, "pos": [], "n": 0})
    for r in d.get("queries", []):
        q = (r.get("Query") or "").strip()
        if not q:
            continue
        a = agg[q]
        a["impr"] += r.get("Impressions", 0)
        a["clicks"] += r.get("Clicks", 0)
        p = r.get("AvgImpressionPosition", 0)
        if p and p > 0:
            a["pos"].append(p)
        a["n"] += 1
    return {q: {"impressions": a["impr"], "clicks": a["clicks"],
                "position": round(sum(a["pos"]) / len(a["pos"]), 1) if a["pos"] else None}
            for q, a in agg.items()}


def load_google(site):
    f = CATS / f"{site}_page_queries.json"
    if not f.exists():
        return {}
    raw = json.load(open(f, encoding="utf-8"))
    best = {}
    for rows in raw.values():
        for r in rows:
            q = r["query"]
            if q not in best or r["position"] < best[q]["position"]:
                best[q] = {"position": round(r["position"], 1),
                           "impressions": r["impressions"]}
    return best


def load_ai():
    f = CATS / "ai_visibility.json"
    if not f.exists():
        return {}
    hist = json.load(open(f, encoding="utf-8"))
    if not hist:
        return {}
    last = hist[-1]
    out = {}
    for site, d in last.get("sites", {}).items():
        for p in d.get("prompts", []):
            out[(site, p["prompt"])] = {
                "cited": p.get("cited", False),
                "competitors": p.get("competitors", []),
                "sources": p.get("total_sources", 0),
            }
    return out


def match_bing(query, bing):
    """התאמה גמישה: Bing לא בהכרח מחזיק את הפרומפט המלא."""
    if query in bing:
        return query, bing[query]
    words = [w for w in re.findall(r"[\u0590-\u05FF\w]{3,}", query)]
    if len(words) < 2:
        return None, None
    best, score = None, 0
    for q in bing:
        hits = sum(1 for w in words if w in q)
        if hits > score and hits >= max(2, len(words) - 2):
            best, score = q, hits
    return (best, bing[best]) if best else (None, None)


def verdict(ai, g, b):
    """האבחנה. זה כל הערך של הכלי."""
    if ai and ai["cited"]:
        return "מצוטט", "אין פעולה"
    gp = g["position"] if g else None
    bp = b["position"] if b else None
    if bp is None and gp is None:
        return "לא נוכח באף מנוע", "פער תוכן — אין עמוד שמכסה את השאילתה"
    if bp is None:
        return "בגוגל בלבד", ("לא מאונדקס ב-Bing. בדוק Bing Webmaster: "
                              "sitemap, IndexNow, חסימות")
    if bp > TOP:
        return f"ב-Bing מקום {bp}", ("זו הסיבה שמנוע AI לא מצטט. "
                                      "Bing מזין את ChatGPT ו-Copilot")
    if gp and gp > TOP:
        return f"ב-Bing {bp}, בגוגל {gp}", "נוכח ב-Bing וחלש בגוגל — חזק את הגוגל"
    return f"בעשירייה בשני המנועים ({bp}/{gp})", \
           "נוכח ולא מצוטט — בעיית תוכן ולא נראות. חסר אבחון/מספרים/מקורות"


def main() -> int:
    ai = load_ai()
    if not ai:
        print("⚠️  אין ai_visibility.json — הרץ קודם את AI Visibility", file=sys.stderr)
    L = ["# נוכחות במנועי AI — אבחון", "",
         f"נוצר: {date.today()}. מקור: `bing_ai_presence.py`.", "",
         "**מה זה עונה:** מדידת ai_visibility אומרת *אם* אנחנו מצוטטים. ",
         "זה אומר **למה לא**. Bing מזין את ChatGPT ו-Copilot; אם איננו ",
         "בעשירייה הראשונה בו, זו הסיבה — לא איכות התוכן.", ""]

    for site, domain in SITES.items():
        bing, goog = load_bing(site), load_google(site)
        if not bing:
            print(f"⚠️  {site}: אין נתוני Bing", file=sys.stderr)
            continue
        prompts = [(s, q) for (s, q) in ai if s == site]
        L += [f"## {site} ({len(bing)} שאילתות ב-Bing)", "",
              "| שאילתה | Gemini | גוגל | Bing | אבחנה |", "|---|---|---|---|---|"]
        weak = []
        for _, q in prompts:
            a = ai[(site, q)]
            g = goog.get(q)
            _, b = match_bing(q, bing)
            state, action = verdict(a, g, b)
            L.append(f"| {q[:38]} | {'✅' if a['cited'] else '❌'} | "
                     f"{g['position'] if g else '—'} | "
                     f"{b['position'] if b else '—'} | {state} |")
            if not a["cited"]:
                weak.append((q, state, action, a.get("competitors", [])))
        L.append("")
        if weak:
            L += ["**שאילתות שאיננו מצוטטים בהן, ומה לעשות:**", ""]
            for q, state, action, comp in weak:
                L.append(f"- **{q}** — {state}")
                L.append(f"  - {action}")
                if comp:
                    L.append(f"  - מצוטטים במקומנו: {', '.join(comp)}")
            L.append("")

        top = sorted((v["impressions"], q, v) for q, v in bing.items()
                     if v["position"] and v["position"] <= TOP)[-8:]
        L += [f"**8 השאילתות החזקות שלנו ב-Bing** (מה שמנוע AI כן רואה):", ""]
        for impr, q, v in reversed(top):
            L.append(f"- `{q[:52]}` — מקום {v['position']}, {impr} חשיפות")
        L.append("")
        print(f"{site}: {len(bing)} שאילתות | {len(weak)} פרומפטים ללא ציטוט")

    CATS.mkdir(parents=True, exist_ok=True)
    (CATS / "ai_presence.md").write_text("\n".join(L), encoding="utf-8")
    print(f"נכתב: {CATS}/ai_presence.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
