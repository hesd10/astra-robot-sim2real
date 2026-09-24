"""Run the authorized second and third rounds: exactly 18 additional trials."""
import json,os,sys,time,subprocess,fcntl,hashlib
from pathlib import Path
from start_local_feedback_trial import ROOT,OUT,validate as validate_original,hashes,start,preflight
from run_skill_comparison import measure
BATCH=ROOT/'reports/batches/local-feedback-001-repeats'
SCHEDULE_SHA256='a394a729c3f3644017430c889e48ddae388f37be3a44d10a61d80a83394e1c0b'
def validate():
 m=validate_original()
 p=OUT/'REPEATS.json'
 assert hashlib.sha256(p.read_bytes()).hexdigest()==SCHEDULE_SHA256
 r=json.loads(p.read_text())
 assert hashlib.sha256((OUT/'manifest.json').read_bytes()).hexdigest()==r['parent_manifest_sha256']
 return {**m,'trials':r['trials']}
def read(p):return json.loads(p.read_text())
def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);q=p.with_suffix('.next');q.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n');os.replace(q,p)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def summarize(t):
 run=ROOT/'experiments'/t['run'];p=run/'private';r=read(p/'simulation/result.json');a=read(p/'agent-result.json');l=read(p/'launch.json')
 assert a.get('status') in ('completed','environment_ended') and a.get('exit_code')==0,'Agent infrastructure failure'
 assert (a.get('resolved_model'),a.get('reasoning'),l['task_budget_seconds'],l['agent_session_budget_seconds'])==('gpt-6-astra','xhigh',300,480)
 assert r.get('subject_outcome')!='contamination' and r.get('fault') not in ('realtime_overrun','recording_failure','operator_camera_failure','camera_failure','service_exception')
 assert not r.get('recording_error') and not (r.get('operator_monitor') or {}).get('error')
 expected=hashes(OUT/'inputs'/t['condition'])
 assert read(p/'prior-input-audit.json')['sha256']==expected
 for f,h in expected.items():assert digest(run/'subject'/f)==h,'Supplied input modified: '+f
 init=read(p/'simulation/initial-prior-audit.json');assert init['passed'] and init['stage_snapshot_sha256']==digest(OUT/'states'/f'{t["state"]}.json')
 for f in ('dashboard.mp4','follow.mp4','follow-compact.mp4'):assert (p/f).stat().st_size>0
 assert read(p/'dashboard-recording.json')['status']=='saved'
 metrics=measure(run)
 events=[json.loads(x) for x in (p/'agent-events.jsonl').read_text().splitlines() if x.strip()]
 usage=[e['params']['tokenUsage']['total'] for e in events if e.get('method')=='thread/tokenUsage/updated']
 calls=run/'subject/evidence/local-skill-calls.jsonl'
 return dict(metrics=metrics,simulation_result=r,tokens_whole_session=usage[-1] if usage else None,skill_calls=[json.loads(x) for x in calls.read_text().splitlines()] if calls.exists() else [],visual_review_required=True)
def worker():
 s=read(BATCH/'status.json')
 try:
  with (ROOT/'experiments/.iterations.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   assert s['status']=='prepared' and not s['completed']
   previous=read(ROOT/'reports/batches/local-feedback-001/status.json')
   assert len(previous['completed'])==9 and previous['active'] is None
   s['account_fingerprint']=previous['account_fingerprint']
   assert digest(Path(__file__))==s['worker_sha256']
   for t in validate()['trials']:
    while (BATCH/'PAUSE_REQUEST.json').exists():
     s.update(status='paused_by_user');write(BATCH/'status.json',s);time.sleep(10)
    m=validate();assert digest(OUT/'manifest.json')==s['manifest_sha256']
    assert not os.environ.get('ASTRA_BASE_URL')
    q=preflight();assert q['model']==m['model'] and q['effort']==m['effort']
    assert q['minimum_remaining_percent']>0 and not q.get('spend_control_reached') and not q.get('rate_limit_reached_type'),'Quota unavailable'
    if s.get('account_fingerprint'):assert s['account_fingerprint']==q['account_fingerprint']
    s['account_fingerprint']=q['account_fingerprint']
    s.update(status='running',active={**t,'started_unix':time.time()},last_quota=q);write(BATCH/'status.json',s)
    print('START',t,flush=True)
    start(t['run'],input_dir=OUT/'inputs'/t['condition'],reference=OUT/'states'/f'{t["state"]}.json',max_seconds=m['task_seconds'],reasoning=m['effort'])
    validate();result=summarize(t)
    s['completed'].append({**s['active'],'ended_unix':time.time(),'result':result});s['active']=None;write(BATCH/'status.json',s)
    write(BATCH/'results.json',s['completed'])
   s.update(status='completed_awaiting_visual_review',ended_unix=time.time());write(BATCH/'status.json',s)
  print('All 18 additional trials archived; stopped at 27 total.',flush=True)
 except BaseException as e:
  s.update(status='needs_audit',error=repr(e),last_checked_unix=time.time());write(BATCH/'status.json',s);raise

def launch():
 m=validate();assert not BATCH.exists(),'Never overwrite batch'
 assert all(not (ROOT/'experiments'/t['run']).exists() for t in m['trials'])
 from sim_env.dashboard_recording import check_available
 check_available()
 BATCH.mkdir(parents=True)
 write(BATCH/'status.json',dict(status='prepared',completed=[],active=None,manifest_sha256=digest(OUT/'manifest.json'),worker_sha256=digest(Path(__file__)),git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),created_unix=time.time(),authorized_trials=18,schedule_sha256=SCHEDULE_SHA256))
 cmd=['systemd-inhibit','--what=sleep:idle','--mode=block','--why=Run 18 authorized local feedback repetitions',str(ROOT.parent/'run-local.sh'),'scripts/local_feedback_repeats.py','worker']
 with (BATCH/'background.log').open('x') as log:p=subprocess.Popen(cmd,cwd=ROOT.parent,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 write(BATCH/'launch.json',dict(pid=p.pid,command=cmd));print('Started supervisor',p.pid)
if __name__=='__main__':
 {'start':launch,'worker':worker,'check':validate}[sys.argv[1]]()
