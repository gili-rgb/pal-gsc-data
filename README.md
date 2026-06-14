# pal-gsc-data

נתוני GSC וסריקת קטגוריות ל-3 אתרי השירות של Pal Group (CSB / Marom / Plrom).
מזין את content-machine בשפת לקוח אמיתית, זיהוי פערי תוכן, ועמודים חלשים.

## מבנה
- `gsc_pull.py` — שליפת Search Analytics ל-3 האתרים (מתוקן ל-sandbox).
- `build_tree.py`, `build_empty.py`, `scan_batch.py` — סקריפטי סריקה.
- `cats/` — פלט הסריקה: trees, categories, empty-pages, results.

## מה לא נכנס ל-repo (ראה .gitignore)
- מפתח ה-service-account (`pal-gsc-*.json`, `gsc_secure/`).
- פלט GSC רגיש (`*_gsc.json`) — נמשך בזמן ריצה.

## שימוש מתוך sandbox של Claude
```bash
git clone --depth 1 https://github.com/USER/pal-gsc-data /home/claude/pal-gsc
cp -r /home/claude/pal-gsc/cats /home/claude/cats
cp /home/claude/pal-gsc/gsc_pull.py /home/claude/gsc_pull.py
```

## רענון הנתונים (מהמחשב שלך)
לאחר סריקה מחדש:
```bash
git add cats/ && git commit -m "refresh cats" && git push
```
