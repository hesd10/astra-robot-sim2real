"""Exercise real filesystem/syscall restrictions without reading any images."""
import json
from pathlib import Path
import subprocess
import sys
import uuid
from prepare_subject import prepare, ROOT


def run():
    base=ROOT/'reports'/'runtime'/('isolation-'+uuid.uuid4().hex[:8])
    base.mkdir(parents=True)
    subject=prepare(base/'subject')
    secret=base/'private-canary.txt'
    secret.write_text('private-test-canary')
    (subject/'escape').symlink_to(secret)
    code='''import pathlib,socket,os,json,subprocess
import numpy as np
results={}
def denied(name, action):
 try: action()
 except (PermissionError,OSError): results[name]=True
 else: results[name]=False
denied('private_read',lambda:pathlib.Path(%r).read_text())
denied('symlink_escape',lambda:pathlib.Path('escape').read_text())
denied('proc_read',lambda:pathlib.Path('/proc/1/environ').read_bytes())
denied('network',lambda:socket.socket(socket.AF_INET,socket.SOCK_STREAM))
denied('other_socket',lambda:socket.socket(socket.AF_UNIX,socket.SOCK_STREAM))
denied('private_truncate',lambda:os.truncate(%r,0))
denied('outside_write',lambda:pathlib.Path(%r).write_text('changed'))
results['numpy_compute']=bool(np.allclose(np.linalg.solve(np.eye(2),np.array([1.,2.])),[1.,2.]))
denied('dependency_write',lambda:pathlib.Path(np.__file__).open('r+b').close())
results['own_read']='Robot interface' in pathlib.Path('API.md').read_text()
pathlib.Path('new.txt').write_text('synthetic check')
r=subprocess.run(['git','add','new.txt'],capture_output=True)
s=subprocess.run(['git','commit','-m','Synthetic isolation check'],capture_output=True)
results['own_commit']=r.returncode==0 and s.returncode==0
print(json.dumps(results))
assert all(results.values()),results
'''%(str(secret),str(secret),str(secret))
    result=subprocess.run([sys.executable,'-m','sim_env.isolate','--workspace',str(subject),
                           '--','/usr/bin/python3','-c',code],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0,(result.stdout,result.stderr)
    assert secret.read_text()=='private-test-canary'
    report=json.loads(result.stdout)
    (base/'checks.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS',base,json.dumps(report))


if __name__=='__main__':run()
