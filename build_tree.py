import json, sys, csv, io

def load(alias):
    rows=[]
    try:
        with open(f"cats/{alias}.raw.jsonl") as f:
            for line in f:
                line=line.strip()
                if not line: continue
                rows.extend(json.load(io.StringIO(line)))
    except FileNotFoundError:
        return []
    # dedupe by id
    seen={}
    for r in rows: seen[r["id"]]=r
    return list(seen.values())

def build(alias):
    rows=load(alias)
    if not rows: return None
    by_id={r["id"]:r for r in rows}
    children={}
    for r in rows:
        children.setdefault(r["parent"],[]).append(r)
    for k in children:
        children[k].sort(key=lambda x:x["name"].lower())

    lines=[]
    def walk(pid, depth):
        for r in children.get(pid,[]):
            indent="  "*depth
            lines.append(f'{indent}- {r["name"]} (id:{r["id"]} | slug:{r["slug"]} | count:{r["count"]})')
            walk(r["id"], depth+1)
    walk(0,0)

    # stats
    roots=children.get(0,[])
    total=len(rows)
    total_products=sum(r["count"] for r in rows)
    # depth
    def depth_of(r):
        d=0; p=r["parent"]
        while p in by_id:
            d+=1; p=by_id[p]["parent"]
        return d
    maxdepth=max((depth_of(r) for r in rows), default=0)

    with open(f"cats/{alias}_tree.txt","w") as f:
        f.write(f"# עץ קטגוריות מלא — {alias}\n")
        f.write(f"# סך קטגוריות: {total} | סך שיוכי מוצרים: {total_products} | עומק מרבי: {maxdepth+1} רמות\n")
        f.write(f"# קטגוריות שורש: {len(roots)}\n\n")
        f.write("\n".join(lines))

    # CSV flat
    with open(f"cats/{alias}_categories.csv","w",newline="") as f:
        w=csv.writer(f)
        w.writerow(["id","name","slug","parent_id","parent_name","count","depth"])
        for r in sorted(rows,key=lambda x:(x["parent"],x["name"].lower())):
            pn=by_id.get(r["parent"],{}).get("name","ROOT")
            w.writerow([r["id"],r["name"],r["slug"],r["parent"],pn,r["count"],depth_of(r)])

    return dict(total=total,products=total_products,roots=len(roots),depth=maxdepth+1)

for a in ["csb","marom","plrom"]:
    s=build(a)
    if s: print(f"{a}: {s['total']} קטגוריות, {s['products']} שיוכים, {s['roots']} שורשים, עומק {s['depth']}")
    else: print(f"{a}: אין נתונים (403)")
