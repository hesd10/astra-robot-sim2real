"""Frozen paired perturbation study, with quota-aware sequential execution."""
import argparse,fcntl,json,os,random,shutil,signal,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from prior_materials import digest,hashes,initial_target,write_json
from sim_env.core import Core
from sim_env.setup import load_setup
from prior_service import verify_initial
from account_preflight import preflight
import body_experience_study as prior
import run_prior_comparison as legacy
STUDY=ROOT/'studies/position-perturbation-001';BATCH=ROOT/'reports/batches/position-perturbation-001'
def read(p):return json.loads(Path(p).read_text())
def save(s):
    BATCH.mkdir(parents=True,exist_ok=True)
    temp=BATCH/'status.next.json';write_json(temp,s);os.replace(temp,BATCH/'status.json')
def prepare():
    assert not (STUDY/'manifest.json').exists() and not BATCH.exists()
    pm,inputs=prior.validate();assert read(prior.BATCH/'status.json')['status']=='completed_analyzed'
    pos=read(STUDY/'positions.json');checks=[]
    for p in pos['points']:
        setup=load_setup(STUDY/'setups'/f'{p["id"]}.json');core=Core(**setup['parameters'],max_seconds=1800.)
        folder=STUDY/'references'/p['id'];folder.mkdir(parents=True,exist_ok=False)
        write_json(folder/'private-initial-reference.json',{'public_measurement':initial_target(core.m,core.d),'qpos':core.d.qpos.tolist(),'qvel':core.d.qvel.tolist(),'ctrl':core.d.ctrl.tolist()})
        other=Core(**setup['parameters'],max_seconds=1800.)
        audit=verify_initial(other,folder/'private-initial-reference.json')
        assert max(abs(other.d.body('chassis').xpos[i]-p['world_xy_m'][i]) for i in [0,1])<.001
        checks.append({'point':p['id'],'audit':audit})
    # P1 at all radii first for quota calibration; remaining points in seeded order.
    rng=random.Random(20260921);first=[p for p in pos['points'] if p['id'].endswith('P1')];rest=[p for p in pos['points'] if not p['id'].endswith('P1')];rng.shuffle(rest)
    pairs=[];trials=[]
    for i,p in enumerate(first+rest):
        conditions=['I0E0','I0E3'] if i%2==0 else ['I0E3','I0E0']
        pair={'point':p['id'],'radius_m':p['radius_m'],'conditions':conditions,'phase':'calibration' if i<3 else 'remaining'};pairs.append(pair)
        for c in conditions:trials.append({**pair,'condition':c,'run':'pp001-'+p['id'].lower()+'-'+c.lower(),'pair_index':i+1})
    manifest={'study':'position-perturbation-001','created_unix':time.time(),'model':'gpt-6-astra','effort':'xhigh','task_seconds':1800,'session_seconds':1980,'quota_reserve_percent':10,'pair_order_seed':20260921,'pairs':pairs,'trials':trials,'inputs':{c:{'path':str(prior.STUDY/'inputs'/c),'sha256':inputs[c]} for c in ['I0E0','I0E3']},'positions_sha256':digest(STUDY/'positions.json'),'setups_sha256':hashes(STUDY/'setups'),'references_sha256':hashes(STUDY/'references'),'worker_sha256':digest(__file__),'analysis_sha256':digest(ROOT/'scripts/position_perturbation_summary.py'),'prior_manifest_sha256':digest(prior.STUDY/'manifest.json'),'prior_experience_manifest_sha256':digest(prior.STUDY/'experience-manifest.json'),'same_source':'be001-source-3','no_new_experience':True}
    write_json(STUDY/'manifest.json',manifest);write_json(STUDY/'VALIDATION.json',{'initial_reference_checks':checks,'inputs_reused_exactly':True,'original_trials_unchanged':True,'no_subjects_launched':True})
    save({'status':'prepared','completed':[],'active':None,'created_unix':time.time(),'pairs_done':[],'manifest_sha256':digest(STUDY/'manifest.json'),'transient_preflight_errors':[]})
    print(json.dumps(pairs,indent=2))
def validate():
    m=read(STUDY/'manifest.json');prior.validate()
    for folder,key in [('setups','setups_sha256'),('references','references_sha256')]:assert hashes(STUDY/folder)==m[key]
    assert digest(STUDY/'positions.json')==m['positions_sha256']
    assert digest(__file__)==read(STUDY/'quiet-amendment.json')['worker_sha256']
    assert digest(ROOT/'scripts/position_perturbation_summary.py')==m['analysis_sha256']
    assert digest(prior.STUDY/'manifest.json')==m['prior_manifest_sha256']
    assert digest(prior.STUDY/'experience-manifest.json')==m['prior_experience_manifest_sha256']
    for c,v in m['inputs'].items():assert hashes(v['path'])==v['sha256'],c
    return m

def quota(s,m):
    retries=0
    while True:
        try:q=preflight()
        except (RuntimeError,TimeoutError) as exc:
            message=str(exc)
            if not any(x in message.lower() for x in ['rate limits','ratelimits','sending request','timed out','server exited']):raise
            retries+=1;s['transient_preflight_errors'].append({'time':time.time(),'error':message})
            s.update(status='waiting_preflight_network',last_checked_unix=time.time());save(s);time.sleep(min(300,15*2**min(retries,4)));continue
        assert q['account_fingerprint']==s.get('account_fingerprint',q['account_fingerprint']),'Account changed'
        s['account_fingerprint']=q['account_fingerprint'];s['last_quota']=q
        if q['minimum_remaining_percent']<=m['quota_reserve_percent'] or q.get('spend_control_reached') or q.get('rate_limit_reached_type'):
            s.update(status='waiting_quota',last_checked_unix=time.time());save(s);time.sleep(300);continue
        s.setdefault('quota_at_start',q);return q

def summarize(trial,m):
    # Reuse audited metric extraction, pointing only its private reference check
    # at this point's reference. The legacy module/file itself is unchanged.
    original=legacy.STUDY
    try:
        legacy.STUDY=STUDY/'references'/trial['point']
        result=legacy.summarize(ROOT/'experiments'/trial['run'],{'sha256':m['inputs'][trial['condition']]['sha256']})
    finally:legacy.STUDY=original
    raw=read(ROOT/'experiments'/trial['run']/'private/simulation/result.json')
    return {**result,'wrong_button':raw['wrong_button'],'target_pressed':raw['target_pressed']}

def worker():
    with (ROOT/'experiments/.iterations.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        m=validate();s=read(BATCH/'status.json');assert s['active'] is None and s['status']=='quiet_resume'
        assert s['manifest_sha256']==digest(STUDY/'manifest.json')
        s.update(pid=os.getpid(),status='starting');save(s);process=None
        try:
            for t in m['trials']:
                if t['run'] in {x['run'] for x in s['completed']}:continue
                validate();assert shutil.disk_usage(ROOT).free>25*1024**3,'Insufficient disk'
                q=quota(s,m);run=ROOT/'experiments'/t['run'];assert not run.exists(),'Existing trial requires audit, never overwrite'
                cmd=[sys.executable,'-u',str(ROOT/'scripts/start_prior_experiment.py'),t['run'],'--input-dir',m['inputs'][t['condition']]['path'],'--reference',str(STUDY/'references'/t['point']/'private-initial-reference.json'),'--setup',str(STUDY/'setups'/f'{t["point"]}.json'),'--max-seconds','1800','--reasoning','xhigh']
                active={**t,'started_unix':time.time(),'quota_before':q,'command':cmd};s.update(status='running',active=active);save(s)
                with (BATCH/(t['run']+'.log')).open('x') as log:
                    process=subprocess.Popen(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True);active['pid']=process.pid;save(s)
                    while process.poll() is None:
                        if time.time()-active['started_unix']>4500:raise TimeoutError('Trial/export watchdog')
                        s['last_checked_unix']=time.time();save(s);time.sleep(5)
                    if process.returncode:raise RuntimeError('Launcher failed; preserve and audit '+t['run'])
                    process=None
                result=summarize(t,m);s['completed'].append({**active,'ended_unix':time.time(),'result':result});s['active']=None;save(s)
                from position_perturbation_summary import summarize as aggregate
                aggregate()
                if sum(x['point']==t['point'] for x in s['completed'])==2:s['pairs_done'].append(t['point']);save(s)
            s.update(status='completed_awaiting_review',ended_unix=time.time());save(s)
            aggregate(final=True)
        except BaseException as exc:
            if process and process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:process.wait(timeout=60)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGTERM)
            s.update(status='needs_audit',error=repr(exc),last_checked_unix=time.time());save(s);raise

def launch():
    validate();assert read(BATCH/'status.json')['status']=='prepared'
    directory=BATCH/'launch';directory.mkdir(exist_ok=False)
    cmd=['systemd-inhibit','--what=sleep:idle','--mode=block','--why=Complete paired perturbation trials',str(ROOT.parent/'run-local.sh'),'scripts/position_perturbation_study.py','worker']
    with (directory/'background.log').open('x') as log:p=subprocess.Popen(cmd,cwd=ROOT.parent,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    write_json(directory/'launch.json',{'pid':p.pid,'command':cmd,'started_unix':time.time()});print(p.pid)
if __name__=='__main__':
    mode=sys.argv[1]
    {'prepare':prepare,'validate':validate,'start':launch,'worker':worker}[mode]()
