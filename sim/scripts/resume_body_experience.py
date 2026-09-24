"""Resume the frozen amended schedule after the user-authorized E0 review."""
import fcntl,os,time
from body_experience_study import ROOT,BATCH,read,save,validate
from body_experience_corrected import run_phase
from prior_materials import write_json
from pause_after_prior_trial import process_info

def main():
    with (BATCH/'resume-e0.lock').open('a') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        write_json(BATCH/'resume-e0-controller.json',{'pid':os.getpid(),'status':'waiting_for_e0_archive','authorized_unix':time.time()})
        deadline=time.time()+1800
        while True:
            s=read(BATCH/'status.json')
            if s['status']=='paused_e0_review':break
            assert s['status']=='running_evaluation' and s['active']['run']=='be001-r3-i1e0',s['status']
            c=read(BATCH/'pause-e0-controller.json');p=process_info(c['pid'])
            assert p and p['state']!='Z','Pause archive controller no longer running'
            assert time.time()<deadline,'Archive wait exceeded 30 minutes'
            time.sleep(5)
        validate()
        done=[t for t in s['completed'] if t['phase']=='evaluation']
        assert len(done)==12 and all(t['condition'].endswith('E0') for t in done)
        assert s['active'] is None
        for _ in range(100):
            p=process_info(s['pid'])
            if p is None or p['state']=='Z':break
            time.sleep(.1)
        else:raise RuntimeError('Old scheduler has not retired')
        s.update(status='schedule_corrected',pid=os.getpid(),resume_automatically=True,resumed_unix=time.time(),resume_reason='User authorized continuation after E0 review')
        save(s)
        write_json(BATCH/'resume-e0-controller.json',{'pid':os.getpid(),'status':'resumed','resumed_unix':time.time()})
        run_phase('evaluation')
if __name__=='__main__':main()
