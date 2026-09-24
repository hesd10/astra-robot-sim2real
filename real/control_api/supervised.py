#!/usr/bin/env python3
"""Independent process watchdog for powered base. No temperature logic.
On missing heartbeat/owner exit, close owner then reopen buses and send wheel zero.
Host power/USB loss still requires the physical power switch; software cannot stop
an unreachable actuator. Never enables a motor or drops a holding arm here.
"""
import os,sys,select,subprocess,time,json,signal
from pathlib import Path
from machine import paths
from transport import Transport,ROOT,BACKUP
HERE=Path(__file__).resolve().parent
if __name__=='__main__':
    selected=paths();supervisor_cal=json.loads(selected['calibration'].read_text())
    read_fd,write_fd=os.pipe();log=HERE/'runtime/watchdog.jsonl';log.parent.mkdir(exist_ok=True)
    def audit(e):
        with log.open('a') as f:f.write(json.dumps(dict(e,unix=time.time()))+'\n');f.flush()
    child=subprocess.Popen([sys.executable,str(HERE/'service.py'),*sys.argv[1:],'--heartbeat-fd',str(write_fd)],pass_fds=(write_fd,));os.close(write_fd)
    def stop(*_):
        if child.poll() is None:child.terminate()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    last=time.monotonic();deadline=10 # startup allowance, before any motion API is available
    try:
        while child.poll() is None:
            readable,_,_=select.select([read_fd],[],[],.2)
            if readable:
                msg=os.read(read_fd,4096)
                if not msg:break
                last=time.monotonic();deadline=2
            if time.monotonic()-last>deadline:
                audit(dict(event='heartbeat_timeout'));child.kill();break
    finally:
        if child.poll() is None:child.terminate()
        try:child.wait(timeout=1)
        except subprocess.TimeoutExpired:child.kill();child.wait()
        os.close(read_fd)
        if '--demo' not in sys.argv:
            h=Transport(selected['backup'],audit)
            try:
                initial=h.connect();c=supervisor_cal;h.sync(46,2,{w['motor']:0 for w in c['wheels'].values()},True);h.sync(40,1,{w['motor']:initial[w['motor']]['torque'] for w in c['wheels'].values()},True);audit(dict(event='wheel_zero_verified'))
            except Exception as e:audit(dict(event='wheel_stop_unconfirmed',error=str(e)));print('WHEEL STOP UNCONFIRMED: '+str(e),file=sys.stderr)
            finally:h.close()
