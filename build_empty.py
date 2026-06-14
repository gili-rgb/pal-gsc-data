import json, io

SITES=["csb","marom","plrom"]
summary={}

for alias in SITES:
    rows=[]
    for line in open(f'cats/{alias}.raw.jsonl'):
        rows.extend(json.load(io.StringIO(line.strip())))
    seen={r['id']:r for r in rows}; rows=list(seen.values())
    by_id={r['id']:r for r in rows}
    results={int(k):v for k,v in json.load(open(f'cats/{alias}_results.json')).items()}

    def depth(r):
        d=0;p=r['parent']
        while p in by_id: d+=1;p=by_id[p]['parent']
        return d
    def root_brand(r):
        p=r
        while p['parent'] in by_id: p=by_id[p['parent']]
        return p['name']

    empty=[by_id[c] for c,n in results.items() if n==0]
    errs=[c for c,n in results.items() if n is None]
    empty.sort(key=lambda r:(root_brand(r).lower(), depth(r), r['name'].lower()))

    rec=[]
    for r in empty:
        rec.append({"id":r['id'],"name":r['name'],"slug":r['slug'],
                    "depth":depth(r),"brand":root_brand(r),
                    "parent_name":by_id.get(r['parent'],{}).get('name','ROOT'),
                    "count_field":r['count']})
    json.dump(rec, open(f'cats/{alias}_empty_final.json','w'), ensure_ascii=False, indent=2)

    # build readable txt
    with open(f'cats/{alias}_empty.txt','w') as f:
        f.write(f"# קטגוריות ריקות (0 חלפים פעילים) — {alias}\n")
        f.write(f"# סהכ נסרק: {len(results)} | ריקים: {len(empty)} | שגיאות סריקה: {len(errs)}\n")
        f.write(f"# ריק = רק בלוק CTA, אפס חלף אמיתי. מועמד ל-noindex.\n\n")
        # group by brand
        from collections import defaultdict
        g=defaultdict(list)
        for r in rec: g[r['brand']].append(r)
        for brand in sorted(g, key=str.lower):
            items=g[brand]
            f.write(f"## {brand} ({len(items)} ריקים)\n")
            for r in items:
                lvl="שורש" if r['depth']==0 else ("דגם" if r['depth']>=2 else "סוג")
                f.write(f"  [{lvl}] {r['name']}  (id:{r['id']} | slug:{r['slug']} | parent:{r['parent_name']})\n")
            f.write("\n")

    by_depth={}
    for r in rec: by_depth[r['depth']]=by_depth.get(r['depth'],0)+1
    summary[alias]={"scanned":len(results),"empty":len(empty),"errs":len(errs),"by_depth":by_depth}

print(json.dumps(summary, ensure_ascii=False, indent=2))
