import os,sys,json,socket,subprocess,time
from pathlib import Path
import pytest
HERE=Path(__file__).resolve().parents[1]
def exchange(path,request):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
        s.settimeout(5);s.connect(str(path));s.sendall((json.dumps(request)+'\n').encode());return json.loads(s.makefile('rb').readline())
@pytest.fixture
def server(tmp_path):
    path=tmp_path/'api.sock';log=(tmp_path/'log').open('w');p=subprocess.Popen([sys.executable,str(HERE/'service.py'),'--demo','--arm','--enable-base','--socket',str(path)],stdout=log,stderr=log)
    try:
        for _ in range(100):
            if path.exists():break
            if p.poll() is not None:raise RuntimeError('Service failed')
            time.sleep(.03)
        yield path
    finally:p.terminate();p.wait(timeout=5);log.close()
def test_socket_expiry_without_new_requests(server):
    assert exchange(server,dict(op='base',id='b',vx=.02,duration=.1))['ok']
    time.sleep(.25);r=exchange(server,dict(op='state',id='s'))['result'];assert r['base_command']==[0,0,0]
def test_socket_retry_and_finish(server):
    r=dict(op='move',id='m',targets={'left_1':.05},duration=1)
    a=exchange(server,r);assert a['ok'];assert exchange(server,r)==a
    assert not exchange(server,dict(r,duration=2))['ok']
    assert exchange(server,dict(op='finish',id='f',outcome='failure'))['ok']
    assert not exchange(server,dict(op='move',id='new',targets={'left_1':.1},duration=1))['ok']
def test_camera_roles_required(server):
    r=exchange(server,dict(op='observe',id='o'));assert not r['ok'] and 'mapping' in r['error']
def test_supervisor_owner_crash_exits(tmp_path):
    # Demo watchdog test: kill owner, verify supervisor detects pipe EOF and exits.
    path=tmp_path/'supervised.sock';p=subprocess.Popen([sys.executable,str(HERE/'supervised.py'),'--demo','--arm','--enable-base','--socket',str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        for _ in range(100):
            if path.exists():break
            time.sleep(.03)
        children=Path(f'/proc/{p.pid}/task/{p.pid}/children').read_text().split();assert len(children)==1
        os.kill(int(children[0]),9);p.wait(timeout=5)
    finally:
        if p.poll() is None:p.terminate();p.wait(timeout=5)
