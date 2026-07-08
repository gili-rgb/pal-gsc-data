#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
autocomplete_pull.py — קציר Google Autocomplete לשלושת אתרי Pal Group.
מטרה: לגלות ביקוש חיפוש בעברית שלא נראה ב-GSC/Bing (שאילתות שהאתרים לא מדורגים בהן בכלל).

רץ ב-GitHub Actions (ראה .github/workflows/autocomplete-pull.yml). אין צורך במפתח API.
פלט: cats/autocomplete_customer_language.md — "יהלומי Autocomplete" = הצעות השלמה
שאינן מופיעות ב-gsc_customer_language.md (ביקוש בלתי נראה).

עיצוב לפי אותם עקרונות של bing_pull.py: stdlib + requests, פלט md אחד, כשל = exit!=0.
"""
import json
import os
import re
import sys
import time
import datetime as dt
from pathlib import Path

import requests

OUT_DIR = Path(os.environ.get("AC_OUT_DIR", "cats"))
GSC_MD = OUT_DIR / "gsc_customer_language.md"
OUT_MD = OUT_DIR / "autocomplete_customer_language.md"

ENDPOINT = "https://suggestqueries.google.com/complete/search"
SLEEP = 0.35          # נימוס בסיסי; ~1,000 בקשות => ~6 דקות
TIMEOUT = 10
RETRIES = 2

# מטריצת הזרעים: מותג/מכשיר בשפת הלקוח (לא שפת יצרן).
SITES = {
    "CSB": {
        "brands": ["בוש", "סימנס", "קונסטרוקטה", "גגנאו", "נף"],
        "devices": ["מדיח כלים", "מכונת כביסה", "מייבש כביסה", "תנור", "מקרר", "כיריים", "קולט אדים", "מיקרוגל"],
    },
    "Marom": {
        "brands": ["שארפ", "בלומברג", "דלונגי", "האייר", "קיצ'נאייד", "מגימיקס", "טפאל"],
        "devices": ["מקרר", "מכונת כביסה", "מייבש כביסה", "תנור", "מדיח כלים", "מזגן", "מעבד מזון", "מיקסר"],
    },
    "Plrom": {
        "brands": ["מילה", "ליבהר", "סאוטר", "פיליפס", "ברוויל"],
        "devices": ["מכונת כביסה", "מייבש כביסה", "מדיח כלים", "מקרר", "תנור", "מכונת קפה", "שואב אבק"],
    },
}

# מודיפיקטורים שמייצרים כוונות שונות. "" = ההצעות הגולמיות לצירוף עצמו.
MODIFIERS = ["", "לא", "תקלה", "איך", "למה", "כמה עולה", "החלפת", "ניקוי", "שירות", "חלקים"]


def fetch_suggestions(q: str) -> list[str]:
    """הצעות Autocomplete לשאילתה אחת. client=firefox מחזיר JSON נקי."""
    params = {"client": "firefox", "hl": "he", "gl": "il", "q": q}
    for attempt in range(RETRIES + 1):
        try:
            r = requests.get(ENDPOINT, params=params, timeout=TIMEOUT,
                             headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            data = json.loads(r.content.decode("utf-8", errors="replace"))
            return [s for s in data[1] if isinstance(s, str)]
        except Exception as e:
            if attempt == RETRIES:
                print(f"  ! נכשל: {q!r}: {e}", file=sys.stderr)
                return []
            time.sleep(2 * (attempt + 1))
    return []


def load_known_terms() -> str:
    """הטקסט המלא של קובץ ה-GSC — לסינון הצעות שכבר מוכרות."""
    if GSC_MD.exists():
        return GSC_MD.read_text(encoding="utf-8")
    print("אזהרה: gsc_customer_language.md לא נמצא — כל ההצעות יסומנו כיהלומים", file=sys.stderr)
    return ""


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def main() -> int:
    known = load_known_terms()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total_req = 0
    lines = [
        "# Autocomplete Customer Language — ביקוש בלתי נראה",
        "",
        f"עודכן: {dt.date.today().isoformat()} (autocomplete_pull.py, אוטומטי)",
        "",
        "מקור: Google Autocomplete (hl=he, gl=il). **יהלום** = הצעה שאינה מופיעה",
        "ב-gsc_customer_language.md, כלומר ביקוש שהאתר לא נחשף אליו כלל ב-GSC.",
        "שימוש ב-content-machine שלב 0/4: מקור שלישי לצד GSC ו-Bing.",
        "",
    ]
    for site, cfg in SITES.items():
        lines += [f"## {site}", ""]
        site_diamonds = 0
        for brand in cfg["brands"]:
            rows = []
            seen = set()
            for device in cfg["devices"]:
                for mod in MODIFIERS:
                    q = f"{device} {brand} {mod}".strip()
                    sugg = fetch_suggestions(q)
                    total_req += 1
                    time.sleep(SLEEP)
                    for s in sugg:
                        s = normalize(s)
                        if not s or s in seen or brand not in s:
                            continue
                        seen.add(s)
                        # יהלום = לא מופיע בקובץ ה-GSC (בדיקת מחרוזת פשוטה ומכוונת-שמרנות)
                        diamond = s not in known
                        rows.append((s, diamond))
            diamonds = [s for s, d in rows if d]
            site_diamonds += len(diamonds)
            if not rows:
                continue
            lines += [f"### {brand}", ""]
            if diamonds:
                lines += ["**יהלומים (לא ב-GSC):**", ""]
                lines += [f"- {s}" for s in diamonds]
                lines += [""]
            rest = [s for s, d in rows if not d]
            if rest:
                lines += ["<details><summary>הצעות שכבר מוכרות מ-GSC (" + str(len(rest)) + ")</summary>", ""]
                lines += [f"- {s}" for s in rest]
                lines += ["", "</details>", ""]
        lines += [f"_סה\"כ יהלומים ל-{site}: {site_diamonds}_", ""]

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"נכתב {OUT_MD} | {total_req} בקשות")
    # sanity: הקובץ חייב להכיל את שלושת האתרים
    txt = OUT_MD.read_text(encoding="utf-8")
    if not all(s in txt for s in SITES):
        print("שגיאה: פלט חסר אתר", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
