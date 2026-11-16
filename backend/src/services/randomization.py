import hashlib,json

def stratum_targets(sizes,quota):
    """按教学点分层分配辅导名额：每层先对半，再按“离对半最远差最小”贪心调整，
    直到整批名额恰好等于 quota。层内两组人数差在名额约束下尽量小。"""
    targets={c:n//2 for c,n in sizes.items()}
    total=sum(targets.values())
    while total<quota:
        candidates=[c for c in sizes if targets[c]<sizes[c]]
        if not candidates: raise ValueError('辅导名额超过名单人数')
        pick=min(candidates,key=lambda c:(2*targets[c]-sizes[c],c))
        targets[pick]+=1;total+=1
    while total>quota:
        candidates=[c for c in sizes if targets[c]>0]
        if not candidates: raise ValueError('辅导名额不能为负')
        pick=max(candidates,key=lambda c:(2*targets[c]-sizes[c],c))
        targets[pick]-=1;total-=1
    return targets

def assign(roster,quota,seed):
    """stratified-sha256-v1：层内按 sha256(seed:code) 升序排名，取前 t 名进辅导组。
    只依赖封存名单、名额与种子，任何语言可用 SHA-256 独立复算。"""
    sizes={}
    for e in roster: sizes[e['campus']]=sizes.get(e['campus'],0)+1
    targets=stratum_targets(sizes,quota)
    assignments={}
    for campus in sorted(sizes):
        members=sorted((e for e in roster if e['campus']==campus),key=lambda e:e['code'])
        ranked=sorted(members,key=lambda e:hashlib.sha256(f"{seed}:{e['code']}".encode()).hexdigest())
        for i,e in enumerate(ranked):
            assignments[str(e['id'])]='intervention' if i<targets[campus] else 'control'
    return assignments,targets

def commitment(algorithm,seed,quota,roster):
    basis={'algorithm':algorithm,'seed':seed,'quota':quota,'roster':[{'id':e['id'],'code':e['code'],'campus':e['campus']} for e in sorted(roster,key=lambda e:e['code'])]}
    return hashlib.sha256(json.dumps(basis,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
