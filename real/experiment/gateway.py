"""Private operator gate. The subject never receives an operator capability."""
import json, threading, time, uuid, socket, socketserver, copy, base64
from pathlib import Path


def rpc(path, op, **fields):
    request={'op':op,'id':uuid.uuid4().hex,**fields}
    # Retry only connect refusal: no request bytes have been sent yet.
    # Keep the request ID stable and never replay after a send/read failure.
    for attempt in range(4):  # initial connection plus at most three reconnects
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
            s.settimeout(12)
            try:s.connect(str(path))
            except ConnectionRefusedError:
                if attempt==3:raise
            else:
                s.sendall((json.dumps(request)+'\n').encode())
                with s.makefile('rb') as f:response=json.loads(f.readline(8*1024*1024))
                break
        time.sleep(.5*(attempt+1))
    if not response['ok']:raise RuntimeError(response['error'])
    return response['result']


class Gate:
    def __init__(self,attempt_id,call,log,clock=time.time,feedback_policy="silent_retry"):
        self.attempt_id=attempt_id;self.call=call;self.log=Path(log);self.clock=clock
        self.lock=threading.RLock();self.events=[];self.cache={};self.active=False
        self.terminal=None;self.waiting=False;self.action_id=0;self.t0=None;self.head_initial=None
        self.feedback_policy=feedback_policy;self.delivery=[];self.stop_error=None;self.finished_by_agent=False;self.latest_observation=None
    def record(self,kind,**data):
        row={'kind':kind,'unix':self.clock(),**data}
        with self.log.open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush()
    def start(self):
        with self.lock:
            if self.active or self.terminal:raise ValueError('Attempt cannot restart')
            self.head_initial=self.call('state')['joints']['head_1']['position']
            self.t0=self.clock();self.active=True;self.record('task_started',t0=self.t0)
    def status(self):
        with self.lock:return copy.deepcopy(dict(attempt_id=self.attempt_id,active=self.active,terminal=self.terminal,waiting=self.waiting,action_id=self.action_id,t0=self.t0,events=self.events,stop_error=self.stop_error,feedback_policy=self.feedback_policy))
    def stop(self):
        try:self.call('stop')
        except Exception as e:self.stop_error=str(e);self.record('stop_unconfirmed',error=str(e));raise
    def end(self,outcome,source):
        with self.lock:
            if not self.terminal:
                self.terminal={'outcome':outcome,'source':source,'unix':self.clock()};self.record('terminal',**self.terminal)
            self.waiting=False
            self.stop()
    def operator(self,attempt_id,event_id,outcome,action_id=None,operator_unix=None):
        if outcome not in ('success','failure','uncertain','wrong_button','stop'):raise ValueError('Unknown outcome')
        if not isinstance(event_id,str) or not 1<=len(event_id)<=128:raise ValueError('Invalid event id')
        with self.lock:
            if attempt_id!=self.attempt_id:raise ValueError('Old/wrong attempt')
            previous=next((e for e in self.events if e['event_id']==event_id),None)
            if previous:
                if previous['outcome']!=outcome or previous['action_id']!=action_id:raise ValueError('Event id reused')
                return copy.deepcopy(previous)
            if self.terminal:raise ValueError('Attempt already ended; correction must be an audit note')
            if not self.active and outcome!='stop':raise ValueError('Task not started')
            if outcome in ('failure','uncertain') and (action_id!=self.action_id or (self.feedback_policy=='explicit_wait' and not self.waiting)):raise ValueError('Feedback must match the current waiting action')
            event=dict(event_id=event_id,attempt_id=attempt_id,target_id='initial-opposite-down',outcome=outcome,action_id=action_id,operator_unix=operator_unix,accepted_unix=self.clock(),delivered_unix=None,read_unix=None)
            self.events.append(event);self.record('operator_event',**event)
            if outcome in ('success','wrong_button','stop'):
                # Latch first. Even if stopping fails, all later motion is refused.
                try:self.end('success' if outcome=='success' else 'failure','operator:'+outcome)
                finally:self.delivery.append(event_id)
            else:
                if outcome=='failure':self.waiting=False
                self.delivery.append(event_id)
            return copy.deepcopy(event)
    def delivered(self,event_id):
        with self.lock:
            e=next(e for e in self.events if e['event_id']==event_id)
            e['delivered_unix']=self.clock();self.record('event_delivered',event_id=event_id)
    def pending(self):
        with self.lock:return [copy.deepcopy(e) for e in self.events if e['delivered_unix'] is None]
    def request(self,r):
        op=r.get('op');rid=r.get('id')
        if not isinstance(rid,str) or not 1<=len(rid)<=128:raise ValueError('Request id required')
        canonical=json.dumps(r,sort_keys=True,allow_nan=False)
        # Do not hold the gate lock while waiting for cameras or feedback.
        if op=='observe':
            result=self.call('observe',id=rid)
            folder=self.log.parent/'observations'/uuid.uuid4().hex;folder.mkdir(parents=True)
            for role,encoded in result.get('images',{}).items():
                if role not in ('head','left_wrist','right_wrist'):raise ValueError('Unexpected camera role')
                (folder/(role+'.jpg')).write_bytes(base64.b64decode(encoded,validate=True))
            metadata={k:v for k,v in result.items() if k!='images'}
            (folder/'metadata.json').write_text(json.dumps(metadata))
            self.latest_observation={'folder':str(folder),'unix':self.clock(),'id':folder.name}
            self.record('observation',metadata=metadata,folder=str(folder));return result
        if op=='wait_feedback':
            timeout=r.get('timeout',1.)
            if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not 0<=timeout<=5:raise ValueError('timeout must be 0..5 seconds')
            with self.lock:
                if self.active and not self.terminal:
                    self.stop();self.waiting=self.feedback_policy=='explicit_wait';self.record('waiting_for_result' if self.waiting else 'outcome_check',action_id=self.action_id)
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                with self.lock:
                    if self.terminal or not self.waiting:break
                time.sleep(.03)
            return self.status()
        with self.lock:
            if rid in self.cache:
                prior,result=self.cache[rid]
                if prior!=canonical:raise ValueError('Request id reused')
                return copy.deepcopy(result)
            if op=='events':result=self.status()
            elif op=='ack_events':
                ids=r.get('event_ids')
                if not isinstance(ids,list) or any(not isinstance(x,str) for x in ids):raise ValueError('Invalid event ids')
                if set(ids)-{e['event_id'] for e in self.events}:raise ValueError('Unknown event')
                for e in self.events:
                    if e['event_id'] in ids and e['read_unix'] is None:e['read_unix']=self.clock();self.record('event_read',event_id=e['event_id'])
                result=self.status()
            elif op in ('move','base'):
                if not self.active or self.terminal or self.waiting:raise ValueError('Motion unavailable: inactive, ended or awaiting outcome')
                if op=='move' and 'head_1' in r.get('targets',{}):
                    q=r['targets']['head_1']
                    if not isinstance(q,(float,int)) or not self.head_initial-1.570796326795<=q<=self.head_initial+1.570796326795:raise ValueError('Head pan exceeds initial ±90 degrees')
                result=self.call(op,**{k:v for k,v in r.items() if k!='op'});self.action_id+=1;result={**result,'action_id':self.action_id}
            elif op=='finish':
                outcome=r.get('outcome')
                if outcome not in ('success','failure','contamination'):raise ValueError('Invalid finish')
                if outcome=='success' and (not self.terminal or self.terminal['outcome']!='success'):raise ValueError('Success requires operator confirmation')
                self.end(outcome,'agent');self.finished_by_agent=True;result=self.status()
            elif op in ('schema','state','stop'):
                result=self.call(op,**{k:v for k,v in r.items() if k!='op'})
                if op=='schema':
                    result=copy.deepcopy(result)
                    if self.head_initial is not None:
                        h=result['joints']['head_1'];h['minimum']=max(h['minimum'],self.head_initial-1.570796326795);h['maximum']=min(h['maximum'],self.head_initial+1.570796326795)
                if op=='state':result={**result,'operator':self.status()}
            else:raise ValueError('Unknown public operation')
            self.cache[rid]=(canonical,copy.deepcopy(result));self.record('request',request=r,result=result);return result


class GateServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads=True
    def __init__(self,path,gate):
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(15)
                try:
                    raw=self.rfile.readline(16385)
                    if len(raw)>16384 or not raw.endswith(b'\n'):raise ValueError('Invalid request')
                    request=json.loads(raw)
                    if not isinstance(request,dict):raise ValueError('Expected object')
                    reply={'ok':True,'result':gate.request(request)}
                except Exception as e:reply={'ok':False,'error':str(e)}
                self.wfile.write((json.dumps(reply,allow_nan=False)+'\n').encode())
        super().__init__(str(path),Handler)
        Path(path).chmod(0o600)
        self.worker=threading.Thread(target=self.serve_forever,daemon=True);self.worker.start()
    def close(self):self.shutdown();self.server_close();Path(self.server_address).unlink(missing_ok=True)
