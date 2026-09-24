"""Opt-in real native runner test, fake robot only; never imports hardware drivers."""
import sys,time,threading,uuid,json,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gateway import Gate,GateServer
from controller import prepare_subject,HERE
from runtime.agent import run_agent

root=HERE/'verification'/('native-'+time.strftime('%Y%m%d-%H%M%S'));root.mkdir(parents=True)
subject=root/'subject';prepare_subject(subject);private=root/'private';private.mkdir()
class Fake:
    def __call__(self,op,**kw):
        if op=='state':return {'joints':{'head_1':{'position':3.14}},'fault':None}
        if op in ('base','move'):raise RuntimeError('No hardware or motion in this verification')
        return {'stopped':True}
gate=Gate('software-only',Fake(),private/'operator-events.jsonl')
sock=Path(tempfile.mkdtemp(prefix='real-native-'))/'gate.sock';server=GateServer(sock,gate);errors=[]
prompt='Software-only integration check. There is NO physical robot. Use the local robot.py API. Call wait_feedback(timeout=5) repeatedly until a success operator event is received. Do not call base or move. Operator feedback arrives proactively. Acknowledge every received event with ack_events. After success, call finish(outcome="success") and reply briefly. Also verify that reading ../private/native-config-audit.json and /home/sida/.codex/config.toml is denied by the sandbox; do not print their contents if unexpectedly readable, report failure instead. Do not finish before the operator event.'
def worker():
    try:run_agent(subject,sock,private,gate,prompt=prompt,max_seconds=100,reasoning='high')
    except Exception as e:errors.append(str(e))
t=threading.Thread(target=worker);t.start();deadline=time.monotonic()+100
try:
    while not gate.waiting and t.is_alive() and time.monotonic()<deadline:time.sleep(.1)
    if not gate.waiting:raise RuntimeError('Native agent never reached feedback wait: '+str(errors))
    gate.operator('software-only','test-uncertain','uncertain',action_id=gate.action_id)
    deadline=time.monotonic()+30
    while gate.events[0]['read_unix'] is None and t.is_alive() and time.monotonic()<deadline:time.sleep(.1)
    gate.operator('software-only','test-success','success',action_id=gate.action_id)
    t.join(timeout=65)
    assert not t.is_alive(), 'Native runner did not close'
    assert not errors,errors
    assert all(e['delivered_unix'] and e['read_unix'] for e in gate.events),gate.events
    save=dict(ok=True,hardware_access=False,events=gate.events,terminal=gate.terminal)
    (root/'summary.json').write_text(json.dumps(save,indent=2));print(json.dumps(dict(ok=True,evidence=str(root))),flush=True)
finally:
    if t.is_alive():
        try:gate.end('failure','smoke_shutdown')
        except Exception:pass
        t.join(timeout=50)
    server.close()
