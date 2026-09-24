"""Scheduling-only correction: complete all E0 repeats before experience trials."""
import argparse,fcntl,json,os,shutil,signal,subprocess,sys,time
from pathlib import Path
from body_experience_study import ROOT,STUDY,BATCH,read,save,validate,summary,analysis,preflight
from prior_materials import write_json
from pause_after_prior_trial import process_info

def adopt():
    request=read(BATCH/'schedule-correction.json');s=read(BATCH/'status.json')
    parent=request['scheduler_pid'];child=request['launcher_pid']
    assert s['pid']==parent and s['active']['pid']==child
    p=process_info(parent);c=process_info(child)
    assert p and p['state']=='T' and c
    assert b'body_experience_study.py' in Path(f'/proc/{parent}/cmdline').read_bytes()
    start=time.time()
    while True:
        now=process_info(child)
        if not now or now['started_ticks']!=c['started_ticks']:raise RuntimeError('Launcher unexpectedly disappeared')
        if now['state']=='Z':break
        if time.time()-start>900:raise RuntimeError('Interrupted launcher closeout watchdog')
        time.sleep(5)
    assert process_info(parent)['state']=='T'
    evidence=ROOT/'experiments'/request['trial']['run']/'private'
    result=read(evidence/'simulation/result.json') if (evidence/'simulation/result.json').exists() else None
    s.setdefault('excluded_operator_interruptions',[]).append({**request['trial'],'reason':request['reason'],'interrupted_unix':request['requested_unix'],'closed_unix':time.time(),'launcher_exit_status':now['exit_status'],'preserved_result':result,'replacement_run':request['trial']['run']+'-rescheduled'})
    os.kill(parent,signal.SIGKILL)
    s.update(status='schedule_corrected',active=None,pid=os.getpid(),schedule_amendment='schedule-amendment-001.json')
    save(s)
    # The retired scheduler releases the shared lock before our worker acquires it.
    for _ in range(50):
        x=process_info(parent)
        if x is None or x['state']=='Z':break
        time.sleep(.1)

def run_phase(phase):
    with (ROOT/'experiments/.iterations.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        m,inputs=validate();s=read(BATCH/'status.json')
        if s.get('active'):raise RuntimeError('Active or interrupted trial requires audit; never rerun silently')
        assert phase=='evaluation'
        if s['status']!='schedule_corrected':raise RuntimeError('Expected corrected schedule')
        batches=read(STUDY/'schedule-amendment-001.json')['batches']
        process=None
        try:
            for batch in batches:
                for trial in batch['trials']:
                    if trial['run'] in {t['run'] for t in s['completed']}:continue
                    validate()
                    if shutil.disk_usage(ROOT).free < 15*1024**3:raise RuntimeError('Insufficient free disk')
                    quota=preflight()
                    if quota['minimum_remaining_percent']<=0 or quota.get('spend_control_reached'):raise RuntimeError('Quota unavailable; no reset credits authorized')
                    if s.get('account_fingerprint',quota['account_fingerprint'])!=quota['account_fingerprint']:raise RuntimeError('Account changed')
                    s['account_fingerprint']=quota['account_fingerprint']
                    name=trial['run'];condition=trial['condition']
                    if (ROOT/'experiments'/name).exists():raise RuntimeError('Trial exists: '+name)
                    cmd=[sys.executable,'-u',str(ROOT/'scripts/start_prior_experiment.py'),name,'--input-dir',str(STUDY/'inputs'/condition),'--reference',str(STUDY/'private-initial-reference.json'),'--setup',str(ROOT/'setups/formal-001.json'),'--max-seconds','1800','--reasoning','xhigh']
                    active={**trial,'phase':phase,'batch':batch['id'],'started_unix':time.time(),'quota_before':quota,'command':cmd}
                    s.update(status='running_'+phase,pid=os.getpid(),active=active);save(s)
                    with (BATCH/(name+'.log')).open('x') as log:
                        process=subprocess.Popen(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
                        active['pid']=process.pid;save(s)
                        while process.poll() is None:
                            if time.time()-active['started_unix']>4500:raise TimeoutError('Launcher/export watchdog')
                            s['last_checked_unix']=time.time();save(s);time.sleep(5)
                        if process.returncode:raise RuntimeError('Launcher failure '+name)
                        process=None
                    result=summary(name,condition)
                    s['completed'].append({**active,'ended_unix':time.time(),'result':result});s['active']=None;save(s);analysis(s)
                if batch['id'] not in s['batches_done']:s['batches_done'].append(batch['id'])
                save(s)
                write_json(BATCH/(batch['id']+'-checkpoint.json'),{'completed_unix':time.time(),'input_integrity_passed':True,'completed_trials':len(s['completed']),'continue_authorized':True})
            if phase=='source':
                valid=[t for t in s['completed'] if t['phase']=='source' and t['result']['success_and_correct_declaration']]
                if valid:
                    chosen=min(valid,key=lambda t:(t['result']['sim_seconds'],t['run']))
                    s.update(status='awaiting_experience',selected_source=chosen['run'])
                else:s['status']='source_unavailable'
            else:s['status']='completed_awaiting_analysis'
            s['ended_unix']=time.time();save(s)
        except BaseException as exc:
            if process and process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:process.wait(timeout=45)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGTERM)
            s.update(status='needs_audit',error=repr(exc));save(s);raise

if __name__=='__main__':
    if '--worker' in sys.argv:
        adopt()
        run_phase('evaluation')
    else:
        directory=BATCH/'schedule-corrected-launch';directory.mkdir(exist_ok=False)
        command=['systemd-inhibit','--what=sleep:idle','--mode=block','--why=Complete all E0 repeats before experience',str(ROOT.parent/'run-local.sh'),'scripts/body_experience_corrected.py','--worker']
        with (directory/'background.log').open('x') as log:
            process=subprocess.Popen(command,cwd=ROOT.parent,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        write_json(directory/'launch.json',{'pid':process.pid,'command':command,'started_unix':time.time()})
        print(process.pid)
