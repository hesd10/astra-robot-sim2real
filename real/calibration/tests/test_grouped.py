import sys,time,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from controller import Controller
from grouped import members

def setup(tmp_path,group='left',bus='DEMO-B'):
 c=Controller(tmp_path,demo=True);c.connect();c.start_capture('group_mapping',group)
 sid=7 if group=='head' else 1
 for v in [2070,2100,2160]:
  c.hw.positions[f'{bus}:{sid}']=v;c.ingest(c.hw.sample())
 c.capture['started_mono']-=1;c.finish_capture();c.confirm_group(group)
 return c

def stable(c):
 for _ in range(65):c.ingest(c.hw.sample())

def ready(c,group='left'):
 stable(c);c.group_reference(group)
 for k in members(group):c.data['joints'][k]['sign']=1

def test_group_mapping_records_six_and_preserves_matching_prior(tmp_path):
 c=setup(tmp_path)
 assert len(c.data['joints'])==6
 assert c.data['joints']['left_6']['motor']=='DEMO-B:6'
 assert 'right_1' not in c.data['joints']

def test_both_arm_motion_rejected(tmp_path):
 c=Controller(tmp_path,demo=True);c.connect();c.start_capture('group_mapping','left')
 for v in [2070,2100,2160]:
  c.hw.positions['DEMO-A:1']=v;c.hw.positions['DEMO-B:2']=v;c.ingest(c.hw.sample())
 c.capture['started_mono']-=1
 with pytest.raises(ValueError):c.finish_capture()

def test_group_reference_atomic_and_head_pi(tmp_path):
 c=setup(tmp_path,'head');stable(c)
 c.history['DEMO-B:8'].append((time.monotonic(),3000))
 with pytest.raises(ValueError):c.group_reference('head')
 assert all('reference' not in x for x in c.data['joints'].values())
 stable(c);c.group_reference('head')
 assert c.data['joints']['head_1']['reference']['reference_q']==pytest.approx(3.141592653589793)
 assert c.data['joints']['head_2']['reference']['reference_q']==0

def test_group_range_partial_then_supplement_without_redo(tmp_path):
 c=setup(tmp_path);ready(c);c.start_capture('group_range','left')
 for v in [2000,1900,2300,2500]:
  for i in range(1,6):c.hw.positions[f'DEMO-B:{i}']=v
  c.ingest(c.hw.sample())
 c.capture['started_mono']-=1;r=c.finish_capture()
 assert r['partial'] and list(r['rejected'])==['left_6']
 old=copy.deepcopy(c.data['joints']['left_1']['limits'])
 c.start_capture('group_range','left')
 for v in [2000,1900,2300,2500]:
  c.hw.positions['DEMO-B:6']=v;c.ingest(c.hw.sample())
 c.capture['started_mono']-=1;r=c.finish_capture()
 assert r['ok'] and c.data['joints']['left_1']['limits']['counts']==old['counts']
 assert all('limits' in c.data['joints'][k] for k in members('left'))

def test_group_reference_invalidates_signs_ranges_and_reconnect(tmp_path):
 c=setup(tmp_path);ready(c)
 c.group_reference('left')
 assert all('sign' not in c.data['joints'][k] for k in members('left'))
 with pytest.raises(ValueError):c.start_capture('group_range','left')
 for k in members('left'):c.data['joints'][k]['sign']=1
 c.disconnect();c.connect()
 with pytest.raises(ValueError,match='连接已变化'):c.start_capture('group_range','left')

def test_individual_signs_remain_independent(tmp_path):
 c=setup(tmp_path);stable(c);c.group_reference('left')
 c.start_capture('positive','left_2')
 for v in [2020,1980,1920]:
  c.hw.positions['DEMO-B:2']=v;c.ingest(c.hw.sample())
 c.capture['started_mono']-=1;c.finish_capture()
 assert c.data['joints']['left_2']['sign']==-1
 assert 'sign' not in c.data['joints']['left_1']
