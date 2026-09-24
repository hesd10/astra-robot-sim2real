#!/usr/bin/env python3
"""Local-only passive calibration UI. No automatic torque changes on startup."""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import argparse, base64, json, mimetypes, secrets, urllib.parse, os
from controller import Controller, ROOT, atomic_json

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,controller,workflow=None):
        self.workflow=workflow
        self.controller=controller;self.token=secrets.token_urlsafe(32)
        super().__init__(address,Handler)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args):
        if args and str(args[0]).startswith('GET /api/state'):return
        super().log_message(fmt,*args)
    def valid_host(self):
        return self.headers.get('Host') in [f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}']
    def send(self,status,body,ctype='application/json',extra=None):
        if isinstance(body,(dict,list)):body=json.dumps(body,ensure_ascii=False,allow_nan=False).encode()
        if isinstance(body,str):body=body.encode()
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        for k,v in (extra or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if not self.valid_host():return self.send(403,{'error':'Local host only'})
        path=urllib.parse.urlparse(self.path).path
        if path=='/api/state':
            with self.server.controller.lock:
                result=self.server.controller.status()
                if self.server.workflow:result['machines']=self.server.workflow.state()
                return self.send(200,result)
        if path.startswith('/api/machine/image/') and self.server.workflow:
            key=path.rsplit('/',1)[-1]
            if not key.isdigit():return self.send(404,{'error':'Invalid image'})
            file=self.server.workflow.path()/'camera-preview'/(key+'.jpg')
            if not file.exists():return self.send(404,{'error':'No image'})
            return self.send(200,file.read_bytes(),'image/jpeg')
        if path=='/api/machine/archive' and self.server.workflow:
            meta=self.server.workflow.registry.status(self.server.workflow.name);kind=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('kind',['ready'])[0]
            if kind not in ('ready','initial','snapshot'):return self.send(400,{'error':'Invalid backup kind'})
            record=meta.get('latest_'+kind)
            if not record and kind in ('initial','ready') and meta.get('backup_index'):
                record=json.loads(Path(meta['backup_index']).read_text())['initial_state' if kind=='initial' else 'ready_for_experiment']
            if not record:return self.send(404,{'error':'尚未生成ready备份'})
            file=Path(record['archive'])
            return self.send(200,file.read_bytes(),'application/zip',{'Content-Disposition':'attachment; filename=robot-backup.zip'})
        if path=='/api/export':
            with self.server.controller.lock:body=self.server.controller.export()
            return self.send(200,body,'application/zip',{'Content-Disposition':'attachment; filename="passive-calibration.zip"'})
        if path=='/':
            body=(ROOT/'static/index.html').read_text().replace('__TOKEN__',self.server.token)
            return self.send(200,body,'text/html; charset=utf-8')
        target=(ROOT/'static'/path.lstrip('/')).resolve()
        if not target.is_relative_to((ROOT/'static').resolve()) or not target.is_file():return self.send(404,{'error':'Not found'})
        return self.send(200,target.read_bytes(),mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-Calib-Token')!=self.server.token:return self.send(403,{'error':'操作来源无效，请刷新页面'})
        origin=self.headers.get('Origin')
        if origin and origin not in [f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}']:return self.send(403,{'error':'来源不匹配'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=8_000_000:raise ValueError('请求大小无效')
            p=json.loads(self.rfile.read(size))
            if not isinstance(p,dict):raise ValueError('请求格式无效')
            path=urllib.parse.urlparse(self.path).path
            if path.startswith('/api/machine/') and self.server.workflow:
                w=self.server.workflow
                with self.server.controller.lock:
                    w.action(path.rsplit('/',1)[-1],p)
                    self.server.controller=w.controller
                    result=w.controller.status();result['machines']=w.state()
                return self.send(200,result)
            with self.server.controller.lock:
                c=self.server.controller
                if self.server.workflow:
                    w=self.server.workflow
                    if p.get('_robot',w.name)!=w.name:raise ValueError('选中的机器人已变化，请刷新页面')
                    if w.thread and w.thread.is_alive():raise ValueError('请先等待当前工作流任务完成')
                    if w.process:raise ValueError('请先结束主动测试连接，再修改或连接被动标定；不会释放torque')
                    if path=='/api/action/connect' and not w.registry.status(w.name).get('initial_backup') and not c.demo:raise ValueError('新机器请先在配置页建立初始备份')
                if path=='/api/camera_import':
                    if c.capture:raise ValueError('请先结束采集')
                    entries=p.get('files',[])
                    if not entries or len(entries)>10:raise ValueError('请选择 1–10 份 JSON/YAML 标定文件')
                    prepared=[]
                    for entry in entries:
                        name=entry['name']
                        if Path(name).name!=name or Path(name).suffix.lower() not in ['.json','.yaml','.yml']:raise ValueError('仅允许 JSON/YAML 参数文件')
                        data=base64.b64decode(entry['data'],validate=True)
                        if len(data)>2_000_000:raise ValueError('单文件太大')
                        if name.endswith('.json'):json.loads(data)
                        prepared.append((name,data))
                    import hashlib
                    folder=c.ws/'camera-import';folder.mkdir(exist_ok=True)
                    version=secrets.token_hex(4);items=[]
                    for name,data in prepared:
                        dest=folder/(version+'-'+name);dest.write_bytes(data)
                        items.append(dict(name=dest.name,source_name=name,sha256=hashlib.sha256(data).hexdigest()))
                    c.data['camera']=dict(status='historical_reference_only',files=items,note=str(p.get('note',''))[:2000],validated_for_current_setup=False)
                    c.save();c.audit(dict(kind='camera_reference_imported',files=items))
                    if self.server.workflow:
                        from registry import read,write
                        config_file=self.server.workflow.path()/'camera-config.json';config=read(config_file,{})
                        config.update(parameter_source='imported_reference',reference_files=items,validated_for_current_setup=False)
                        write(config_file,config)
                    result=c.status()
                elif path.startswith('/api/action/'):
                    result=c.action(path.split('/')[-1],p)
                else:return self.send(404,{'error':'Unknown endpoint'})
            return self.send(200,result)
        except (ValueError,KeyError,TypeError,RuntimeError,OSError) as e:
            return self.send(400,{'error':str(e)})
        except Exception as e:
            self.server.controller.audit(dict(kind='api_error',error=repr(e)))
            return self.send(500,{'error':'操作未完成：'+str(e)})

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--demo',action='store_true',help='Offline UI and tests; never opens serial devices')
    parser.add_argument('--workspace',type=Path)
    parser.add_argument('--robot',default='Beijing',help='Named robot profile')
    args=parser.parse_args()
    workspace=args.workspace or ROOT.parent/('robots-demo' if args.demo else 'robots')/'.manager'
    # A session may not be silently switched between demo and real hardware.
    workspace.mkdir(parents=True,exist_ok=True)
    import fcntl
    session_lock=(workspace/'.server.lock').open('a')
    fcntl.flock(session_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    mode=workspace/'mode.json'
    if mode.exists() and json.loads(mode.read_text())['demo']!=args.demo:raise RuntimeError('不能混用演示与实机工作区')
    atomic_json(mode,dict(demo=args.demo))
    from registry import Registry
    from workflow import Workflow
    registry=Registry(demo=args.demo);registry.import_beijing()
    if args.robot not in registry.names():registry.create(args.robot)
    workflow=Workflow(registry,Controller);controller=workflow.load(args.robot)
    meta=json.loads((registry.path(args.robot)/'profile.json').read_text())
    if meta.get('backup_index') and not (registry.path(args.robot)/'parameters.json').exists():
        plan=workflow.generate()
        index=json.loads(Path(meta['backup_index']).read_text());prior=json.loads((Path(index['ready_for_experiment']['directory'])/'REPORT.json').read_text())
        if all(plan['motors'][m['key']]['acceleration']==m['acceleration'] and plan['motors'][m['key']]['speed']==m['goal_velocity'] for m in prior['motors']):
            for section in ('joints','base'):registry.accept(args.robot,section,'Imported operator-confirmed Beijing tests; generated parameter values match the sealed ready backup.')
    server=Server(('127.0.0.1',args.port),controller,workflow)
    print(f'Passive calibration: http://127.0.0.1:{server.server_port}',flush=True)
    print(f'Workspace: {workspace.resolve()} | demo={args.demo} | no automatic connection or torque writes',flush=True)
    import signal,threading
    def shutdown(*_):threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        workflow.stop()
        if workflow.thread and workflow.thread.is_alive():workflow.thread.join(timeout=12)
        workflow.close_service()
        with server.controller.lock:server.controller.running=False;server.controller.disconnect()
        server.server_close();session_lock.close()
if __name__=='__main__':main()
