import sys,json,math,copy
from pathlib import Path
import pytest
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
from engine import Engine
from transport import FakeTransport,Transport,signed_word,ROOT
from domain import signed_magnitude
@pytest.fixture
def rig():
    c=json.loads((ROOT/'calibration/sessions/real-001/calibration.json').read_text());h=FakeTransport(c);now=[100.];e=Engine(c,h,clock=lambda:now[0],base_enabled=True);return e,h,now

def req(e,op,i='x',**kw):return e.request(dict(op=op,id=i,**kw))
def test_read_only_start(rig):
    e,h,t=rig;assert not h.writes
    req(e,'schema');req(e,'state','s');assert not h.writes
    with pytest.raises(RuntimeError):req(e,'move','motion',targets={'left_1':.1},duration=1)
def test_seed_before_torque_and_no_restore(rig):
    e,h,t=rig;e.arm();idx=next(i for i,x in enumerate(h.writes) if x[0]==40)
    assert any(x[0]==42 for x in h.writes[:idx]);assert all(v==0 for a,d in h.writes[:idx] if a==46 and set(d)==set(e.wheel_keys) for v in d.values())
    e.stop();assert h.writes[-1][0]==46;assert all(h.values[k]['torque']==1 for k in e.arm_keys)
def test_time_progress_ignores_tracking(rig):
    e,h,t=rig;e.arm();start=e.state()['joints']['left_1']['position'];req(e,'move',targets={'left_1':start+.1,'right_1':-.1},duration=2)
    t[0]+=1;e.tick();mid=e.targets['left_1'];t[0]+=1;e.tick()
    assert not e.motion and e.targets['left_1']>mid
    assert e.state()['joints']['left_1']['position']==start # fake servo never follows, still completes
    assert e.fault is None

def test_target_continuity(rig):
    e,h,t=rig;e.arm();req(e,'move',targets={'left_1':.1},duration=2);t[0]+=2;e.tick();previous=e.targets['left_1'];req(e,'move','next',targets={'left_1':.2},duration=2);assert e.motion['start']['left_1']==previous!=e.counts['left_1']
def test_retry_and_conflict(rig):
    e,h,t=rig;e.arm();r=dict(op='move',id='same',targets={'left_1':.1},duration=2);a=e.request(r);t[0]+=1;assert e.request(r)==a and e.motion['start_time']==100
    with pytest.raises(ValueError):e.request(dict(r,duration=3))
def test_base_sign_and_expiry(rig):
    e,h,t=rig;e.arm();req(e,'base',vx=.03,vy=0,wz=0,duration=.2);t[0]+=.05;e.tick()
    vals=h.writes[-1][1];dec=[signed_magnitude(vals[k]) for k in e.wheel_keys];assert dec[0]<0<dec[1] and dec[2]<0<dec[3]
    t[0]+=.21;e.tick();assert e.base_command==[0.,0.,0.] and all(v==0 for v in h.writes[-1][1].values())
def test_stop_retains_applied_targets_finish_terminal(rig):
    e,h,t=rig;e.arm();req(e,'move',targets={'left_1':.1},duration=2);t[0]+=1;e.tick();targets=copy.deepcopy(e.targets);req(e,'stop','stop');assert e.targets==targets and not e.motion
    req(e,'finish','f',outcome='success')
    with pytest.raises(RuntimeError):req(e,'base','b',vx=.01,duration=.1)
@pytest.mark.parametrize('value',[float('nan'),float('inf'),True,'1'])
def test_invalid_values_no_write(rig,value):
    e,h,t=rig;e.arm();before=len(h.writes)
    with pytest.raises((ValueError,TypeError)):req(e,'move',targets={'left_1':value},duration=1)
    assert len(h.writes)==before

def test_temperature_sensor_not_read():
    h=object.__new__(Transport);h.motors={'one':{}};reads=[]
    def read(k,a,n):reads.append((a,n));return [0]*n
    h.read=read;h.sample();assert reads==[(56,4),(40,1)];assert not any(a<=63<a+n for a,n in reads)
def test_no_wrap_command_range(rig):
    e,h,t=rig;e.arm();assert all(0<=a<=b<=4095 for a,b in e.bounds.values())
    with pytest.raises(ValueError):req(e,'move',targets={'left_5':-2.8},duration=10)
def test_signed_speed_encoding():
    for x in [-3000,-1,0,1,3000]:assert signed_magnitude(signed_word(x))==x

def test_no_wheel_write_without_base_commissioning(rig):
    e,h,t=rig;e.base_enabled=False;e.arm();e.stop()
    assert not any(set(values)&set(e.wheel_keys) for _,values in h.writes)
    assert all(h.values[k]['torque']==0 for k in e.wheel_keys)
def test_release_then_shutdown_never_reenables_wheels(rig):
    e,h,t=rig;e.arm();e.release();e.stop();assert all(v['torque']==0 for v in h.values.values())

def test_limits_match_simulation(rig):
    e,h,t=rig
    for n,s in e.schema()['joints'].items():
        deg=20 if n.startswith('head') else 15 if n.endswith(('_4','_5')) else 10
        assert s['max_target_speed']==math.radians(deg)
        assert s['max_target_acceleration']==3*math.radians(deg)
def test_base_ramp_matches_simulation(rig):
    e,h,t=rig;e.arm();req(e,'base',vx=.1,vy=0,wz=math.pi/12,duration=.2)
    assert e.base_command==[0,0,0]
    t[0]+=.05;e.tick();assert e.base_command[0]==pytest.approx(.01);assert e.base_command[2]==pytest.approx(math.pi/120)
    t[0]+=.05;e.tick();assert e.base_command[0]==pytest.approx(.02)
    t[0]+=.11;e.tick();assert e.base_command[0]==pytest.approx(0,abs=1e-10)

def test_base_only_does_not_enable_or_command_arms(rig):
    e,h,t=rig;e.arm(arms=False);assert all(h.values[k]['torque']==0 for k in e.arm_keys)
    assert not any(set(v)&set(e.arm_keys) for a,v in h.writes)
    t[0]+=.1;e.tick();assert e.fault is None
    with pytest.raises(ValueError):req(e,'move',targets={'left_1':.1},duration=2)
def test_documented_acceleration_quantization():
    from profiles import joint_profile,base_raw_acceleration
    assert [joint_profile(n)['raw_acceleration'] for n in ['left_1','left_4','head_1']]==[4,6,7]


def test_sustained_base_output_and_retarget_without_pause(rig):
    e,h,t=rig;e.arm();req(e,'base','long',vx=.02,duration=5)
    for _ in range(30):t[0]+=.05;e.tick()
    assert e.base_command[0]==pytest.approx(.02)
    req(e,'base','extend',vx=.02,duration=2)
    t[0]+=.05;e.tick();assert e.base_command[0]==pytest.approx(.02)
    for _ in range(50):t[0]+=.05;e.tick()
    assert e.base_command==[0.,0.,0.]
    with pytest.raises(ValueError):req(e,'base','too-long',vx=.02,duration=5.1)

def test_configured_translation_limit():
    c=json.loads((ROOT/'calibration/sessions/real-001/calibration.json').read_text());c['base']['max_translation_speed_mps']=.03
    e=Engine(c,FakeTransport(c),base_enabled=True);e.arm(arms=False)
    assert req(e,'schema')['base']['max_translation_speed']==.03
    req(e,'base','allowed',vx=.03,vy=0,duration=.2)
    for i,(vx,vy) in enumerate([(.031,0),(.025,.025),(-.04,0)]):
        with pytest.raises(ValueError):req(e,'base','bad'+str(i),vx=vx,vy=vy,duration=.2)
    req(e,'stop','stop-limit');assert e.base_command==[0.,0.,0.]
