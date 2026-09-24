"""Resume after an audited pre-trial quota network failure; never rerun trials."""
import fcntl,os,time
from pathlib import Path
from body_experience_study import ROOT,BATCH,STUDY,read,save,validate,preflight
from body_experience_corrected import run_phase
from prior_materials import write_json
from pause_after_prior_trial import process_info

def main():
    with (BATCH/'recovery.lock').open('a') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with (ROOT/'experiments/.iterations.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            s=read(BATCH/'status.json')
            assert s['status']=='needs_audit' and s['active'] is None
            assert 'account/rateLimits/read' in s['error'] and 'error sending request' in s['error']
            old=process_info(s['pid']);assert old is None or old['state']=='Z'
            validate();quota=preflight()
            assert quota['account_fingerprint']==s['account_fingerprint']
            assert quota['minimum_remaining_percent']>0 and not quota.get('spend_control_reached')
            completed={t['run'] for t in s['completed']}
            pending=[t for b in read(STUDY/'schedule-amendment-001.json')['batches'] for t in b['trials'] if t['run'] not in completed]
            assert pending and not (ROOT/'experiments'/pending[0]['run']).exists()
            record={'at_unix':time.time(),'previous_error':s['error'],'previous_pid':s['pid'],'next_trial':pending[0],'quota':quota,'reason':'Transient pre-trial network failure; fresh preflight passed; no active trial or rerun'}
            s.setdefault('infrastructure_recoveries',[]).append(record)
            write_json(BATCH/'preflight-recovery-001.json',record)
            s.pop('error');s.update(status='schedule_corrected',pid=os.getpid());save(s)
        run_phase('evaluation')
if __name__=='__main__':main()
