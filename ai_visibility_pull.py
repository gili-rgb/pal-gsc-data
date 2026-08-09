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
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

OUT_DIR = Path(os.environ.get("LP_OUT_DIR", "cats"))
# סדר ניסיון. 404 על מודל אחד עובר לבא בתור במקום להכשיל את המדידה.
MODELS = [m.strip() for m in os.environ.get(
    "AIV_MODELS", "gemini-2.5-flash,gemini-flash-latest,gemini-2.0-flash"
).split(",") if m.strip()]
MODEL = MODELS[0]
MAX_SECONDS = int(os.environ.get("AIV_MAX_SECONDS", "420"))  # תקציב זמן גלובלי

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


def usable_models(key):
    """
    בוחר מודל מהרשימה החיה במקום לקדד שם קשיח.
    לקח 2026-08-09: `gemini-2.5-flash` הוצא משימוש למשתמשים חדשים והחזיר
    404, למרות שהוא עדיין מופיע ברשימת המודלים. שם מקודד מתיישן; רשימה לא.
    """
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    names = [m["name"].split("/")[-1] for m in data.get("models", [])
             if "generateContent" in (m.get("supportedGenerationMethods") or [])]

    def bad(n):
        return any(x in n for x in ("tts", "image", "embedding", "vision",
                                    "preview", "exp", "thinking", "live"))

    def rank(n):
        ver = 2.5 if "2.5" in n else (2.0 if "2.0" in n else 1.0)
        return (ver, "flash" in n, "lite" not in n, n.count("-") * -1)

    cands = sorted((n for n in names if "flash" in n and not bad(n)),
                   key=rank, reverse=True)
    return cands or [n for n in names if not bad(n)]


def probe(candidates, key):
    """
    בדיקת נסיון אחת בהתחלה. הרשימה החיה מכילה גם מודלים שהוצאו משימוש
    (`gemini-2.5-flash` מופיע ומחזיר 404 "no longer available to new users").
    עדיף לשלם קריאה אחת מראש מאשר 15 קריאות מבוזבזות אחת לכל פרומפט.
    """
    busy = None
    for m in candidates[:6]:
        try:
            body = json.dumps({"contents": [{"parts": [{"text": "היי"}]}]}).encode()
            req = urllib.request.Request(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{m}:generateContent",
                data=body, headers={"Content-Type": "application/json",
                                    "x-goog-api-key": key})
            urllib.request.urlopen(req, timeout=60).read()
            return m                      # 200 — הבחירה הוודאית
        except urllib.error.HTTPError as e:
            if e.code == 429 and busy is None:
                # "זמין אבל עמוס" הוא ניחוש. 429 יכול להגיע גם ממודל מת.
                # שומרים כמועמד אחרון בלבד וממשיכים לחפש מודל שבאמת עונה.
                busy = m
            continue
        except Exception:
            continue
    return busy


def _post(model, prompt, key):
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
    }).encode()
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


REDIRECT_MARKERS = ("vertexaisearch", "grounding-api-redirect")

# GitHub Push Protection חוסם כל מחרוזת שנראית כמו מפתח. מדידת ציטוטים
# לא זקוקה לאף טוקן, ולכן הכלל: שום רצף ארוך וחסר-רווחים לא נכתב.
SECRET_PAT = re.compile(r"AIza[0-9A-Za-z_\-]{20,}|[A-Za-z0-9_\-]{32,}")


def scrub(text):
    """מחליף כל רצף שנראה כמו טוקן ב-[token]. שומר על קריאות הטקסט."""
    return SECRET_PAT.sub("[token]", text) if text else text


def scrub_deep(obj, path="$"):
    """
    ניקוי רקורסיבי על כל המבנה, בנקודה אחת לפני הכתיבה.
    ניקוי שדה-שדה נכשל שלוש פעמים כי תמיד נשאר נתיב שלא חשבתי עליו.
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


def clean_url(u):
    """URL של vertexaisearch לעולם לא נשמר — הטוקן שבו מזוהה כמפתח GCP."""
    if not u or any(m in u for m in REDIRECT_MARKERS):
        return None
    return u


def safe_path(url):
    """דומיין + נתיב בלבד, בלי query, ורק אם לא נשאר בו טוקן."""
    u = clean_url(url)
    if not u:
        return None
    u = u.split("?")[0].split("#")[0]
    return None if SECRET_PAT.search(u) else u


class QuotaExceeded(Exception):
    """מכסה היא מצב פרויקט, לא מצב פרומפט. אין טעם להמשיך."""


def ask(prompt, key):
    """
    לקח 2026-08-09: הכפלתי נסיגה (4 ניסיונות) במודלים (3) בלי לחשב את
    המכפלה — עד 67 דקות ל-15 פרומפטים. הריצה בוטלה אחרי 15 דקות.

    התיקון הוא ארכיטקטוני ולא פרמטרי:
      • 429 הוא מכסה ברמת הפרויקט. מעבר למודל אחר לא עוזר — עוצרים מיד.
      • ניסיון חוזר יחיד על 429, ורק אחרי המתנה קצרה.
      • 404 עובר למודל הבא, בלי נסיגה. זה מצב "מודל לא קיים", לא עומס.
    """
    last = None
    for model in MODELS:
        for attempt in range(2):
            try:
                return _post(model, prompt, key)
            except urllib.error.HTTPError as e:
                try:
                    detail = json.loads(e.read()).get("error", {}).get("message", "")
                except Exception:
                    detail = ""
                last = f"HTTP {e.code}: {detail[:150]}" if detail else f"HTTP {e.code}"
                if e.code == 429:
                    if attempt == 0:
                        time.sleep(20)
                        continue
                    raise QuotaExceeded(last)
                break          # 404 וכל השאר: למודל הבא
            except Exception as e:
                last = str(e)[:150]
                break
    raise RuntimeError(last or "כשל לא ידוע")


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


def diagnose(key):
    """
    שלוש בדיקות שמפרידות בין הסיבות ל-429:
      1. רשימת מודלים — האם המפתח בכלל תקף
      2. קריאה רגילה בלי grounding — האם המכסה הכללית פתוחה
      3. קריאה עם grounding — האם דווקא google_search חסום
    מדפיס את גוף השגיאה המלא, כי שם יושבת הסיבה האמיתית.
    """
    def show(label, fn):
        try:
            fn()
            print(f"✅ {label}")
            return True
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read())
                msg = body.get("error", {}).get("message", "")
                status = body.get("error", {}).get("status", "")
                details = json.dumps(body.get("error", {}).get("details", []),
                                     ensure_ascii=False)[:400]
            except Exception:
                msg = status = details = ""
            print(f"❌ {label} — HTTP {e.code} {status}")
            print(f"   {msg[:300]}")
            if details and details != "[]":
                print(f"   details: {details}")
        except Exception as e:
            print(f"❌ {label} — {str(e)[:200]}")
        return False

    def list_models():
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": key})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
        names = [m["name"].split("/")[-1] for m in d.get("models", [])]
        print(f"   מודלים זמינים: {len(names)}")
        print(f"   רלוונטיים: {[n for n in names if 'flash' in n][:6]}")

    def plain():
        body = json.dumps({"contents": [{"parts": [{"text": "היי"}]}]}).encode()
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{pick[0]}:generateContent",
            data=body, headers={"Content-Type": "application/json",
                                "x-goog-api-key": key})
        urllib.request.urlopen(req, timeout=60).read()

    def grounded():
        _post(pick[0], "מי נותן שירות רשמי לבוש בישראל", key)

    print("=== אבחון Gemini API ===")
    try:
        cands = usable_models(key)
        ok = probe(cands, key)
        pick = ([ok] + [c for c in cands if c != ok]) if ok else cands
        print(f"   מועמדים: {cands[:4]}")
        print(f"   עבר בדיקת נסיון: {ok or 'אף אחד'}")
    except Exception as e:
        pick = MODELS
        print(f"   בחירה אוטומטית נכשלה: {str(e)[:100]}")
    show("1. רשימת מודלים (תקפות המפתח)", list_models)
    show("2. קריאה רגילה, בלי grounding", plain)
    show("3. קריאה עם google_search grounding", grounded)
    print("\nפירוש: 1 נכשל = מפתח לא תקף. 2 עובד ו-3 נכשל = grounding חסום")
    print("        בפרויקט הזה. שניהם נכשלים = המכסה של הפרויקט אפס.")
    return 0


def main() -> int:
    # .strip() חובה: הדבקה לשדה secret ב-GitHub גוררת לעיתים \n בסוף,
    # ואז urllib פוסל את ה-header וכל 15 הקריאות נכשלות (נצפה 2026-08-09).
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        die("אין GEMINI_API_KEY")
    if "--diagnose" in sys.argv or os.environ.get("AIV_DIAGNOSE"):
        return diagnose(key)

    global MODELS
    if not os.environ.get("AIV_MODELS"):
        try:
            live = usable_models(key)
            chosen = probe(live, key) if live else None
            if chosen:
                MODELS = [chosen] + [m for m in live[:3] if m != chosen]
                print(f"מודל שנבחר ואומת: {chosen}")
            elif live:
                MODELS = live[:3]
                print(f"⚠️  אף מודל לא עבר בדיקת נסיון. מנסה: {MODELS}",
                      file=sys.stderr)
        except Exception as e:
            print(f"⚠️  בחירת מודל אוטומטית נכשלה ({str(e)[:80]}), "
                  f"נופל לברירת מחדל {MODELS}", file=sys.stderr)
    if len(key) < 20:
        die(f"GEMINI_API_KEY קצר מדי ({len(key)} תווים) — כנראה הודבק חלקית")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    run = {"date": str(date.today()), "model": MODEL, "engine": "gemini-grounding",
           "sites": {}}
    quota_hit = False
    t0 = time.time()
    for site, prompts in PROMPTS.items():
        dom = OURS[site]
        rows, cited = [], 0
        for q in prompts:
            if quota_hit:
                rows.append({"prompt": q, "error": "דולג — מכסה נגמרה"})
                continue
            try:
                resp = ask(q, key)
            except QuotaExceeded as e:
                quota_hit = True
                print(f"⛔ מכסה נגמרה: {e}", file=sys.stderr)
                rows.append({"prompt": q, "error": str(e)[:150]})
                continue
            except Exception as e:
                # הודעת שגיאה של urllib מכילה את ערך ה-header, כלומר את המפתח.
                # זה מה שהפעיל את GitHub Push Protection שוב ושוב — בצדק.
                msg = str(e).replace(key, "[API_KEY]")
                rows.append({"prompt": q, "error": scrub(msg)[:400]})
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
            if time.time() - t0 > MAX_SECONDS:
                quota_hit = True
                print(f"⏱️  תקציב זמן ({MAX_SECONDS}s) נגמר — עוצר", file=sys.stderr)
                continue
            time.sleep(6)
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
