"""Native Codex + local SSE fixture; no real model or private scene input."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time
import uuid
from PIL import Image
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim_env.agent import run_agent
from prepare_subject import prepare


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values(): yield from walk(child)
    elif isinstance(value, list):
        for child in value: yield from walk(child)


def main():
    out = ROOT/'reports'/'runtime'/('native-boundary-'+uuid.uuid4().hex[:8]); out.mkdir(parents=True)
    subject = prepare(out/'subject')
    secret = out/'private-canary.txt'; secret.write_text('PRIVATE_CANARY_MUST_NOT_APPEAR')
    secret_image = out/'private-camera.jpg'; Image.new('RGB', (32, 32), 'red').save(secret_image)
    (subject/'escape.jpg').symlink_to(secret_image)
    for i in range(8): Image.new('RGB', (32, 32), (i*30, 90, 140)).save(subject/f'fixture-{i}.jpg')
    probe = '''import pathlib,socket,os,json,numpy as np,subprocess
r={}
def denied(name,action):
 try:action()
 except (PermissionError,OSError):r[name]=True
 else:r[name]=False
denied('private_read',lambda:pathlib.Path(%r).read_text())
denied('symlink_read',lambda:pathlib.Path('escape.jpg').read_bytes())
r['host_credentials_hidden']=True
for entry in pathlib.Path('/proc').iterdir():
 if entry.name.isdigit():
  try:environment=(entry/'environ').read_bytes()
  except OSError:continue
  if b'ASTRA_NATIVE_TOKEN=' in environment:r['host_credentials_hidden']=False
denied('network',lambda:socket.create_connection(('127.0.0.1',%d),timeout=1))
denied('dependency_write',lambda:pathlib.Path(np.__file__).open('r+b').close())
r['numpy']=bool(np.allclose(np.linalg.solve(np.eye(2),[1.,2.]),[1.,2.]))
r['credentials_absent']=not any('TOKEN' in k or 'API_KEY' in k for k in os.environ)
from robot import call
state=call('state');r['robot_rpc']=len(state['joints'])==14 and 'base_pose' not in state
pathlib.Path('native-fixture.txt').write_text('fixture')
a=subprocess.run(['git','add','native-fixture.txt'],capture_output=True)
b=subprocess.run(['git','commit','-qm','Native fixture'],capture_output=True)
r['git_commit']=a.returncode==0 and b.returncode==0
print('BOUNDARY_RESULT '+json.dumps(r))
assert all(r.values()),r
'''
    captures = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            captures.append(data)
            index = len(captures)-1
            rid = 'resp_fixture_'+str(index)
            if index == 0:
                code = 'text(await tools.exec_command('+json.dumps({'cmd':'python3 boundary_probe.py', 'yield_time_ms':10000, 'max_output_tokens':3000})+'))'
            elif index <= 8:
                code = 'image((await tools.view_image('+json.dumps({'path':str(subject/f'fixture-{index-1}.jpg')})+')).image_url)'
            elif index <= 10:
                path = secret_image if index == 9 else subject/'escape.jpg'
                code = 'image((await tools.view_image('+json.dumps({'path':str(path)})+')).image_url)'
            else: code = None
            if code:
                item = {'id':'tool_'+rid,'type':'custom_tool_call','call_id':'call_'+rid,
                        'name':'exec','namespace':'functions','input':code}
            else:
                item = {'id':'msg_'+rid,'type':'message','role':'assistant',
                        'content':[{'type':'output_text','text':'Native fixture complete.'}]}
            events = [{'type':'response.created','response':{'id':rid}},
                      {'type':'response.output_item.done','output_index':0,'item':item},
                      {'type':'response.completed','response':{'id':rid,'status':'completed','output':[item],
                       'usage':{'input_tokens':100+index*100,'output_tokens':20,'total_tokens':120+index*100}}}]
            body = ''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
            self.send_response(200); self.send_header('Content-Type','text/event-stream')
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    (subject/'boundary_probe.py').write_text(probe%(str(secret), server.server_port))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    sock = Path('/tmp')/('astra-native-'+uuid.uuid4().hex[:12]+'.sock')
    with (out/'service.log').open('w') as log:
        service = subprocess.Popen([sys.executable,'-m','sim_env.service','--socket-path',str(sock),
            '--log-dir',str(out/'simulation'),'--no-render','--no-monitor','--wall-seconds','90'],
            cwd=ROOT,stdout=log,stderr=log)
        try:
            deadline = time.monotonic()+30
            while not sock.exists():
                assert service.poll() is None and time.monotonic()<deadline
                time.sleep(.1)
            result = run_agent(subject,sock,out,provider={'base_url':f'http://127.0.0.1:{server.server_port}/v1',
                'token':'LOCAL_FIXTURE_ONLY','model':'gpt-6-astra'},max_seconds=75,prompt='Local tool fixture only.')
            (out/'captured-requests.json').write_text(json.dumps(captures))
            assert result['status']=='completed', result
            assert len(captures)==12, len(captures)
            results = [v for v in walk(captures[1]['input']) if isinstance(v,str) and 'BOUNDARY_RESULT {' in v]
            assert results, 'native shell output absent'
            line = json.loads(results[-1])['output'].split('BOUNDARY_RESULT ')[1].split('\n')[0]
            boundary = json.loads(line); assert all(boundary.values()), boundary
            images = [sum(1 for v in walk(c['input']) if isinstance(v,dict) and v.get('type')=='input_image') for c in captures]
            assert images[9] == 8, images  # Native context contains >6 reads.
            assert images[10] == images[11] == 8, images  # Private and symlink reads add none.
            assert secret.read_text()=='PRIVATE_CANARY_MUST_NOT_APPEAR'
            for c in captures:
                assert 'PRIVATE_CANARY_MUST_NOT_APPEAR' not in json.dumps(c)
            report = {'passed':True,'real_model_called':False,'runner':result['runner'],
                'codex_version':result['codex_version'],'boundary':boundary,
                'image_counts_in_native_requests':images,'private_image_reads_rejected':True,
                'request_limit':None,'image_history_limit':None}
            (out/'checks.json').write_text(json.dumps(report,indent=2)+'\n');print('PASS',out,json.dumps(report))
        finally:
            if service.poll() is None: service.terminate();service.wait(timeout=15)
            server.shutdown();server.server_close()


if __name__=='__main__': main()
