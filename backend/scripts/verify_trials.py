"""随机试验批次端到端验证：奇数分层、并发揭晓、独立复算、转组、缺考、失访与缺失成绩上下界。
用法：python -m scripts.verify_trials（默认打 http://localhost:18202 的 nginx 入口）；
直连后端时 VERIFY_BASE_URL=http://localhost:8000 VERIFY_API_PREFIX= python -m scripts.verify_trials
脚本自建学员与批次，不改动演示数据；可重复运行。"""
import os,sys,json,time,hashlib,urllib.request,urllib.error
from concurrent.futures import ThreadPoolExecutor

BASE=os.environ.get('VERIFY_BASE_URL','http://localhost:18202').rstrip('/')+os.environ.get('VERIFY_API_PREFIX','/api')
FAILURES=[]

def check(name,cond,detail=''):
    print(('PASS' if cond else 'FAIL'),name,detail)
    if not cond: FAILURES.append(name)

def req(method,path,token=None,body=None):
    r=urllib.request.Request(BASE+path,method=method,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {})})
    try:
        with urllib.request.urlopen(r) as resp: return resp.status,json.loads(resp.read() or b'null')
    except urllib.error.HTTPError as e:
        return e.code,json.loads(e.read() or b'{}')

def login(email):
    s,d=req('POST','/auth/login',body={'email':email,'password':'Demo123!'})
    assert s==200,(email,d)
    return d['access_token']

def sha(s): return hashlib.sha256(s.encode()).hexdigest()

def recompute_assignments(roster,quota,seed):
    """独立复算 stratified-sha256-v1（仅标准库，与后端实现无关）。"""
    sizes={}
    for e in roster: sizes[e['campus']]=sizes.get(e['campus'],0)+1
    targets={c:n//2 for c,n in sizes.items()}
    total=sum(targets.values())
    while total<quota:
        pick=min([c for c in sizes if targets[c]<sizes[c]],key=lambda c:(2*targets[c]-sizes[c],c))
        targets[pick]+=1;total+=1
    while total>quota:
        pick=max([c for c in sizes if targets[c]>0],key=lambda c:(2*targets[c]-sizes[c],c))
        targets[pick]-=1;total-=1
    out={}
    for campus in sorted(sizes):
        ranked=sorted((e for e in roster if e['campus']==campus),key=lambda e:sha(f"{seed}:{e['code']}"))
        for i,e in enumerate(ranked): out[str(e['id'])]='intervention' if i<targets[campus] else 'control'
    return out,targets

def recompute_commitment(seed,quota,roster):
    basis={'algorithm':'stratified-sha256-v1','seed':seed,'quota':quota,'roster':[{'id':e['id'],'code':e['code'],'campus':e['campus']} for e in sorted(roster,key=lambda e:e['code'])]}
    return hashlib.sha256(json.dumps(basis,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def expected_analysis(rows):
    """按规格独立重算检验结果：封存分组聚合当前成绩，缺失按 0–100 插补上下界。"""
    sc={'control':[],'intervention':[]};miss={'control':0,'intervention':0}
    tr=ab=lo=0
    for r in rows:
        tr+=r['transferred'];ab+=r['absent'];lo+=r['lost']
        if r['score'] is None: miss[r['sealed_group']]+=1
        else: sc[r['sealed_group']].append(r['score'])
    mean=lambda xs: sum(xs)/len(xs) if xs else None
    n={g:len(sc[g])+miss[g] for g in sc};s={g:sum(sc[g]) for g in sc}
    m0,m1=mean(sc['control']),mean(sc['intervention'])
    return {'transferred':tr,'absent':ab,'lost':lo,
        'control_mean':m0,'intervention_mean':m1,
        'difference':None if m0 is None or m1 is None else m1-m0,
        'low':s['intervention']/n['intervention']-(s['control']+100*miss['control'])/n['control'],
        'high':(s['intervention']+100*miss['intervention'])/n['intervention']-s['control']/n['control']}

def close(a,b): return a is not None and b is not None and abs(a-b)<1e-9

def main():
    admin=login('admin@demo.local');viewer=login('viewer@demo.local')
    tag=str(int(time.time()))
    # 1) 自建 9 名学员：城东 5 人（奇数层）、城西 4 人
    students=[]
    for i in range(9):
        campus='城东' if i<5 else '城西'
        s,d=req('POST','/students',admin,{'code':f'ZXV-{tag}-{i+1}','name':f'验证学员{i+1}','campus':campus,'group':'control','score':60.0+i*3.5})
        assert s==201,(s,d);students.append(d)
    codes=[s['code'] for s in students]
    # 2) 参数校验
    s,_=req('POST','/trials',admin,{'title':f'验证批次-{tag}-q0','quota':0,'codes':codes});check('名额为0被拒绝',s==422)
    s,_=req('POST','/trials',admin,{'title':f'验证批次-{tag}-q9','quota':9,'codes':codes});check('名额等于名单人数被拒绝',s==422)
    s,_=req('POST','/trials',admin,{'title':f'验证批次-{tag}-bad','quota':3,'codes':codes+['NO-SUCH-CODE']});check('未知学号被拒绝',s==422)
    s,_=req('POST','/trials',viewer,{'title':f'验证批次-{tag}-v','quota':3,'codes':codes});check('观察员不能创建批次',s==403)
    # 3) 创建批次：奇数分层 + 整批名额
    s,batch=req('POST','/trials',admin,{'title':f'验证批次-{tag}','quota':5,'codes':codes})
    check('创建批次',s==201,str(batch)[:80]);bid=batch['id']
    strata={x['campus']:x for x in batch['strata']}
    check('奇数层人数差≤1',abs(2*strata['城东']['intervention']-5)<=1 and abs(2*strata['城西']['intervention']-4)<=1,str(strata))
    check('整批名额恰好满足',sum(x['intervention'] for x in batch['strata'])==5)
    check('待抽签隐藏种子与分组',batch['seed'] is None and batch['assignments'] is None and batch['analysis'] is None)
    check('承诺哈希已封存',isinstance(batch['commitment'],str) and len(batch['commitment'])==64)
    # 4) 并发揭晓 + 重试幂等
    s,_=req('POST',f'/trials/{bid}/reveal',viewer);check('观察员不能揭晓',s==403)
    with ThreadPoolExecutor(8) as ex: results=list(ex.map(lambda _:req('POST',f'/trials/{bid}/reveal',admin),range(8)))
    check('并发揭晓全部成功',all(s==200 for s,_ in results))
    check('并发揭晓结果一致',len({r['seed'] for _,r in results})==1 and len({r['revealed_at'] for _,r in results})==1)
    s,again=req('POST',f'/trials/{bid}/reveal',admin)
    check('重试揭晓幂等',s==200 and again['seed']==results[0][1]['seed'] and again['revealed_at']==results[0][1]['revealed_at'])
    # 5) 独立复算
    s,detail=req('GET',f'/trials/{bid}',viewer)
    check('揭晓后公开种子',s==200 and detail['seed'])
    exp,targets=recompute_assignments(detail['roster'],5,detail['seed'])
    check('独立复算分组一致',exp==detail['assignments'])
    check('复算分层名额一致',{x['campus']:x['intervention'] for x in detail['strata']}==targets)
    check('独立复算承诺哈希一致',recompute_commitment(detail['seed'],5,detail['roster'])==detail['commitment'])
    check('服务端复算校验通过',detail['verification']['assignments_match'] and detail['verification']['commitment_match'])
    s,export=req('GET',f'/trials/{bid}/export',viewer)
    check('导出与详情一致',s==200 and export['commitment']==detail['commitment'] and export['assignments']==detail['assignments'])
    # 6) 按揭晓结果落组（现实流程：分组揭晓后学员进入各自组），初始应无转组
    def current_rows():
        _,d=req('GET',f'/trials/{bid}',admin)
        return d,d['analysis']
    detail,a=current_rows()
    for row in a['rows']:
        stu=next(x for x in students if x['code']==row['code'])
        s,_=req('PUT',f"/students/{stu['id']}",admin,{'code':stu['code'],'name':stu['name'],'campus':stu['campus'],'group':row['sealed_group'],'score':stu['score']})
        assert s==200,(s,stu)
    detail,a=current_rows()
    exp=expected_analysis(a['rows'])
    check('初始转组/缺考/失访为0',a['transferred']==0 and a['absent']==0 and a['lost']==0)
    check('初始完整样本差一致',close(a['complete_case']['difference'],exp['difference']))
    check('初始上下界一致',close(a['bounds']['low'],exp['low']) and close(a['bounds']['high'],exp['high']))
    # 7) 转组：检验仍按封存分组聚合
    rows=a['rows'];target=next(r for r in rows if r['sealed_group']=='intervention')
    stu=next(s for s in students if s['code']==target['code'])
    s,_=req('PUT',f"/students/{stu['id']}",admin,{'code':stu['code'],'name':stu['name'],'campus':stu['campus'],'group':'control','score':stu['score']})
    check('转组保存',s==200)
    detail,a=current_rows()
    exp=expected_analysis(a['rows'])
    check('转组被单独统计',a['transferred']==1)
    check('转组后仍按封存分组聚合',close(a['complete_case']['difference'],exp['difference']) and close(a['complete_case']['intervention_mean'],exp['intervention_mean']))
    # 8) 缺考：成绩进入缺失，不计入完整样本
    stu2=next(s for s in students if s['code']!=target['code'])
    sealed2=next(r['sealed_group'] for r in a['rows'] if r['code']==stu2['code'])
    s,_=req('PUT',f"/students/{stu2['id']}",admin,{'code':stu2['code'],'name':stu2['name'],'campus':stu2['campus'],'group':sealed2,'score':None,'absent':True})
    check('缺考保存',s==200)
    detail,a=current_rows()
    exp=expected_analysis(a['rows'])
    check('缺考被单独统计',a['absent']==1)
    check('缺考后完整样本差一致',close(a['complete_case']['difference'],exp['difference']))
    check('缺考后上下界一致',close(a['bounds']['low'],exp['low']) and close(a['bounds']['high'],exp['high']))
    # 9) 失访：删除学员记录
    stu3=next(s for s in students if s['code'] not in (target['code'],stu2['code']))
    s,_=req('DELETE',f"/students/{stu3['id']}",admin)
    check('删除学员',s==204)
    detail,a=current_rows()
    exp=expected_analysis(a['rows'])
    check('失访被单独统计',a['lost']==1)
    check('失访后完整样本差一致',close(a['complete_case']['difference'],exp['difference']))
    check('失访后上下界一致',close(a['bounds']['low'],exp['low']) and close(a['bounds']['high'],exp['high']))
    check('缺失插补方向正确',a['bounds']['low']<=a['bounds']['high'])
    # 10) 名单变化不混入半批
    s,_=req('POST','/students',admin,{'code':f'ZXV-{tag}-new','name':'中途转入','campus':'城东','group':'intervention','score':99.0})
    check('新学员录入',s==201)
    detail,a=current_rows()
    check('封存名单不混入新学员',a['roster_size']==9 and all(r['code']!=f'ZXV-{tag}-new' for r in a['rows']))
    # 11) 无重抽入口：再次揭晓种子不变
    s,again=req('POST',f'/trials/{bid}/reveal',admin)
    check('不允许重抽挑结果',s==200 and again['seed']==detail['seed'])
    print()
    if FAILURES: print('FAILED:',FAILURES);sys.exit(1)
    print('ALL CHECKS PASSED')

if __name__=='__main__': main()
