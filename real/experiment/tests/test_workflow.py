import json,sys,time,uuid
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gateway import Gate
import importlib.util
spec=importlib.util.spec_from_file_location('experiment_controller_test',Path(__file__).resolve().parents[1]/'controller.py')
experiment_controller=importlib.util.module_from_spec(spec);spec.loader.exec_module(experiment_controller)
Controller=experiment_controller.Controller

class Motor:
    def __init__(self):self.commands=[]
    def __call__(self,op,**kw):
        self.commands.append((op,kw))
        if op=='state':return {'joints':{'head_1':{'position':3.14}},'fault':None}
        if op=='schema':return {'joints':{'head_1':{'minimum':0,'maximum':6.2}}}
        return {'accepted':True}

@pytest.fixture
def gate(tmp_path):
    g=Gate('attempt-1',Motor(),tmp_path/'events.jsonl',feedback_policy='explicit_wait');g.start();return g

def request(g,op,**kw):return g.request(dict(op=op,id=uuid.uuid4().hex,**kw))
def event(g,outcome,**kw):return g.operator('attempt-1',uuid.uuid4().hex,outcome,**kw)

def test_terminal_stops_before_any_delivery_and_blocks_motion(gate):
    event(gate,'success');assert gate.call.commands[-1][0]=='stop';assert gate.pending()
    with pytest.raises(ValueError):request(gate,'base',vx=.01,duration=.5)
    assert not any(op=='base' for op,_ in gate.call.commands)
    assert gate.terminal['outcome']=='success'

def test_failed_physical_stop_still_latches_terminal(gate):
    def failed(op,**kw):raise OSError('disconnected')
    gate.call=failed
    with pytest.raises(OSError):event(gate,'success')
    assert gate.terminal and gate.pending()
    with pytest.raises(ValueError):request(gate,'move',targets={'head_1':3.14},duration=1)

def test_negative_feedback_correlated_and_uncertain_keeps_wait(gate):
    request(gate,'base',vx=.01,duration=.2);request(gate,'wait_feedback',timeout=0)
    with pytest.raises(ValueError):event(gate,'failure',action_id=0)
    event(gate,'uncertain',action_id=1)
    with pytest.raises(ValueError):request(gate,'base',vx=.01,duration=.2)
    event(gate,'failure',action_id=1);request(gate,'base',vx=.01,duration=.2)
    assert gate.action_id==2

def test_repeated_and_cross_attempt_events(gate):
    a=gate.operator('attempt-1','event1','success');assert gate.operator('attempt-1','event1','success')==a
    assert len(gate.events)==1
    with pytest.raises(ValueError):gate.operator('attempt-0','event1','success')
    with pytest.raises(ValueError):gate.operator('attempt-1','event1','stop')
    with pytest.raises(ValueError):event(gate,'failure',action_id=0)

def test_no_success_without_operator(gate):
    with pytest.raises(ValueError):request(gate,'finish',outcome='success')
    assert gate.terminal is None

def test_read_ack_is_separate_from_delivery(gate):
    e=event(gate,'success');gate.delivered(e['event_id']);assert gate.events[0]['read_unix'] is None
    request(gate,'ack_events',event_ids=[e['event_id']]);assert gate.events[0]['read_unix']

def test_idempotent_motion(gate):
    r=dict(op='base',id='once',vx=.01,duration=.2);a=gate.request(r);assert gate.request(r)==a;assert gate.action_id==1
    with pytest.raises(ValueError):gate.request(dict(r,vx=.02))

def test_relative_head_limit(gate):
    with pytest.raises(ValueError):request(gate,'move',targets={'head_1':5.},duration=5)
    assert request(gate,'schema')['joints']['head_1']['minimum']>1.5

def wait_done(c):
    deadline=time.monotonic()+8
    while c.thread.is_alive() and time.monotonic()<deadline:time.sleep(.02)
    assert not c.thread.is_alive()

def test_demo_full_cycle_pause_restart_no_autostart(tmp_path):
    c=Controller(tmp_path,'demo')
    try:
        aid=c.start()
        with pytest.raises(ValueError):c.start()
        for _ in range(200):
            if c.gate and c.gate.active:break
            time.sleep(.02)
        assert c.gate.active
        with pytest.raises(ValueError):c.pause()
        c.outcome(attempt_id=aid,event_id='success1',outcome='success');wait_done(c)
        assert c.data['phase']=='ended';assert len(c.data['attempts'])==1
        c.pause();assert c.data['phase']=='paused';assert c.service is None
    finally:c.close()
    d=Controller(tmp_path,'demo')
    try:
        assert d.data['next_index']==2;assert d.thread is None;assert len(d.data['attempts'])==1
    finally:d.close()

def test_restart_preserves_interrupted_attempt(tmp_path):
    (tmp_path/'campaign.json').write_text(json.dumps(dict(version=1,next_index=2,phase='running',mode='demo',attempts=[dict(id='pilot-001',status='running')])))
    c=Controller(tmp_path,'demo')
    try:assert c.data['attempts'][0]['status']=='interrupted';assert c.data['next_index']==2
    finally:c.close()

def test_observation_does_not_block_operator_stop(gate):
    import threading,base64
    entered=threading.Event();release=threading.Event();original=gate.call
    def slow(op,**kw):
        if op=='observe':
            entered.set();release.wait(2)
            return {'images':{'head':base64.b64encode(b'test image').decode()},'captured':123}
        return original(op,**kw)
    gate.call=slow;t=threading.Thread(target=lambda:request(gate,'observe'));t.start();assert entered.wait(1)
    event(gate,'stop');assert gate.terminal
    release.set();t.join(2);assert not t.is_alive();assert gate.latest_observation

def test_end_is_not_overwritten_by_late_agent_declaration(gate):
    event(gate,'success');request(gate,'finish',outcome='failure')
    assert gate.terminal['outcome']=='success'

def test_timing_starts_only_at_task_start(tmp_path):
    now=[20.];g=Gate('a',Motor(),tmp_path/'events.jsonl',clock=lambda:now[0]);assert g.t0 is None
    now[0]=50;g.start();now[0]=70;g.operator('a','success','success')
    assert g.terminal['unix']-g.t0==20

def test_real_pose_planner_against_fake_motor_engine(tmp_path,monkeypatch):
    controller=experiment_controller
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'control_api'))
    from engine import Engine
    from transport import FakeTransport
    cal=json.loads((Path(__file__).resolve().parents[2]/'calibration/sessions/real-001/calibration.json').read_text())
    class Clock:
        t=0.
        def monotonic(self):return self.t
    clock=Clock();engine=Engine(cal,FakeTransport(cal),clock=clock.monotonic);engine.arm()
    calls=[]
    def rpc(path,op,**kw):
        calls.append(op);return engine.request(dict(op=op,id=uuid.uuid4().hex,**kw))
    class Cancel:
        def is_set(self):return False
        def wait(self,dt):clock.t+=dt;engine.tick();return False
    c=Controller(tmp_path,'demo');c.mode='real';c.cancel=Cancel()
    monkeypatch.setattr(controller,'rpc',rpc);monkeypatch.setattr(controller,'time',clock)
    try:
        c._prepare_pose(tmp_path)
        assert 'move' in calls and engine.motion is None
        target=json.loads((Path(__file__).resolve().parents[2]/'control/elevator-task-initial-pose.json').read_text())['targets']
        for n,v in target.items():assert abs(engine.state()['joints'][n]['target']-v['q_commanded_rad'])<.002
    finally:c.lease.close()


def test_preparation_waits_for_explicit_begin(tmp_path):
    c=Controller(tmp_path,'demo')
    try:
        aid=c.start(prepare_only=True)
        for _ in range(250):
            if c.data['phase']=='ready':break
            time.sleep(.02)
        assert c.data['phase']=='ready'
        assert not c.gate.active
        assert c.gate.status()['t0'] is None
        time.sleep(.15)
        assert c.data['phase']=='ready'
        c.begin()
        for _ in range(100):
            if c.gate.active:break
            time.sleep(.02)
        assert c.gate.active and not c.gate.waiting
        c.outcome(attempt_id=aid,event_id='done',outcome='success')
        wait_done(c)
    finally:c.close()


def test_initial_pose_coordinates_head_and_arms(tmp_path,monkeypatch):
    import math
    c=Controller(tmp_path,'demo')
    try:
        c.mode='real';c.api='fake'
        targets=json.loads(c.machine['pose'].read_text())['targets']
        end={n:v['q_commanded_rad'] for n,v in targets.items()}
        end.update(head_1=math.pi,head_2=0.)
        commands=[]
        def fake_rpc(path,op,**kw):
            if op=='state':return {'joints':{n:{'target':q+.01} for n,q in end.items()},'fault':None}
            if op=='schema':return {'joints':{n:{'minimum':-10,'maximum':10,'max_target_speed':1,'max_target_acceleration':1} for n in end}}
            commands.append(kw)
        monkeypatch.setattr(experiment_controller,'rpc',fake_rpc)
        c._prepare_pose(tmp_path)
        assert len(commands)==1
        assert commands[0]['targets']==end
        assert len(end)==14
    finally:
        c.api=None;c.close()


def test_silent_feedback_allows_retry_but_success_locks(tmp_path):
    g=Gate('silent',Motor(),tmp_path/'events.jsonl');g.start()
    request(g,'move',targets={'head_2':.1},duration=1)
    request(g,'wait_feedback',timeout=0)
    assert not g.waiting
    request(g,'base',vx=.01,duration=.5)
    g.operator('silent','success','success')
    with pytest.raises(ValueError):request(g,'base',vx=.01,duration=.5)
    assert g.events[0]['target_id']=='initial-opposite-down'
