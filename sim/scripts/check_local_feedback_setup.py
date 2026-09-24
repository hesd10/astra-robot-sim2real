"""Offline feasibility and stop-path checks; no Astra session is started."""
import sys,json,tempfile,importlib.util
from pathlib import Path
import mujoco
from PIL import Image
from prepare_local_feedback_states import ROOT,OUT,load_stage
sys.path.insert(0,str(OUT/'inputs/LOOP/skill/local-press/scripts'))
from feedback import run
from primitive import step
class Adapter:
 def __init__(self,c,path):self.c=c;self.path=path;self.n=0;self.stops=0;self.renderer=mujoco.Renderer(c.m,height=480,width=640)
 def call(self,op,**kw):
  if op=='stop':self.stops+=1
  return self.c.dispatch({'op':op,**kw},now=float(self.c.d.time))
 def sleep(self,secs):
  for _ in range(round(secs/self.c.dt)):self.c.step(now=float(self.c.d.time))
 def observe(self):
  self.n+=1;f=self.path/f'{self.n}.jpg';self.renderer.update_scene(self.c.d,camera='head');Image.fromarray(self.renderer.render()).save(f)
  return {'sim_time':float(self.c.d.time),'files':{'head':str(f)}}
 def close(self):self.renderer.close()
def main():
 checks=[]
 with tempfile.TemporaryDirectory() as td:
  for name in ['S1','S2','S3']:
   a=Adapter(load_stage(OUT/'states'/f'{name}.json'),Path(td))
   try:
    result=run(a,vx=.04,vy=-.006,duration=.8,regions={'head':[420,260,590,410]},max_steps=6)
    assert result['reason']=='red_detected_verify' and a.c.first_press and not a.c.fault
    assert not a.c.private_result()['wrong_button'] and a.stops>=result['steps']
    checks.append({'state':name,'closed_loop_steps':result['steps'],'physical_success':True,'model_calls':0})
   finally:a.close()
  a=Adapter(load_stage(OUT/'states/S3.json'),Path(td))
  try:
   step(a,vx=.04,vy=-.006,duration=.8);assert a.c.public_action_count==1 and not a.c.first_press
   checks.append({'single_step_only':True})
  finally:a.close()
  a=Adapter(load_stage(OUT/'states/S3.json'),Path(td))
  try:
   result=run(a,vx=.04,vy=-.006,duration=.8,regions={'head':[420,260,590,410]},max_steps=1)
   assert result['reason']=='step_budget' and a.stops>=1 and not a.c.first_press
   checks.append({'budget_stop':True})
  finally:a.close()
  a=Adapter(load_stage(OUT/'states/S1.json'),Path(td))
  try:
   try:run(a,vx=.04,vy=-.006,duration=.8,regions={'head':[0,0,9999,9999]})
   except ValueError:pass
   else:raise AssertionError('invalid ROI accepted')
   assert a.c.public_action_count==0 and a.stops>=1
   checks.append({'invalid_image_region_stops_before_motion':True})
  finally:a.close()
 (OUT/'OFFLINE_CHECKS.json').write_text(json.dumps(checks,indent=2)+'\n');print(json.dumps(checks))
if __name__=='__main__':main()
