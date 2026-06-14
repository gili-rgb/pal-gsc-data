import json, io, subprocess, concurrent.futures as cf, sys, os, time

KEY="WCHldZVT9rBula8L55tb"
alias=sys.argv[1]; domain=sys.argv[2]
BUDGET=float(sys.argv[3]) if len(sys.argv)>3 else 200
CTA="לא מוצאים את החלק"
t0=time.time()

rows=[]
for line in open(f'cats/{alias}.raw.jsonl'):
    rows.extend(json.load(io.StringIO(line.strip())))
seen={r['id']:r for r in rows}; rows=list(seen.values())
ids=[r['id'] for r in rows]

# load checkpoint
ckpt=f'cats/{alias}_results.json'
results={}
if os.path.exists(ckpt):
    results={int(k):v for k,v in json.load(open(ckpt)).items()}
todo=[c for c in ids if c not in results]

def active(cid):
    url=f"https://{domain}/wp-json/wp/v2/product?product_cat={cid}&per_page=10&status=publish&_fields=id,title"
    try:
        r=subprocess.run(["curl","-s","--max-time","15","-H",f"x-pal-key: {KEY}",url],
                         capture_output=True,text=True)
        d=json.loads(r.stdout)
        if isinstance(d,list):
            real=[p for p in d if CTA not in (p.get('title',{}).get('rendered','') if isinstance(p.get('title'),dict) else '')]
            return cid, len(real)
    except: pass
    return cid, None

processed=0
with cf.ThreadPoolExecutor(max_workers=12) as ex:
    futs={ex.submit(active,c):c for c in todo}
    for f in cf.as_completed(futs):
        cid,n=f.result(); results[cid]=n; processed+=1
        if time.time()-t0 > BUDGET:
            # cancel remaining
            for ff in futs:
                ff.cancel()
            break

json.dump({str(k):v for k,v in results.items()}, open(ckpt,'w'))
remaining=len([c for c in ids if c not in results])
print(f"{alias}: סה\"כ {len(ids)} | נסרק עד כה {len(results)} | נותר {remaining} | אצווה זו {processed}")
