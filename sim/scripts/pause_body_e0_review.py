"""Archive the last E0 trial without dispatching experience trials."""
import os, signal, time
from pathlib import Path
from body_experience_study import ROOT,BATCH,read,save,summary,analysis
from prior_materials import write_json
from pause_after_prior_trial import process_info

def main():
    request=read(BATCH/'pause-e0-review.json');s=read(BATCH/'status.json')
    parent=request['scheduler_pid'];active=request['active'];child=active['pid']
    assert s['pid']==parent and s['active']['run']==active['run']
    p=process_info(parent);c=process_info(child)
    assert p and p['state']=='T' and c
    assert b'body_experience_corrected.py' in Path(f'/proc/{parent}/cmdline').read_bytes()
    control={'pid':os.getpid(),'status':'waiting_for_trial_and_exports','run':active['run'],'started_unix':time.time()}
    write_json(BATCH/'pause-e0-controller.json',control)
    while True:
        current=process_info(child)
        assert current and current['started_ticks']==c['started_ticks']
        if current['state']=='Z':break
        time.sleep(5)
    try:
        assert current['exit_status']==0, current
        result=summary(active['run'],active['condition'])
        assert active['run'] not in {t['run'] for t in s['completed']}
        s['completed'].append({**active,'ended_unix':time.time(),'result':result})
        if active['batch'] not in s['batches_done']:s['batches_done'].append(active['batch'])
        s.update(status='paused_e0_review',active=None,resume_automatically=False,paused_unix=time.time(),pause_reason=request['reason'])
        analysis(s)
        control.update(status='paused_e0_review',completed_unix=time.time())
    except Exception as exc:
        s.update(status='paused_e0_review_error',resume_automatically=False,error=repr(exc))
        control.update(status=s['status'],error=repr(exc))
    now=process_info(parent)
    assert now and now['state']=='T' and now['started_ticks']==p['started_ticks']
    os.kill(parent,signal.SIGKILL)
    s['scheduler_retired_after_trial_exit']=True
    save(s);write_json(BATCH/'pause-e0-controller.json',control)
    print(control,flush=True)

if __name__=='__main__':main()
