"""Minimal stdio MCP broker. The subject must receive ONLY these tools.

No API key or model invocation here: this is the boundary used by a fresh
experiment session. The private service and broker stay outside its filesystem.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = '2024-11-05'


class Broker:
    def __init__(self, workspace, socket_path, audit):
        self.workspace = Path(workspace).resolve(strict=True)
        self.socket_path = str(socket_path)
        self.audit_path = Path(audit)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.write_lock = threading.Lock()
        self.work_lock = threading.Lock()

    def audit(self, row):
        row['wall_time'] = time.time()
        with self.audit_path.open('a') as stream:
            stream.write(json.dumps(row, ensure_ascii=False)+'\n')

    def execute(self, args, timeout=60):
        command = [sys.executable, '-m', 'sim_env.isolate', '--workspace', str(self.workspace),
                   '--socket-path', self.socket_path, '--']+args
        # File-backed output bounds memory even if subject code prints endlessly.
        import tempfile
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            p = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr, start_new_session=True)
            timed_out = False
            try:
                p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                import signal
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
                timed_out = True
            stdout.seek(0); stderr.seek(0)
            out, err = stdout.read(4*1024*1024), stderr.read(65536)
        return {'exit_code': p.returncode, 'timed_out': timed_out,
                'stdout': out.decode(errors='replace'), 'stderr': err.decode(errors='replace')}

    def tools(self):
        return [
            {'name':'run', 'description':'Run a shell command inside the current isolated experiment workspace. Use robot.py for low-level robot commands. No external filesystem/network access.',
             'inputSchema':{'type':'object','properties':{'command':{'type':'string'},'timeout_seconds':{'type':'number','minimum':1,'maximum':60}},'required':['command'],'additionalProperties':False}},
            {'name':'view_camera_image', 'description':'Read a saved onboard camera JPEG from this current workspace. No other image source is available.',
             'inputSchema':{'type':'object','properties':{'path':{'type':'string'}},'required':['path'],'additionalProperties':False}}
        ]

    def call(self, name, args):
        if name == 'run':
            if not isinstance(args.get('command'), str) or set(args)-{'command','timeout_seconds'}:
                raise ValueError('invalid command')
            timeout = float(args.get('timeout_seconds',60))
            if not 1 <= timeout <= 60: raise ValueError('invalid timeout')
            self.audit({'event':'tool_start','tool':name,'command':args['command']})
            result = self.execute(['/bin/bash','--noprofile','--norc','-c',args['command']],timeout)
            self.audit({'event':'tool_end','tool':name,'exit_code':result['exit_code'],'timed_out':result['timed_out']})
            return {'content':[{'type':'text','text':json.dumps(result,ensure_ascii=False)}], 'isError':result['exit_code'] != 0}
        if name == 'view_camera_image':
            path = args.get('path')
            if not isinstance(path,str) or set(args) != {'path'}:
                raise ValueError('invalid image path')
            # Resolve/open inside the SAME restricted process as all other reads.
            # The broker itself never reads a subject-supplied path on the host.
            code = '''import pathlib,base64,sys
p=pathlib.Path(sys.argv[1]).resolve(strict=True)
p.relative_to(pathlib.Path.cwd())
assert p.suffix.lower() in ('.jpg','.jpeg') and p.stat().st_size <= 2000000
data=p.read_bytes()
assert data[:2] == bytes([255,216])
print(base64.b64encode(data).decode())
'''
            result = self.execute(['/usr/bin/python3','-c',code,path])
            if result['exit_code']:
                raise ValueError('image unavailable in current workspace')
            encoded = result['stdout'].strip()
            base64.b64decode(encoded,validate=True)
            self.audit({'event':'image_read','path':path})
            return {'content':[{'type':'image','mimeType':'image/jpeg','data':encoded}]}
        raise ValueError('unknown tool')

    def handle(self, req):
        ident = req.get('id')
        method = req.get('method')
        if ident is None:
            return
        try:
            if method == 'initialize':
                result = {'protocolVersion':PROTOCOL,'capabilities':{'tools':{}},
                          'serverInfo':{'name':'astra-isolated-robot','version':'1.0.0'}}
            elif method == 'ping': result = {}
            elif method == 'tools/list': result = {'tools':self.tools()}
            elif method == 'tools/call':
                params=req.get('params',{})
                with self.work_lock:
                    result = self.call(params.get('name'),params.get('arguments',{}))
            else: raise ValueError('unsupported method')
            response = {'jsonrpc':'2.0','id':ident,'result':result}
        except Exception:
            # No private paths, tracebacks, scene names or evaluation data leak.
            response = {'jsonrpc':'2.0','id':ident,'error':{'code':-32602,'message':'Request rejected or tool unavailable'}}
        with self.write_lock:
            print(json.dumps(response),flush=True)

    def run(self):
        for line in sys.stdin:
            if len(line)>1024*1024: continue
            try: req=json.loads(line)
            except ValueError: continue
            # Sequential tools intentionally enforce the single-agent protocol.
            self.handle(req)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--socket-path',required=True)
    parser.add_argument('--audit',required=True)
    args=parser.parse_args()
    Broker(**vars(args)).run()
