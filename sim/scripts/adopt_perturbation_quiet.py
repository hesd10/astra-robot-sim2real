"""Close out the unchanged active trial before swapping only its scheduler."""
import os,signal,time
from pathlib import Path
from pause_after_prior_trial import process_info
import position_perturbation_quiet as new
from position_perturbation_summary import summarize as aggregate
from prior_materials import write_json
b=new.BATCH;r=new.read(b/'quiet-continuation-request.json');s=new.read(b/'status.json');parent=r['scheduler_pid'];a=r['active'];child=a['pid']
p=process_info(parent);c=process_info(child)
assert p and p['state']=='T' and c and s['active']['run']==a['run']
assert b'position_perturbation_study.py' in Path(f'/proc/{parent}/cmdline').read_bytes()
write_json(b/'quiet-handoff.json',{'pid':os.getpid(),'status':'waiting_active_trial_exports','run':a['run']})
while True:
 now=process_info(child);assert now and now['started_ticks']==c['started_ticks']
 if now['state']=='Z':break
 time.sleep(5)
try:
 assert now['exit_status']==0,now
 m=new.validate();result=new.summarize(a,m)
 s['completed'].append({**a,'ended_unix':time.time(),'result':result});s['active']=None
 if sum(x['point']==a['point'] for x in s['completed'])==2:s['pairs_done'].append(a['point'])
 s.update(status='quiet_resume',pid=os.getpid(),quiet_amendment='quiet-amendment.json');new.save(s);aggregate()
except BaseException as exc:
 s.update(status='needs_audit',error=repr(exc));new.save(s);raise
finally:
 nowp=process_info(parent);assert nowp and nowp['state']=='T' and nowp['started_ticks']==p['started_ticks']
 os.kill(parent,signal.SIGKILL)
for _ in range(100):
 old=process_info(parent)
 if old is None or old['state']=='Z':break
 time.sleep(.1)
write_json(b/'quiet-handoff.json',{'pid':os.getpid(),'status':'resumed_without_calibration','run':a['run']})
new.worker()
