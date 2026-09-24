import sys,json,copy
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from registry import Registry,read,write,control_digest,ROOT
from controller import Controller
from workflow import Workflow

def test_names_and_separate_edits(tmp_path):
 r=Registry(tmp_path);a=r.create('Beijing');b=r.create('Shanghai')
 for bad in ['../Shanghai','a/b','..','']:
  with pytest.raises(ValueError):r.create(bad)
 with pytest.raises(ValueError):r.create('beijing')
 before=(b/'calibration/calibration.json').read_bytes();r.checkpoint('Beijing','camera edit');write(a/'camera-config.json',{'devices':{'left':'x'}})
 assert (b/'calibration/calibration.json').read_bytes()==before;assert len(r.status('Beijing')['revisions'])==1

def test_partial_invalidation(tmp_path):
 r=Registry(tmp_path);p=r.create('Beijing')
 for s in ['joints','base','camera']:r.accept('Beijing',s,'test')
 write(p/'camera-config.json',dict(devices={'head':'other'}));v=r.status('Beijing')['validation']
 assert v['joints']['valid'] and v['base']['valid'] and not v['camera']['valid']
 cal=read(p/'calibration/calibration.json');cal['joints']={'left_1':{'sign':1}};write(p/'calibration/calibration.json',cal);assert not r.status('Beijing')['validation']['joints']['valid']
 assert r.status('Beijing')['validation']['base']['valid']

def test_camera_metadata_does_not_stale_motor_plan():
 a={'joints':{},'wheels':{},'base':{},'camera':{'status':'old'}};b=copy.deepcopy(a);b['camera']['status']='new';assert control_digest(a)==control_digest(b)

def test_loading_and_demo_actions_never_open_hardware(tmp_path):
 r=Registry(tmp_path,demo=True);r.create('Beijing');r.create('Shanghai');w=Workflow(r,Controller)
 try:
  w.load('Beijing');assert not w.controller.connected
  w.controller.data['camera']['status']='test';w.controller.save();w.load('Shanghai');assert w.controller.data['camera']['status']=='not_imported'
  for op in ['apply','restore','release_all','zero','home','base','initial','ready']:
   with pytest.raises(ValueError):w.action(op,{})
  w.load('Beijing');assert w.controller.data['camera']['status']=='test'
 finally:w.controller.running=False;w.controller.disconnect()

def test_migrate_and_generate_without_hardware(tmp_path):
 r=Registry(tmp_path);r.import_beijing();w=Workflow(r,Controller)
 try:
  w.load('Beijing');old=copy.deepcopy(w.controller.data);plan=w.generate()
  assert len(plan['motors'])==18
  assert set(v['acceleration'] for v in plan['motors'].values())=={4,6,7,54}
  assert w.controller.data==old;assert not w.controller.connected
  pose=read(r.path('Beijing')/'task-pose.json');assert len(pose['targets'])==12
  w.action('save_cameras',{'devices':{'head':'H','left_wrist':'L','right_wrist':'R'}}) if False else None
 finally:w.controller.running=False;w.controller.disconnect()

def test_automatic_job_completion_does_not_restore_or_release(tmp_path):
 r=Registry(tmp_path,demo=True);r.create('demo');w=Workflow(r,Controller);w.load('demo');calls=[]
 w.release=lambda:calls.append('release');w.parameters=lambda *a:calls.append('parameters')
 try:
  w.run('test',lambda:{'ok':True});w.thread.join(2);assert w.job['status']=='completed';assert calls==[]
 finally:w.controller.running=False;w.controller.disconnect()

def test_parameter_apply_preserves_torque_and_restore_is_manual(tmp_path):
 r=Registry(tmp_path);r.import_beijing();w=Workflow(r,Controller);w.load('Beijing');plan=w.generate();backup=Path(r.status('Beijing')['initial_backup']);report=read(backup/'REPORT.json')
 class Fake:
  def __init__(self):
   self.motors={};self.mem={};self.writes=[]
   for m in report['motors']:
    k=m['usb_serial_path']+':'+str(m['id']);a=read(backup/m['folder']/'pass-1.json');self.motors[k]={'original':a,'model':m['model_candidates'][0]};self.mem[k]=list(a)
  def connect(self):return {k:{'torque':v[40]} for k,v in self.mem.items()}
  def read(self,k,a,n):assert not a<=63<a+n;return self.mem[k][a:a+n]
  def sync(self,a,n,values,verify=False):
   self.writes.append((a,dict(values)))
   for k,v in values.items():
    self.mem[k][a:a+n]=list(v.to_bytes(n,'little'))
    if a==46 and self.motors[k]['model']=='sts3250':self.mem[k][40]=1
  def check_configs(self):pass
  def close(self):pass
 f=Fake();arm=next(k for k,m in f.motors.items() if m['model']=='sts3215');f.mem[arm][40]=1;w.hardware=lambda:f
 try:
  w.parameters();assert f.mem[arm][40]==1
  assert all(f.mem[k][41]==v['acceleration'] for k,v in plan['motors'].items())
  assert not any(a==42 for a,v in f.writes)
  with pytest.raises(ValueError):w.parameters(restore=True)
  w.release();assert all(a[40]==0 for a in f.mem.values())
  w.parameters(restore=True);assert all(a[40]==a[41]==a[46]==a[47]==0 for a in f.mem.values())
  assert read(r.path('Beijing')/'profile.json')['parameters_applied_hash'] is None
 finally:w.controller.running=False;w.controller.disconnect()

def test_old_test_evidence_cannot_validate_new_calibration(tmp_path):
 r=Registry(tmp_path);r.import_beijing();w=Workflow(r,Controller);w.load('Beijing');w.generate();p=r.path('Beijing')
 try:
  write(p/'test-results/old-home.json',{'fingerprint':'old'});write(p/'test-results/old-zero.json',{'fingerprint':'old'})
  with pytest.raises(ValueError):w.action('accept',{'section':'joints'})
 finally:w.controller.running=False;w.controller.disconnect()

def test_stop_blocks_subsequent_job_motion_without_release(tmp_path,monkeypatch):
 import workflow
 r=Registry(tmp_path,demo=True);r.create('A');w=Workflow(r,Controller);w.load('A');w.socket='fake';calls=[]
 monkeypatch.setattr(workflow,'rpc',lambda path,op,**kw:calls.append(op))
 try:
  w.stop()
  with pytest.raises(RuntimeError):w.motion('base',vx=.02,duration=.5)
  assert calls==['stop']
 finally:w.controller.running=False;w.controller.disconnect()


def test_camera_label_uses_usb_port_not_host_bus():
 from workflow import camera_port_label
 label=camera_port_label('/dev/v4l/by-path/pci-0000:80:14.0-usb-0:1.1.2:1.0-video-index0')
 assert label.startswith('USB 1.1.2 · ')
