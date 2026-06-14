#!/usr/bin/env python3
"""
GSC לוקאלי — שליפת Search Analytics ל-3 אתרי Pal Group.
שימוש: צרף את ה-ZIP של המפתח, חלץ ל-/home/claude/gsc_secure, ואז:
  python3 gsc_pull.py
דורש דומיינים מאושרים ב-sandbox: oauth2.googleapis.com, www.googleapis.com
הערות סביבה (Claude sandbox):
  - httplib2 לא קורא REQUESTS_CA_BUNDLE, לכן מוגדר httplib2.CA_CERTS ל-CA של ה-egress proxy.
  - משתמש ב-webmasters v3 (לא searchconsole v1), כי searchconsole.googleapis.com לא ב-allowlist.
"""
import glob, json, csv, sys, datetime as dt
import httplib2
httplib2.CA_CERTS = '/etc/ssl/certs/ca-certificates.crt'  # trust egress-gateway CA
from google.oauth2 import service_account
from googleapiclient.discovery import build

KEY=glob.glob('/home/claude/gsc_secure/**/*.json',recursive=True)
if not KEY:
    print("שגיאה: לא נמצא קובץ מפתח. חלץ את ה-ZIP ל-/home/claude/gsc_secure"); sys.exit(1)
KEY=KEY[0]
SCOPES=['https://www.googleapis.com/auth/webmasters.readonly']
creds=service_account.Credentials.from_service_account_file(KEY,scopes=SCOPES)
svc=build('webmasters','v3',credentials=creds,cache_discovery=False)

# auto-detect property format
sites=svc.sites().list().execute().get('siteEntry',[])
print("Properties זמינים:")
for s in sites: print(f"  {s['siteUrl']} [{s['permissionLevel']}]")

end=dt.date.today(); start=end-dt.timedelta(days=365)
TARGETS={}  # alias -> siteUrl, ימולא לפי מה שנמצא
for s in sites:
    u=s['siteUrl']
    for a in ['csb','marom','plrom']:
        if a in u: TARGETS[a]=u

for alias,site in TARGETS.items():
    rows=[]; start_row=0
    while True:
        resp=svc.searchanalytics().query(siteUrl=site,body={
            'startDate':str(start),'endDate':str(end),
            'dimensions':['page'],'rowLimit':25000,'startRow':start_row
        }).execute()
        batch=resp.get('rows',[])
        rows.extend(batch)
        if len(batch)<25000: break
        start_row+=25000
    with open(f'/home/claude/cats/{alias}_gsc.json','w') as f:
        json.dump(rows,f,ensure_ascii=False)
    print(f"{alias}: {len(rows)} עמודים נמשכו")
