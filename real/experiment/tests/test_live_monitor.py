from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"control_api"))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json,time
from cameras import Cameras
from runtime.workflow import Workflow
import pytest

def test_preview_nonblocking_freshness_and_errors():
    c=Cameras({'roles_confirmed':True})
    with pytest.raises(RuntimeError,match='warming'):c.preview('head')
    now=time.monotonic();c.frames['head']=(now,now,'jpeg',(480,640))
    assert c.preview('head')['image']=='jpeg'
    c.frames['head']=(now-5,now-5,'old',(480,640))
    with pytest.raises(RuntimeError,match='stale'):c.preview('head')
    with pytest.raises(ValueError):c.preview('unknown')

def test_feed_partial_output_robot_request_and_reasoning_privacy(tmp_path):
    path=tmp_path/'agent-workflow.jsonl'
    rows=[dict(event='item/started',monotonic=time.monotonic(),id='cmd',kind='commandExecution',command='robot move'),dict(event='item/commandExecution/outputDelta',monotonic=time.monotonic(),id='cmd',delta='in progress'),dict(event='item/started',monotonic=time.monotonic(),id='secret',kind='reasoning')]
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    (tmp_path/'operator-events.jsonl').write_text(json.dumps(dict(kind='request',unix=time.time(),request={'id':'r1','op':'move','targets':{'head_1':3.14}},result={'accepted':True}))+'\n')
    w=Workflow(tmp_path,path)
    try:
        deadline=time.monotonic()+2
        while w.snapshot()['total_entries']<2 and time.monotonic()<deadline:time.sleep(.02)
        entries=w.snapshot()['entries']
        cmd=next(e for e in entries if e['id']=='agent:cmd')
        assert cmd['command']=='robot move' and cmd['output']=='in progress'
        assert any(e['id']=='robot:r1' for e in entries)
        assert not any(e['id']=='agent:secret' for e in entries)
    finally:w.close()


def test_three_view_recording_is_playable_and_timestamped(tmp_path):
    import cv2,numpy as np,base64
    from recording import Recorder
    c=Cameras({'roles_confirmed':True});rec=Recorder(c,tmp_path/'video',fps=10)
    try:
        for i in range(8):
            ok,jpg=cv2.imencode('.jpg',np.full((48,64,3),i*25,dtype=np.uint8));assert ok
            now=time.monotonic()
            with c.cv:
                for role in rec.roles:c.frames[role]=(now,now,base64.b64encode(jpg).decode(),(48,64))
            time.sleep(.12)
    finally:status=rec.close()
    assert not status['error'] and not status['active']
    rows=[json.loads(line) for line in (tmp_path/'video/frames.jsonl').read_text().splitlines()]
    for role in rec.roles:
        cap=cv2.VideoCapture(str(tmp_path/'video'/(role+'.avi')));count=0
        while True:
            ok,frame=cap.read()
            if not ok:break
            count+=1
        cap.release();assert count==status['frames'][role]>=5
        assert len([r for r in rows if r['role']==role])==count
