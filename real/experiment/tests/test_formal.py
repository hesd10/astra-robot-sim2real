import sys,json,time,shutil
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from formal import FormalController
import campaign

def wait_for(c,phase):
 deadline=time.monotonic()+10
 while time.monotonic()<deadline:
  if c.data['phase']==phase:return
  if c.data['phase']=='error':raise AssertionError(c.data)
  time.sleep(.02)
 raise AssertionError(c.data)
def finish(c):
 c.thread.join(timeout=8);assert not c.thread.is_alive()
def record_demo_source(c,aid):
 import cv2,numpy as np
 row=c.data['attempts'][-1];p=Path(row['path'])/'private';folder=p/'observations/test-frame';folder.mkdir(parents=True)
 for role in ['head','left_wrist','right_wrist']:cv2.imwrite(str(folder/(role+'.jpg')),np.full((48,64,3),127,dtype=np.uint8))
 (folder/'metadata.json').write_text('{}');t=row['result']['t0'];entry=dict(kind='observation',unix=t+.001,folder=str(folder),metadata={})
 with (p/'operator-events.jsonl').open('a') as f:f.write(json.dumps(entry)+'\n')
 (p/'NEVER_SUPPLY_PRIVATE.txt').write_text('private canary')

def test_nine_interleaved_review_pause_resume_and_optional_d(tmp_path):
 c=FormalController(tmp_path,'demo')
 try:
  assert ''.join(s['group'] for s in c.data['queue'])=='ABCBCACAB'
  with pytest.raises(ValueError):c.append_d()
  for i in range(9):
   slot=c.next_slot().copy();aid=c.start();wait_for(c,'ready')
   subject=Path(c.data['attempts'][-1]['path'])/'subject'
   assert (subject/'prior/body').exists()==(slot['group']=='B')
   assert (subject/'prior/experience').exists()==(slot['group']=='C')
   assert not c.gate.active and c.gate.t0 is None
   c.begin()
   for _ in range(100):
    if c.gate.active:break
    time.sleep(.02)
   c.outcome(attempt_id=aid,event_id='success',outcome='success');finish(c)
   with pytest.raises(ValueError):c.start()
   if slot['group']=='A':record_demo_source(c,aid)
   c.review(aid,'success',eligible=True);c.release()
   if i==3:
    c.pause();c.close();c=FormalController(tmp_path,'demo');assert c.snapshot()['completed_slots']==4 and not c.snapshot()['busy']
  expected=c.d_candidates()[0]['id'];result=c.append_d();assert result['source']==expected
  assert len(c.data['queue'])==12 and c.next_slot()['group']=='D'
  package=c.bundle/'packages/D';assert list(package.rglob('*.jpg'));assert (package/'prior/experience/demonstration.mp4').stat().st_size>0
  assert not list(package.rglob('*PRIVATE*')) and not list(package.rglob('*.py'))
  assert 'source' in result
  with pytest.raises(ValueError):c.append_d()
  aid=c.start();wait_for(c,'ready');assert (Path(c.data['attempts'][-1]['path'])/'subject/prior/experience/summary.md').exists();c.stop();finish(c)
 finally:c.close()

def test_preparation_cancel_does_not_consume_slot(tmp_path):
 c=FormalController(tmp_path,'demo')
 try:
  first=c.start();wait_for(c,'ready');c.stop();finish(c)
  with pytest.raises(ValueError):c.review(first,'failure')
  c.review(first,'retry',note='Stopped during preparation');c.release()
  assert c.snapshot()['completed_slots']==0
  second=c.start();assert first!=second and '-01-A-' in second;wait_for(c,'ready');c.stop();finish(c)
 finally:c.close()

def test_tampered_inputs_fail_before_creating_attempt(tmp_path):
 c=FormalController(tmp_path,'demo')
 try:
  (c.bundle/'common/PROMPT.md').write_text('changed')
  with pytest.raises(ValueError,match='Frozen material'):c.start()
  assert not c.data['attempts']
 finally:c.close()

def test_pilot_records_cannot_become_formal(tmp_path):
 (tmp_path/'campaign.json').write_text(json.dumps({'attempts':[{'id':'pilot-001'}]}))
 with pytest.raises(ValueError,match='独立'):FormalController(tmp_path,'demo')

def test_no_success_cannot_generate_real_experience(tmp_path):
 c=FormalController(tmp_path,'demo')
 try:
  for slot in c.data['queue']:slot['status']='done'
  with pytest.raises(ValueError,match='没有'):c.append_d()
  c.skip_d();assert c.data['d_status']=='skipped'
 finally:c.close()
