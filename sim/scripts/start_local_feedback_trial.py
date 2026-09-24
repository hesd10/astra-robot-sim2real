"""Explicit single-run launcher for frozen stage setup; no automatic batch."""
import sys,json,hashlib,os,tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'studies/local-feedback-001'
from start_local_feedback_experiment import start
from account_preflight import preflight

def hashes(p):return {str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(p.rglob('*')) if f.is_file() and '__pycache__' not in f.parts}
def validate():
 m=json.loads((OUT/'manifest.json').read_text());assert hashlib.sha256((OUT/'manifest.json').read_bytes()).hexdigest()==json.loads((OUT/'SEAL.json').read_text())['manifest_sha256']
 for k in ['inputs','states']:assert hashes(OUT/k)==m[k+'_sha256'],k
 for f,h in m['runtime_sha256'].items():assert hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h,f
 for f in ['PROMPT.md','API.md','robot.py']:
  assert len({(OUT/'inputs'/c/f).read_bytes() for c in ['FREE','STEP','LOOP']})==1
 assert (OUT/'inputs/STEP/skill/local-press/scripts/primitive.py').read_bytes()==(OUT/'inputs/LOOP/skill/local-press/scripts/primitive.py').read_bytes()
 return m
if __name__=='__main__':
 m=validate()
 if len(sys.argv)!=2:raise SystemExit('Supply --check or one manifest run ID')
 if sys.argv[1]=='--check':print('Validated 9-trial stage setup; no trials launched');raise SystemExit
 t=next(t for t in m['trials'] if t['run']==sys.argv[1])
 if os.environ.get('ASTRA_BASE_URL'):raise RuntimeError('external model endpoint not allowed')
 q=preflight();assert q['model']==m['model'] and q['effort']==m['effort'] and q['minimum_remaining_percent']>0
 assert not q.get('spend_control_reached') and not q.get('rate_limit_reached_type')
 import fcntl
 with (ROOT/'experiments/.iterations.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  run=start(t['run'],input_dir=OUT/'inputs'/t['condition'],reference=OUT/'states'/f'{t["state"]}.json',max_seconds=m['task_seconds'],reasoning=m['effort'])
  for f,h in hashes(OUT/'inputs'/t['condition']).items():assert hashlib.sha256((run/'subject'/f).read_bytes()).hexdigest()==h,f
  validate()
