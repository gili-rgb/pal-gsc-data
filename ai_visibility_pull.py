#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_visibility_pull.py — מדידת ציטוטים במנועי AI, אוטומטית.

למה זה קיים: `ai-visibility-audit` הוא המדד היחיד שמודד את מטרת העל — נראות
בציטוטי AI. ה-baseline מ-2026-07-08 נאסף ידנית ולא חזר על עצמו. מדד שנמדד
פעם אחת אינו מדד.

איך: Gemini עם כלי `google_search` מחזיר `groundingMetadata.groundingChunks`
— רשימת המקורות שעליהם התשובה מבוססת. זה בדיוק "מי מצוטט".

שני ממצאים טכניים שמעצבים את המימוש (אומתו 2026-08-06):
  1. `web.uri` מחזיר redirect של vertexaisearch, לא את ה-URL האמיתי.
  2. `web.title` מכיל את **הדומיין** (למשל "csb.co.il"). לשאלה "האם אנחנו
     מצוטטים" זה בדיוק מה שצריך, ובלי לפתור אף redirect.
המימוש מסתמך על הדומיין, ומנסה לפתוח את ה-redirect רק כדי לדעת איזה עמוד
בדיוק צוטט. כשל בפתיחה אינו מפיל את המדידה.

הרצה: GEMINI_API_KEY=... python3 ai_visibility_pull.py
פלט: cats/ai_visibility.json (סדרה עתית) + cats/ai_visibility.md
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

OUT_DIR = Path(os.environ.get("LP_OUT_DIR", "cats"))
MODEL = os.environ.get("AIV_MODEL", "gemini-2.5-flash")
ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
            f"{MODEL}:generateContent")

OURS = {"csb": "csb.co.il", "marom": "marom-serv.co.il", "plrom": "plrom.co.il"}
# ספקי לידים שמתחרים עלינו על אותן שאילתות. מדידת נוכחותם היא חצי מהתמונה.
COMPETITORS = ["midrag.co.il", "pro.co.il", "b144.co.il", "zap.co.il"]

# סט קבוע. אין לשנות בלי bump גרסה — עקביות היא תנאי למגמה.
# מקור: ai-visibility-audit v1.1
PROMPTS = {
    "csb": [
        "מי נותן שירות רשמי לבוש בישראל",
        "תיקון מדיח כלים סימנס",
        "חלקי חילוף מקוריים בוש",
        "טכנאי מכונות כביסה בוש אזור המרכז",
        "מדיח בוש מציג שגיאה E24 מה עושים",
    ],
    "marom": [
        "מי נותן שירות רשמי לשארפ בישראל",
        "מקרר שארפ מצב שבת איך מפעילים",
        "תיקון מייבש כביסה בלומברג",
        "חלקי חילוף האייר",
        "שירות דלונגי תנורים בישראל",
    ],
    "plrom": [
        "מי נותן שירות רשמי למילה בישראל",
        "תיקון מקרר ליבהר",
        "מכונת כביסה מילה לא שואבת מים",
        "חלקי חילוף מילה מקוריים",
        "שירות סאוטר בישראל",
    ],
}


def die(msg):
    print(f"❌ ai_visibility_pull נכשל: {msg}", file=sys.stderr)
    sys.exit(1)


def ask(prompt, key):
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
    }).encode()
    req = urllib.request.Request(
        ENDPOINT, data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


REDIRECT_MARKERS = ("vertexaisearch", "grounding-api-redirect")

# GitHub Push Protection חוסם כל מחרוזת שנראית כמו מפתח. מדידת ציטוטים
# לא זקוקה לאף טוקן, ולכן הכלל הוא: שום רצף ארוך וחסר-רווחים לא נכתב.
# AIza... = מפתח GCP קלאסי. הדפוס השני תופס טוקנים גנריים ב-URL.
SECRET_PAT = re.compile(r"AIza[0-9A-Za-z_\-]{20,}|[A-Za-z0-9_\-]{32,}")


def scrub(text):
    """מחליף כל רצף שנראה כמו טוקן ב-[token]. שומר על קריאות הטקסט."""
    return SECRET_PAT.sub("[token]", text) if text else text


def scrub_deep(obj, path="$"):
    """
    ניקוי רקורסיבי על כל המבנה, בנקודה אחת לפני הכתיבה.
    שלושה סבבים של ניקוי שדה-שדה נכשלו כי תמיד נשאר נתיב שלא חשבתי עליו.
    מדווח את המיקום המדויק כדי שנדע מאיפה זה הגיע.
    """
    if isinstance(obj, str):
        out = scrub(obj)
        if out != obj:
            print(f"   נוקה: {path}", file=sys.stderr)
        return out
    if isinstance(obj, list):
        return [scrub_deep(v, f"{path}[{i}]") for i, v in enumerate(obj)]
    if isinstance(obj, dict):
        return {k: scrub_deep(v, f"{path}.{k}") for k, v in obj.items()}
    return obj


def safe_path(url):
    """
    שומר דומיין + נתיב בלבד, בלי query ובלי fragment, ורק אם אין בו טוקן.
    למדידת ציטוט די בעמוד. פרמטרים הם המקור לכל התראות ה-push protection.
    """
    u = clean_url(url)
    if not u:
        return None
    u = u.split("?")[0].split("#")[0]
    return None if SECRET_PAT.search(u) else u


def clean_url(u):
    """
    URL של vertexaisearch לעולם לא נשמר. הטוקן שבו מזוהה כ-
    "GCP API Key Bound to a Service Account" ו-GitHub חוסם את ה-push.
    זה לא רק שדה `redirect`: כש-HEAD אינו עוקב, `r.url` מחזיר את אותה
    כתובת עצמה, והיא נכנסת דרך שדה `url` (נצפה 2026-08-06).
    """
    if not u or any(m in u for m in REDIRECT_MARKERS):
        return None
    return u


def resolve(uri, timeout=10):
    """פתיחת redirect. כשל אינו מפיל את המדידה — הדומיין מספיק למדידה."""
    try:
        req = urllib.request.Request(uri, method="GET",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return clean_url(r.url)
    except Exception:
        return None


def sources(resp):
    """דומיין + URL אמיתי לכל chunk."""
    out = []
    for c in (resp.get("candidates") or []):
        gm = c.get("groundingMetadata") or {}
        for ch in gm.get("groundingChunks") or []:
            w = ch.get("web") or ch.get("retrievedContext") or {}
            dom = (w.get("domain") or w.get("title") or "").strip().lower()
            uri = w.get("uri", "")
            # ה-redirect של vertexaisearch אינו נשמר. הטוקן שבו נראה כמו
            # "GCP API Key Bound to a Service Account", ו-GitHub Push Protection
            # חוסם את ה-push (נצפה 2026-08-06). אין בו סוד, אבל גם אין בו ערך:
            # הדומיין מודד את הציטוט, וה-URL הסופי מציין איזה עמוד.
            out.append({"domain": scrub(dom), "url": safe_path(resolve(uri))})
    return out


def answer_text(resp):
    parts = []
    for c in (resp.get("candidates") or []):
        for p in (c.get("content") or {}).get("parts") or []:
            if "text" in p:
                parts.append(p["text"])
    return "\n".join(parts)


def main() -> int:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        die("אין GEMINI_API_KEY")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    run = {"date": str(date.today()), "model": MODEL, "engine": "gemini-grounding",
           "sites": {}}
    for site, prompts in PROMPTS.items():
        dom = OURS[site]
        rows, cited = [], 0
        for q in prompts:
            try:
                resp = ask(q, key)
            except Exception as e:
                rows.append({"prompt": q, "error": str(e)[:120]})
                continue
            srcs = sources(resp)
            doms = [s["domain"] for s in srcs]
            hit = [s for s in srcs if dom in (s["domain"] or "")
                   or (s["url"] and dom in s["url"])]
            for h in hit:
                h.setdefault("url", None)
            comp = sorted({d for d in doms for c in COMPETITORS if c in d})
            if hit:
                cited += 1
            rows.append({
                "prompt": q,
                "cited": bool(hit),
                "our_urls": [h["url"] for h in hit if h["url"]],
                "competitors": comp,
                "total_sources": len(srcs),
                "all_domains": sorted(set(d for d in doms if d)),
                "answer_excerpt": scrub(answer_text(resp))[:280],
            })
            time.sleep(2)
        run["sites"][site] = {"domain": dom, "cited": cited,
                              "of": len(prompts), "prompts": rows}
        print(f"{site}: {cited}/{len(prompts)} מצוטטים")

    # שער סופי: שום מחרוזת redirect לא יוצאת לקובץ, מאיזה שדה שלא תגיע.
    # שער סופי על הפלט עצמו, לא על שדה בודד. מדווח מה נתפס, מצונזר.
    def gate(text, label):
        for m in REDIRECT_MARKERS:
            if m in text:
                die(f'"{m}" ב-{label}. באג — לא נכתב דבר.')
        bad = SECRET_PAT.findall(text)
        if bad:
            for b in sorted(set(bad))[:5]:
                print(f"   נתפס ב-{label}: {b[:6]}…{b[-4:]} (אורך {len(b)})",
                      file=sys.stderr)
            die(f"{len(bad)} מחרוזות דמויות-טוקן ב-{label} אחרי ניקוי מלא. "
                f"זה באג אמיתי — לא נכתב דבר.")

    run = scrub_deep(run)
    gate(json.dumps(run, ensure_ascii=False), "json")

    hist_p = OUT_DIR / "ai_visibility.json"
    hist = json.loads(hist_p.read_text(encoding="utf-8")) if hist_p.exists() else []
    hist = [h for h in hist if h.get("date") != run["date"]] + [run]
    hist.sort(key=lambda h: h["date"])
    hist_p.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# נראות בציטוטי AI — סדרה עתית", "",
             "מקור: Gemini + google_search grounding (`ai_visibility_pull.py`, אוטומטי).",
             "**סייג:** תשובת ה-API אינה זהה לתשובת הממשק. המדד עקבי ובר-השוואה",
             "לאורך זמן, אך אינו \"מה שהמשתמש רואה בדפדפן\".", "",
             "| תאריך | CSB | מרום | פלרום | סה\"כ |", "|---|---|---|---|---|"]
    for h in hist:
        c = [h["sites"].get(s, {}) for s in ("csb", "marom", "plrom")]
        tot = sum(x.get("cited", 0) for x in c)
        of = sum(x.get("of", 0) for x in c)
        lines.append(f"| {h['date']} | " +
                     " | ".join(f"{x.get('cited','?')}/{x.get('of','?')}" for x in c) +
                     f" | **{tot}/{of}** |")
    lines += ["", "---", "", f"## פירוט הרצת {run['date']}", ""]
    for site, d in run["sites"].items():
        lines += [f"### {site} ({d['cited']}/{d['of']})", ""]
        for r in d["prompts"]:
            if r.get("error"):
                lines.append(f"- ⚠️ {r['prompt']} — שגיאה: {r['error']}")
                continue
            mark = "✅" if r["cited"] else "❌"
            lines.append(f"- {mark} **{r['prompt']}** — {r['total_sources']} מקורות")
            if r["our_urls"]:
                lines.append(f"  - שלנו: {r['our_urls'][0][:90]}")
            elif r["cited"]:
                lines.append("  - שלנו: צוטט (ה-URL המדויק לא נפתר)")
            if r["competitors"]:
                lines.append(f"  - מתחרים שצוטטו: {', '.join(r['competitors'])}")
        lines.append("")
    md = "\n".join(lines)
    gate(md, "md")
    (OUT_DIR / "ai_visibility.md").write_text(md, encoding="utf-8")
    print(f"נכתב: {OUT_DIR}/ai_visibility.json + ai_visibility.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
