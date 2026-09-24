import sys, math, json, io, zipfile, hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from domain import *
from controller import Controller, DemoHardware

@pytest.mark.parametrize('before,after,delta',[(4090,8,14),(8,4090,-14),(100,160,60),(-10,10,20)])
def test_unwrap(before,after,delta):assert unwrap_delta(after,before)==delta

def test_head_pi_and_negative_direction():
    assert angle(2048,2048,-1,math.pi)==math.pi
    assert angle(3072,2048,-1,math.pi)==pytest.approx(math.pi/2)

def test_reject_ambiguous_mapping():
    with pytest.raises(ValueError):candidate_mapping({'a':100,'b':85})
    with pytest.raises(ValueError):candidate_mapping({'a':12,'b':4})
    assert candidate_mapping({'a':100,'b':5})=='a'

def test_sign_requires_one_way_motion():
    with pytest.raises(ValueError):infer_sign(2,80)
    with pytest.raises(ValueError):infer_sign(70,400)
    assert infer_sign(-100,110)==-1

def test_limits_keep_margin_and_reject_wrap_ambiguity():
    x=measured_limits(1900,2200,2048,-1,0)
    assert x['usable_min_rad']<0<x['usable_max_rad']
    with pytest.raises(ValueError):measured_limits(0,4096,2048,1,0)
    with pytest.raises(ValueError):measured_limits(100,110,105,1,0)

def make_trials(signs=(1,-1,1,-1)):
    matrix=wheel_matrix(100,400,300)
    axes={'forward':(0,1),'backward':(0,-1),'left':(1,1),'right':(1,-1),'ccw':(2,1),'cw':(2,-1)}
    return {d:{w:dict(delta=(1 if matrix[i][axis]*sgn>0 else -1)*signs[i]*100,travel=100) for i,w in enumerate(WHEELS)} for d,(axis,sgn) in axes.items()}

def test_mecanum_six_directions_and_units():
    dims=dict(diameter_mm=100,track_mm=400,wheelbase_mm=300)
    sol=solve_base(make_trials(),dims)
    assert sol['matrix_body_mps_radps_to_wheel_radps'][0]==pytest.approx([20,-20,-7])
    assert list(sol['encoder_sign_for_forward_roll'].values())==[1,-1,1,-1]
    assert sol['active_motor_command_sign_verified'] is False

def test_mecanum_reject_slip_and_incomplete():
    dims=dict(diameter_mm=100,track_mm=400,wheelbase_mm=300)
    t=make_trials();t['left']['front_left']['delta']*= -1
    with pytest.raises(ValueError):solve_base(t,dims)
    t=make_trials();del t['cw']
    with pytest.raises(ValueError):solve_base(t,dims)
    with pytest.raises(ValueError):wheel_matrix(float('nan'),400,300)

def controller(tmp_path):
    c=Controller(tmp_path,demo=True);c.connect();return c

def move(c,key,values):
    # Distinct samples, no hardware or wall-clock sleeps needed.
    for value in values:
        c.hw.positions[key]=value;c.ingest(c.hw.sample())
    c.capture['started_mono']-=1

def test_joint_flow_mapping_reference_sign_limits_and_export(tmp_path):
    c=controller(tmp_path);key='DEMO-A:1'
    c.start_capture('mapping','left_1');move(c,key,[2060,2100,2150]);c.finish_capture();c.confirm_mapping('left_1',key)
    c.hw.positions[key]=2048
    for _ in range(65):c.ingest(c.hw.sample())
    c.reference('left_1')
    c.start_capture('positive','left_1');move(c,key,[2060,2100,2170]);c.finish_capture()
    c.start_capture('range','left_1');move(c,key,[2000,1900,1800,1900,2200,2300,2400]);c.finish_capture()
    j=c.data['joints']['left_1'];assert j['sign']==1 and j['limits']['usable_min_rad']<0
    assert c.summary()['joints_complete']==1
    archive=c.export()
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        hashes=json.loads(z.read('SHA256SUMS.json'))
        assert all(hashlib.sha256(z.read(k)).hexdigest()==v for k,v in hashes.items())
        p=json.loads(z.read('calibration.json'));assert p['demo'] and not p['status']['ready_for_active_control']
    c.disconnect();c.connect()
    with pytest.raises(ValueError,match='连接已变化'):c.start_capture('positive','left_1')

def test_mapping_only_released_motors_and_duplicate_rejected(tmp_path):
    c=controller(tmp_path);c.hw.torques['DEMO-A:1']=1;c.ingest(c.hw.sample())
    c.start_capture('mapping','left_1');assert 'DEMO-A:1' not in c.capture['stats']
    c.action('capture_cancel',{})
    c.data['joints']['left_1']={'motor':'DEMO-A:2'}
    c.result=dict(kind='mapping',target='left_2',motor='DEMO-A:2',capture_id='x')
    with pytest.raises(ValueError):c.confirm_mapping('left_2','DEMO-A:2')

def test_reference_invalidates_downstream_and_small_span_rejected(tmp_path):
    c=controller(tmp_path);key='DEMO-A:1'
    c.data['joints']['left_1']={'motor':key,'sign':1,'limits':{}}
    for _ in range(6):c.ingest(c.hw.sample())
    c.reference('left_1');assert 'sign' not in c.data['joints']['left_1']
    with pytest.raises(ValueError):c.start_capture('range','left_1')

def test_no_automatic_writes_and_release_requires_confirmation(tmp_path):
    c=controller(tmp_path)
    with pytest.raises(ValueError):c.action('release',{'motors':['DEMO-A:1']})
    with pytest.raises(ValueError):c.action('move',{'position':0})
    c.action('release',{'motors':['DEMO-A:1'],'supported':True})
    c.disconnect();assert not c.connected

def test_transport_only_torque_zero_write():
    import ast
    tree=ast.parse((Path(__file__).resolve().parents[1]/'hardware.py').read_text())
    writes=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr.startswith('write')]
    assert len(writes)==1
    call=writes[0];assert call.func.attr=='write1ByteTxRx'
    assert ast.literal_eval(call.args[-2])==40 and ast.literal_eval(call.args[-1])==0
