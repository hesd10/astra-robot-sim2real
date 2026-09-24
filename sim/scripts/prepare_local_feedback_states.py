"""Operator-only offline initialization and feasibility checks; no model trials."""
import sys,json,gzip
from pathlib import Path
import numpy as np
import mujoco
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sim_env.core import Core
from sim_env.model import restore,snapshot,CAMERAS
from PIL import Image
OUT=ROOT/'studies/local-feedback-001'
def dump(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,default=lambda x:x.tolist(),indent=2)+'\n')
def reset_clock(c):
 c.d.time=0.;c.steps=0;c.events=[];c.first_press=None;c.released_since=None;c.peak_contact=0.;c.impact_window=0.;c.public_action_count=0
 c.risk=dict.fromkeys(c.risk,0.);c.blocked=dict.fromkeys(c.blocked,0.)
def load_stage(path):
 c=Core(max_seconds=300);restore(c.m,c.d,json.loads(Path(path).read_text()));reset_clock(c);return c
def main():
 source=ROOT/'experiments/er001-t016/private/simulation/states.jsonl.gz'
 row=None
 with gzip.open(source,'rt') as f:
  for line in f:
   x=json.loads(line)
   if x['sim_time']>223.2:break
   row=x
 assert row
 results=[]
 for name,back in [('S1',0.),('S2',.02),('S3',.04)]:
  c=Core(max_seconds=300);restore(c.m,c.d,row);reset_clock(c)
  q=int(c.m.joint('base_free').qposadr[0]);forward=c.d.body('chassis').xmat.reshape(3,3)[:,0].copy();c.d.qpos[q:q+3]-=back*forward
  mujoco.mj_forward(c.m,c.d)
  for _ in range(1000):c.step(now=float(c.d.time))
  assert not c.first_press and not c.fault and not any(c.panel.called.values()),(name,c.private_result())
  reset_clock(c);path=OUT/'states'/f'{name}.json';dump(path,snapshot(c.m,c.d))
  with mujoco.Renderer(c.m,height=480,width=640) as rend:
   for public,cam in CAMERAS.items():
    rend.update_scene(c.d,camera=cam);Image.fromarray(rend.render()).save(OUT/'states'/f'{name}-{public}.jpg')
  counts=[]
  for repeat in range(2):
   test=load_stage(path)
   for i in range(12):
    test.dispatch({'op':'base','vx':.04,'vy':-.006,'wz':0,'duration':.8},now=float(test.d.time))
    for _ in range(1100):test.step(now=float(test.d.time))
    if test.first_press or test.fault:break
   assert test.first_press and not test.fault and not test.private_result()['wrong_button'],(name,test.private_result())
   counts.append(i+1)
  assert counts[0]==counts[1]
  results.append({'state':name,'source_run':'er001-t016','source_time':row['sim_time'],'backward_offset_m':back,'normalization':'stop control, settle 1s, reset task clock/health counters only after unpressed/no fault check','reference_pulses':counts,'reference_command':{'vx':.04,'vy':-.006,'duration':.8,'cycle_seconds':1.1},'snapshot_spec':'mjSTATE_INTEGRATION + geom_rgba; controller idle; all panel latches false','source_is_not_skill_origin':True})
 dump(OUT/'STATE_VALIDATION.json',results);print(json.dumps(results))
if __name__=='__main__':main()
