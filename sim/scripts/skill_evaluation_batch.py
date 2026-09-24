"""Sequential frozen trials, with persistent pair reviews supplied by thread heartbeat."""
import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import sys
import time

from prepare_skill_evaluation import ROOT, OUT, validate, digest
from account_preflight import preflight
import run_prior_comparison as legacy

BATCH=ROOT/'reports/batches/skill-evaluation-001'

def read(p):return json.loads(Path(p).read_text())
def write(p,value):
    p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_name(p.name+'.next')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');os.replace(temp,p)
def save(s):write(BATCH/'status.json',s)
def lines(p):
    if not p.exists():return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]

def summarize(t,m):
    run=ROOT/'experiments'/t['run']
    prefix=t['condition']+'/'
    expected={f[len(prefix):]:h for f,h in m['inputs_sha256'].items() if f.startswith(prefix)}
    old=legacy.STUDY
    try:
        legacy.STUDY=OUT/'references'/t['point']
        result=legacy.summarize(run,{'sha256':expected})
    finally:legacy.STUDY=old
    for f,h in expected.items():
        assert digest(run/'subject'/f)==h,'Assigned input modified: '+f
    raw=read(run/'private/simulation/result.json')
    usage=[e['params']['tokenUsage']['total'] for e in lines(run/'private/agent-events.jsonl') if e.get('method')=='thread/tokenUsage/updated']
    totals=usage[-1] if usage else None
    # Cumulative whole-session usage includes post-finish closeout. Do not label as task-only.
    token_counts=None if totals is None else {'total':totals.get('totalTokens'),
        'input':totals.get('inputTokens'),'cached_input':totals.get('cachedInputTokens'),
        'output':totals.get('outputTokens'),
        'noncached_input':totals['inputTokens']-totals['cachedInputTokens'] if 'inputTokens' in totals and 'cachedInputTokens' in totals else None}
    skill=[]
    for p in (run/'subject').rglob('calls.jsonl'):
        if '.git' in p.parts:continue
        for row in lines(p):
            if row.get('event')=='end' and row.get('result',{}).get('skill'):
                skill.append({'file':str(p.relative_to(run)),'result':row['result']})
    timing=lines(run/'private/agent-timing.jsonl')
    tools=Counter(e.get('item_type') for e in timing if e.get('event')=='item/completed')
    return {**result,'wrong_button':raw['wrong_button'],'target_pressed':raw['target_pressed'],
            'tokens_whole_session':token_counts,'token_scope':'whole native session including closeout',
            'skill_calls':skill,'skill_call_count':len(skill),'completed_tool_types':dict(tools)}

def aggregate(s):
    rows=s['completed'];conditions={}
    for c in ['E3','SKILL']:
        selected=[r['result'] for r in rows if r['condition']==c]
        if selected:
            conditions[c]={'n':len(selected),'provisional_success_count':sum(r['success_and_correct_declaration'] for r in selected),
                'mean_failure_capped_seconds':statistics.mean(r['failure_capped_score_seconds'] for r in selected),
                'mean_motion_commands':statistics.mean(r['motion_commands'] for r in selected),
                'mean_observation_groups':statistics.mean(r['observation_groups'] for r in selected)}
    write(BATCH/'summary.json',{'conditions':conditions,'trials':rows,'note':'Success proxy still requires image review. Paired trial records, not pooled means, determine per-point comparison.'})
    text=['# Skill 对照实验进度','',f"状态：{s['status']}；已归档 {len(rows)}/24。",'',
          '|运行|点位|重复|条件|成功代理|任务秒|失败封顶秒|动作|观测|skill调用|',
          '|---|---|---:|---|---|---:|---:|---:|---:|---:|']
    for t in rows:
        r=t['result'];text.append(f"|{t['run']}|{t['point']}|{t['repeat']}|{t['condition']}|{r['success_and_correct_declaration']}|{r['native_execution_wall_seconds']:.1f}|{r['failure_capped_score_seconds']:.1f}|{r['motion_commands']}|{r['observation_groups']}|{r['skill_call_count']}|")
    (BATCH/'SUMMARY.zh-CN.md').write_text('\n'.join(text)+'\n')

def pair_gate(s,m):
    pair=s['completed'][-2:]
    assert len(pair)==2 and pair[0]['point']==pair[1]['point'] and pair[0]['repeat']==pair[1]['repeat']
    key=f"r{pair[0]['repeat']}-{pair[0]['point']}"
    path=BATCH/'pair-reviews'/f'{key}.json'
    pending={'pair':key,'runs':[r['run'] for r in pair],'manifest_sha256':s['manifest_sha256'],
             'review_file':str(path),'trial_results':pair,
             'review_fields':['assigned material usage','skill calls and public actions','fresh visual outcome','fault and recovery','time/token differences'],
             'ordinary_failure_is_not_stop_reason':True}
    write(BATCH/'pair-review-pending.json',pending)
    s.update(status='awaiting_pair_review',pending_pair=key,active=None);save(s);aggregate(s)
    while not path.exists():
        s['last_checked_unix']=time.time();save(s);time.sleep(10)
    review=read(path)
    assert review['runs']==pending['runs'] and review['manifest_sha256']==s['manifest_sha256'],'Review refers to another pair/version'
    assert review.get('analysis') and review.get('evidence_files'),'Review must cite actual evidence'
    if review.get('decision')!='continue':raise RuntimeError('Pair review blocked continuation: '+key)
    s.setdefault('reviewed_pairs',[]).append(key);s.pop('pending_pair',None);save(s)

def quota(s):
    while True:
        try:q=preflight()
        except (TimeoutError,RuntimeError) as error:
            if not any(x in str(error).lower() for x in ['timed out','sending request','rate limits','ratelimits','server exited']):raise
            s.update(status='waiting_preflight_network',preflight_error=str(error));save(s);time.sleep(60);continue
        if s.get('account_fingerprint') and q['account_fingerprint']!=s['account_fingerprint']:
            raise RuntimeError('Account changed')
        s['account_fingerprint']=q['account_fingerprint'];s['last_quota']=q;save(s)
        if q['minimum_remaining_percent']<=0 or q.get('spend_control_reached') or q.get('rate_limit_reached_type'):
            s.update(status='waiting_quota');save(s);time.sleep(60);continue
        return q

def worker():
    with (ROOT/'experiments/.iterations.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        m=validate();s=read(BATCH/'status.json')
        assert s['status']=='prepared' and not s['completed'] and s['active'] is None
        assert digest(OUT/'manifest.json')==s['manifest_sha256']
        assert digest(Path(__file__))==s['worker_sha256']
        s.update(pid=os.getpid(),status='starting');save(s);process=None
        def interrupted(signum,frame):raise KeyboardInterrupt(str(signum))
        for sig in [signal.SIGINT,signal.SIGTERM]:signal.signal(sig,interrupted)
        try:
            for index,t in enumerate(m['trials']):
                validate();assert digest(OUT/'manifest.json')==s['manifest_sha256']
                assert shutil.disk_usage(ROOT).free>25*1024**3,'Insufficient disk'
                q=quota(s)
                assert not (ROOT/'experiments'/t['run']).exists(),'Existing attempt must be audited, never overwritten'
                cmd=[sys.executable,'-u',str(ROOT/'scripts/start_skill_trial.py'),t['run']]
                active={**t,'started_unix':time.time(),'quota_before':q,'command':cmd}
                s.update(status='running',active=active);save(s)
                with (BATCH/(t['run']+'.log')).open('x') as log:
                    process=subprocess.Popen(cmd,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    active['pid']=process.pid;save(s)
                    print('START '+t['run']+' '+t['point']+' '+t['condition'],flush=True)
                    while process.poll() is None:
                        if time.time()-active['started_unix']>4500:raise TimeoutError('Trial/export watchdog')
                        s['last_checked_unix']=time.time();save(s);time.sleep(5)
                    if process.returncode:raise RuntimeError('Launcher failed; preserve '+t['run'])
                    process=None
                result=summarize(t,m)
                s['completed'].append({**active,'ended_unix':time.time(),'result':result});s['active']=None;save(s);aggregate(s)
                if (index+1)%2==0:pair_gate(s,m)
            s.update(status='completed_awaiting_final_analysis',ended_unix=time.time());save(s);aggregate(s)
        except BaseException as error:
            if process and process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:process.wait(timeout=60)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGTERM)
            s.update(status='needs_audit',error=repr(error),last_checked_unix=time.time());save(s);raise

def launch():
    validate();assert not BATCH.exists(),'Existing batch must be audited'
    BATCH.mkdir(parents=True)
    s={'status':'prepared','completed':[],'reviewed_pairs':[],'active':None,
       'manifest_sha256':digest(OUT/'manifest.json'),'worker_sha256':digest(Path(__file__)),
       'created_unix':time.time(),'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
    save(s)
    command=['systemd-inhibit','--what=sleep:idle','--mode=block','--why=Run XLeRobot skill comparisons',str(ROOT.parent/'run-local.sh'),'scripts/skill_evaluation_batch.py','worker']
    with (BATCH/'background.log').open('x') as log:
        process=subprocess.Popen(command,cwd=ROOT.parent,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    write(BATCH/'launch.json',{'pid':process.pid,'command':command,'started_unix':time.time()})
    print('Background supervisor PID',process.pid)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['start','worker','check']);a=p.parse_args()
    {'start':launch,'worker':worker,'check':validate}[a.mode]()
