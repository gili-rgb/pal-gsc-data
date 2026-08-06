#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
youtube_pull.py — קטלוג הסרטונים של שלושת הערוצים.

למה זה קיים: properties של ערוצי יוטיוב ב-Search Console אינם מוחזרים מ-sites.list
(אומת 2026-08-06: ה-service account שותף על שלושת הערוצים, ו-sites.list החזיר
שלושה properties של אתרים בלבד). YouTube Data API הוא המקור הנכון, והוא גם עשיר יותר.

המטרה המעשית: content-machine שלב 7, מקור וידאו דרגה 1. במקום שהמודל יחפש סרטון
ויאמת שהערוץ רשמי, preflight מחזיר לו מזהה מאומת מהקטלוג שלנו.

רץ ב-GitHub Actions עם secret GSC_SA_JSON (אותו service account).
מקומית: GSC_SA_FILE=/path/key.json python3 youtube_pull.py

פלט:
  cats/youtube_catalog.json  — כל הסרטונים: מזהה, כותרת, תיאור, תאריך, תגיות
  cats/youtube_videos.md     — טבלה קריאה לכל ערוץ
"""
import json
import os
import re
import sys
from pathlib import Path

import httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build

httplib2.CA_CERTS = "/etc/ssl/certs/ca-certificates.crt"

OUT_DIR = Path(os.environ.get("LP_OUT_DIR", "cats"))
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

# handle → alias של האתר. מקור: קבצי הפרויקט של content-machine.
CHANNELS = {
    "csb": "@csbinc",
    "marom": "@user-marom-serv",
    "plrom": "@plrom",
}


def die(msg):
    print(f"❌ youtube_pull נכשל: {msg}", file=sys.stderr)
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
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def channel_by_handle(svc, handle):
    """forHandle מחזיר את הערוץ לפי ה-@handle, בלי צורך במזהה UC."""
    r = svc.channels().list(part="snippet,contentDetails,statistics",
                            forHandle=handle).execute()
    items = r.get("items", [])
    if not items:
        return None
    c = items[0]
    return {
        "channel_id": c["id"],
        "handle": handle,
        "title": c["snippet"]["title"],
        "uploads_playlist": c["contentDetails"]["relatedPlaylists"]["uploads"],
        "video_count": int(c["statistics"].get("videoCount", 0)),
        "view_count": int(c["statistics"].get("viewCount", 0)),
        "subscribers": c["statistics"].get("subscriberCount", "hidden"),
    }


def all_videos(svc, playlist_id):
    """כל הסרטונים דרך playlist ההעלאות. עלות מכסה נמוכה מ-search.list."""
    vids, token = [], None
    while True:
        r = svc.playlistItems().list(part="snippet,contentDetails",
                                     playlistId=playlist_id,
                                     maxResults=50, pageToken=token).execute()
        for it in r.get("items", []):
            s = it["snippet"]
            vids.append({
                "video_id": it["contentDetails"]["videoId"],
                "title": s["title"].strip(),
                "description": (s.get("description") or "")[:400],
                "published": it["contentDetails"].get("videoPublishedAt", "")[:10],
                "embed": f"https://www.youtube.com/embed/{it['contentDetails']['videoId']}",
                "watch": f"https://www.youtube.com/watch?v={it['contentDetails']['videoId']}",
            })
        token = r.get("nextPageToken")
        if not token:
            return vids


def enrich(svc, vids):
    """תגיות ומשך — שימושי להתאמת סרטון לנושא מאמר."""
    by_id = {v["video_id"]: v for v in vids}
    ids = list(by_id)
    for i in range(0, len(ids), 50):
        r = svc.videos().list(part="snippet,contentDetails,statistics",
                              id=",".join(ids[i:i + 50])).execute()
        for it in r.get("items", []):
            v = by_id.get(it["id"])
            if not v:
                continue
            v["tags"] = it["snippet"].get("tags", [])[:12]
            v["duration"] = it["contentDetails"].get("duration", "")
            v["views"] = int(it["statistics"].get("viewCount", 0))
    return vids


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    svc = get_service()
    catalog, lines = {}, ["# קטלוג סרטוני יוטיוב — Pal Group", "",
                          "מקור: YouTube Data API v3 (youtube_pull.py, אוטומטי).",
                          "שימוש: content-machine שלב 7 — מקור וידאו דרגה 1, מזהה מאומת.", ""]
    for alias, handle in CHANNELS.items():
        ch = channel_by_handle(svc, handle)
        if not ch:
            print(f"⚠️  {alias}: לא נמצא ערוץ ל-{handle}", file=sys.stderr)
            continue
        vids = enrich(svc, all_videos(svc, ch["uploads_playlist"]))
        vids.sort(key=lambda v: -v.get("views", 0))
        ch["videos"] = vids
        catalog[alias] = ch
        print(f"{alias}: {ch['title']} | {len(vids)} סרטונים | "
              f"{ch['view_count']:,} צפיות | {ch['subscribers']} מנויים")
        lines += [f"## {alias} — {ch['title']} ({handle})", "",
                  f"{len(vids)} סרטונים | {ch['view_count']:,} צפיות בערוץ", "",
                  "| צפיות | תאריך | כותרת | מזהה |", "|---|---|---|---|"]
        for v in vids:
            t = v["title"].replace("|", "/")[:70]
            lines.append(f"| {v.get('views',0)} | {v['published']} | {t} | `{v['video_id']}` |")
        lines.append("")

    if not catalog:
        die("אף ערוץ לא נמשך")
    (OUT_DIR / "youtube_catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / "youtube_videos.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"נכתב: {OUT_DIR}/youtube_catalog.json + youtube_videos.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
