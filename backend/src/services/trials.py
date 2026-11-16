import secrets
from datetime import datetime,timezone
from sqlalchemy import select,update
from fastapi import HTTPException
from src.models.entities import TrialBatch,Student
from src.constants.enums import TRIAL_ALGORITHM
from src.services.randomization import assign,commitment,stratum_targets

def list_batches(db): return db.scalars(select(TrialBatch).order_by(TrialBatch.id.desc())).all()

def get_batch(db,id):
    batch=db.get(TrialBatch,id)
    if not batch: raise HTTPException(404,'随机试验批次不存在')
    return batch

def create_batch(db,data,user):
    codes=list(dict.fromkeys(data.codes))
    students=db.scalars(select(Student).where(Student.code.in_(codes))).all()
    by_code={s.code:s for s in students}
    missing=[c for c in codes if c not in by_code]
    if missing: raise HTTPException(422,'名单包含不存在的学号：'+'、'.join(missing[:5]))
    roster=[{'id':s.id,'code':s.code,'name':s.name,'campus':s.campus} for s in sorted(students,key=lambda x:x.code)]
    n=len(roster)
    if not 1<=data.quota<=n-1: raise HTTPException(422,f'整批辅导名额须在 1 到 {n-1} 之间，保证两组均非空')
    seed=secrets.token_hex(16)
    assignments,targets=assign(roster,data.quota,seed)
    batch=TrialBatch(title=data.title,status='pending',quota=data.quota,algorithm=TRIAL_ALGORITHM,seed=seed,roster=roster,assignments=assignments,commitment=commitment(TRIAL_ALGORITHM,seed,data.quota,roster),created_by=user.email,created_at=datetime.now(timezone.utc).isoformat())
    db.add(batch);db.commit();db.refresh(batch)
    return batch

def reveal_batch(db,id):
    """原子状态翻转：并发揭晓与重试都得到同一结果，且不存在重抽入口。"""
    now=datetime.now(timezone.utc).isoformat()
    db.execute(update(TrialBatch).where(TrialBatch.id==id,TrialBatch.status=='pending').values(status='revealed',revealed_at=now))
    db.commit()
    return get_batch(db,id)

def verify(batch):
    """独立复算：用封存的名单、名额与种子重算分组和承诺哈希，与封存值比对。"""
    assignments,_=assign(batch.roster,batch.quota,batch.seed)
    return {'assignments_match':assignments==batch.assignments,'commitment_match':commitment(batch.algorithm,batch.seed,batch.quota,batch.roster)==batch.commitment,'method':'stratified-sha256-v1：层内按 sha256(seed:code) 升序，取前 t 名为辅导组；t 见分层名额表'}

def analyze(batch,students_by_id):
    """按封存分组聚合原名单内学员的当前成绩（意向性分析口径）。
    分别统计转组、缺考、失访；缺失成绩按 0–100 分插补给出组均差上下界。"""
    rows=[];scores={'control':[],'intervention':[]};missing={'control':0,'intervention':0}
    transferred=absent=lost=0
    for e in batch.roster:
        sealed=batch.assignments[str(e['id'])]
        cur=students_by_id.get(e['id'])
        is_transferred=cur is not None and cur.group!=sealed
        is_absent=cur is not None and cur.absent
        is_lost=cur is None or (cur.score is None and not cur.absent)
        score=cur.score if cur else None
        transferred+=is_transferred;absent+=is_absent;lost+=is_lost
        if score is None: missing[sealed]+=1
        else: scores[sealed].append(score)
        rows.append({'code':e['code'],'name':e['name'],'campus':e['campus'],'sealed_group':sealed,'current_group':cur.group if cur else None,'transferred':is_transferred,'score':score,'absent':is_absent,'lost':is_lost})
    def mean(xs): return sum(xs)/len(xs) if xs else None
    n={g:len(scores[g])+missing[g] for g in scores}
    s={g:sum(scores[g]) for g in scores}
    m0,m1=mean(scores['control']),mean(scores['intervention'])
    complete=None if m0 is None or m1 is None else m1-m0
    low=s['intervention']/n['intervention']-(s['control']+100*missing['control'])/n['control']
    high=(s['intervention']+100*missing['intervention'])/n['intervention']-s['control']/n['control']
    return {'roster_size':len(batch.roster),'transferred':transferred,'absent':absent,'lost':lost,
        'groups':{g:{'n':n[g],'scored':len(scores[g]),'missing':missing[g],'mean':mean(scores[g])} for g in ('control','intervention')},
        'complete_case':{'control_n':len(scores['control']),'intervention_n':len(scores['intervention']),'control_mean':m0,'intervention_mean':m1,'difference':complete},
        'bounds':{'low':low,'high':high,'note':'缺失成绩（缺考+失访）按 0–100 分插补的组均差（辅导−对照）理论上下界；完整样本差另列'},
        'rows':rows}

def serialize_batch(batch):
    return {'id':batch.id,'title':batch.title,'status':batch.status,'quota':batch.quota,'algorithm':batch.algorithm,'commitment':batch.commitment,'roster_size':len(batch.roster),'created_by':batch.created_by,'created_at':batch.created_at,'revealed_at':batch.revealed_at}

def serialize_detail(db,batch):
    data=serialize_batch(batch)
    sizes={}
    for e in batch.roster: sizes[e['campus']]=sizes.get(e['campus'],0)+1
    targets=stratum_targets(sizes,batch.quota)
    data['strata']=[{'campus':c,'size':sizes[c],'intervention':targets[c]} for c in sorted(sizes)]
    data['roster']=batch.roster
    revealed=batch.status=='revealed'
    data['seed']=batch.seed if revealed else None
    data['assignments']=batch.assignments if revealed else None
    data['verification']=verify(batch) if revealed else None
    data['analysis']=analyze(batch,{s.id:s for s in db.scalars(select(Student)).all()}) if revealed else None
    return data
