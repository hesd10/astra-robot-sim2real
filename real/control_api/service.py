#!/usr/bin/env python3
"""Unix-socket API, single motor owner, independent observation threads."""
import argparse,json,os,socketserver,threading,time,signal,sys,copy
from pathlib import Path
from machine import paths
from transport import Transport,FakeTransport,ROOT,BACKUP
from engine import Engine
from cameras import Cameras
from recording import Recorder
HERE=Path(__file__).resolve().parent
class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads=True
class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(12)
        try:
            raw=self.rfile.readline(16385)
            if not raw.endswith(b'\n') or len(raw)>16384:raise ValueError('Invalid request size')
            r=json.loads(raw,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
            if not isinstance(r,dict):raise ValueError('Expected object')
            if r.get('op') in ('recording_status','recording_stop'):
                recorder=self.server.recorder
                result=(recorder.close() if r['op']=='recording_stop' else recorder.status()) if recorder else {'active':False,'error':'No recorder configured'}
            elif r.get('op')=='preview':
                result=self.server.cameras.preview(r.get('role'))
                if self.server.recorder:result['recording']=self.server.recorder.status()
            elif r.get('op')=='observe':
                if not isinstance(r.get('id'),str) or not 1<=len(r['id'])<=128:raise ValueError('Request id required')
                result=self.server.cameras.observe()
            else:
                with self.server.lock:result=self.server.engine.request(r)
            response={'ok':True,'result':result}
        except Exception as e:
            if isinstance(e,RuntimeError) and isinstance(locals().get('r'),dict) and r.get('op') in ['move','base','stop','finish']:
                with self.server.lock:
                    self.server.engine.fault=str(e)
                    try:self.server.engine.stop()
                    except Exception:pass
            response={'ok':False,'error':str(e)}
        self.wfile.write((json.dumps(response,allow_nan=False)+'\n').encode())
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--socket',type=Path,default=Path('/tmp')/f'astra-real-{os.getuid()}'/'robot.sock');ap.add_argument('--demo',action='store_true');ap.add_argument('--arm',action='store_true');ap.add_argument('--enable-base',action='store_true');ap.add_argument('--base-only',action='store_true');ap.add_argument('--heartbeat-fd',type=int);ap.add_argument('--recording-dir',type=Path);args=ap.parse_args()
    if args.enable_base and not args.demo and args.heartbeat_fd is None:ap.error('Powered base requires supervised.py watchdog')
    if len(os.fsencode(args.socket))>100:ap.error('Unix socket path is too long; use a short /tmp path')
    args.socket.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if args.socket.exists():raise RuntimeError('Socket already exists; verify old owner before removing')
    logpath=args.socket.parent/('api-'+time.strftime('%Y%m%d-%H%M%S')+'.jsonl')
    def audit(e):
        with logpath.open('a') as f:f.write(json.dumps(dict(e,unix=time.time()),allow_nan=False)+'\n');f.flush()
    selected=paths();cal=json.loads(selected['calibration'].read_text())
    hw=FakeTransport(cal,audit) if args.demo else Transport(selected['backup'],audit)
    engine=None;server=None;recorder=None;done=threading.Event();cameras=Cameras(json.loads(selected['cameras'].read_text()))
    if args.demo:cameras.config['roles_confirmed']=False
    try:
        engine=Engine(cal,hw,audit,base_enabled=args.enable_base)
        if args.arm:engine.arm(arms=not args.base_only)
        server=Server(str(args.socket),Handler);os.chmod(args.socket,0o600);server.engine=engine;server.lock=threading.RLock();server.cameras=cameras
        if not args.demo:cameras.start()
        if args.recording_dir and not args.demo:recorder=Recorder(cameras,args.recording_dir)
        server.recorder=recorder
        def worker():
            while not done.is_set():
                begin=time.monotonic()
                try:
                    with server.lock:
                        if not engine.fault:engine.tick()
                    if args.heartbeat_fd is not None:os.write(args.heartbeat_fd,b'.')
                except Exception as e:
                    with server.lock:
                        engine.fault=str(e);audit(dict(event='motor_fault',error=str(e)))
                        try:engine.stop()
                        except Exception as se:audit(dict(event='stop_failed',error=str(se)))
                    # Stop heartbeats: supervisor will make a separate zero-speed attempt.
                    if args.heartbeat_fd is not None:done.set();break
                done.wait(max(0,.05-(time.monotonic()-begin)))
        t=threading.Thread(target=worker,daemon=True);t.start()
        def stop_signal(*_):threading.Thread(target=server.shutdown,daemon=True).start()
        signal.signal(signal.SIGINT,stop_signal);signal.signal(signal.SIGTERM,stop_signal)
        print(json.dumps(dict(ready=True,socket=str(args.socket),armed=args.arm,base=args.enable_base,demo=args.demo)),flush=True)
        server.serve_forever(poll_interval=.1)
    finally:
        done.set()
        if recorder:recorder.close()
        cameras.close()
        if 't' in locals():t.join(timeout=3)
        if engine:
            try:engine.stop()
            except Exception as e:audit(dict(event='shutdown_stop_failed',error=str(e)))
        if server:server.server_close();args.socket.unlink(missing_ok=True)
        hw.close()
        if args.heartbeat_fd is not None:os.close(args.heartbeat_fd)
if __name__=='__main__':main()
