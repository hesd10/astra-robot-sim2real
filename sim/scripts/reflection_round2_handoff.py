"""Wait for authorized first-round completion, then start second round exactly once."""
import fcntl,json,os,subprocess,time
from pathlib import Path
from prepare_reflection_round2 import ROOT,validate
B=ROOT/'reports/batches/experience-reflection-001'
SECOND=ROOT/'reports/batches/experience-reflection-001-round2'
def main():
    with (B/'second-round-handoff.lock').open('a') as bridge:
        fcntl.flock(bridge,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while True:
            if SECOND.exists():return
            s=json.loads((B/'status.json').read_text())
            if s['status']=='needs_audit':raise RuntimeError('First measurement needs audit')
            ready=(len(s['completed'])==12 and len(s.get('reviewed_pairs',[]))==6 and s['status'] in ['completed_awaiting_final_analysis','completed_analyzed'])
            if ready and not (B/'PAUSE_REQUEST.json').exists():
                with (ROOT/'experiments/.iterations.lock').open('a') as lock:
                    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:time.sleep(10);continue
                    validate()
                    (B/'SECOND_ROUND_HANDOFF.json').write_text(json.dumps({'time':time.time(),'first_status':s['status'],'completed':12,'reviewed':6,'destination':str(SECOND)},indent=2)+'\n')
                subprocess.run([str(ROOT.parent/'run-local.sh'),'scripts/reflection_round2_batch.py','start'],cwd=ROOT.parent,check=True)
                return
            time.sleep(10)
if __name__=='__main__':main()
