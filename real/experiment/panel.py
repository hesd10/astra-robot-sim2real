#!/usr/bin/env python3
import argparse,json,signal,threading,secrets,base64
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from controller import Controller,HERE


def serve(root,mode,port,study_kind="pilot"):
    if study_kind=='formal':
        from formal import FormalController
        controller=FormalController(root,mode)
    else:controller=Controller(root,mode)
    token=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,data,status=200,content='application/json'):
            raw=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type',content);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def valid_host(self):return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
        def do_GET(self):
            if not self.valid_host():return self.reply({'error':'Forbidden host'},403)
            if self.path=='/':return self.reply((HERE/'panel.html').read_text().replace('__TOKEN__',token).encode(),content='text/html; charset=utf-8')
            if self.path=='/summary':return self.reply(controller.snapshot())
            if self.path=='/state':return self.reply({**controller.snapshot(),'ui_session':token[:12]})
            if self.path.startswith('/live/'):
                role=self.path.split('?')[0][6:]
                if role not in ('head','left_wrist','right_wrist'):return self.reply({'error':'Unknown camera role'},404)
                try:
                    frame=controller.preview(role)
                    return self.reply(frame)
                except Exception as e:return self.reply({'error':str(e)},503)
            if self.path.startswith('/frame/'):
                role=self.path.split('?')[0][7:]
                if role not in ('head','left_wrist','right_wrist'):return self.reply({'error':'Unknown role'},404)
                observed=controller.gate.latest_observation if controller.gate else None
                if observed:
                    path=Path(observed['folder'])/(role+'.jpg')
                    if path.exists():return self.reply(path.read_bytes(),content='image/jpeg')
                return self.reply({'error':'No observation yet'},404)
            self.reply({'error':'Not found'},404)
        def do_POST(self):
            if not self.valid_host():return self.reply({'error':'Forbidden host'},403)
            # Private loopback UI: require an unguessable capability on every mutation.
            if self.headers.get('X-Panel-Token')!=token:return self.reply({'error':'Forbidden'},403)
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<8192:raise ValueError('Invalid request size')
                data=json.loads(self.rfile.read(length));op=self.path
                if op=='/start':result=controller.start(prepare_only=True)
                elif op=='/begin':result=controller.begin()
                elif op=='/outcome':result=controller.outcome(**data)
                elif op=='/stop':result=controller.stop()
                elif op=='/release':result=controller.release()
                elif op=='/pause':result=controller.pause()
                elif op=='/preview_off':result=controller.preview_off()
                elif op=='/review' and study_kind=='formal':result=controller.review(**data)
                elif op=='/append_d' and study_kind=='formal':result=controller.append_d()
                elif op=='/skip_d' and study_kind=='formal':result=controller.skip_d()
                elif op=='/refresh_setup' and study_kind=='formal':result=controller.refresh_setup()
                elif op=='/note':result=controller.note(data['text'])
                else:raise ValueError('Unknown action')
                self.reply({'ok':True,'result':result})
            except Exception as e:self.reply({'ok':False,'error':str(e)},400)
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    def shutdown(*_):threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
    print(json.dumps(dict(url=f'http://127.0.0.1:{server.server_port}',mode=mode,hardware_connected=False)),flush=True)
    try:server.serve_forever()
    finally:controller.close();server.server_close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['demo','real'],default='demo');p.add_argument('--study',choices=['pilot','formal'],default='pilot');p.add_argument('--port',type=int);p.add_argument('--records',type=Path);p.add_argument('--robot',default='Beijing');a=p.parse_args()
    import os
    profile=HERE.parent/'robots'/a.robot
    if not os.environ.get('ASTRA_ROBOT_PROFILE') and profile.is_dir():os.environ['ASTRA_ROBOT_PROFILE']=str(profile)
    records=a.records or HERE/'records'/a.mode/a.robot/a.study
    serve(records,a.mode,a.port or (8771 if a.study=='formal' else 8770),a.study)
