"""Operator-owned attempt lifecycle; no hardware is opened by loading the panel."""
import copy,fcntl,hashlib,json,math,os,shutil,subprocess,sys,threading,time,uuid
from pathlib import Path
from gateway import Gate,GateServer,rpc
from runtime.agent import run_agent
HERE=Path(__file__).resolve().parent
REAL=HERE.parent
sys.path.insert(0,str(REAL/'control_api'))
from machine import paths as machine_paths
from cameras import Cameras
from runtime.workflow import Workflow
PYTHON=sys.executable


def save(path,value):
    tmp=Path(str(path)+'.tmp');tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False));tmp.replace(path)


def prepare_subject(destination):
    destination.mkdir()
    for name in ('robot.py','API.md','PROMPT.md'):shutil.copyfile(HERE/'subject_template'/name,destination/name)
    (destination/'PRIOR.md').write_text('Condition I0E0. No robot model assets or historical experience are supplied. Use only this attempt’s public interface and current observations.\n')
    (destination/'evidence').mkdir()
    return initialize_subject(destination)

def initialize_subject(destination):
    from campaign import hashes
    manifest=hashes(destination)
    subprocess.run(['git','init','-q',str(destination)],check=True)
    (destination/'.gitconfig').write_text('[safe]\n\tdirectory = '+str(destination)+'\n')
    git=['git','-C',str(destination)]
    for k,v in [('user.name','Astra experiment'),('user.email','experiment@localhost')]:subprocess.run(git+['config',k,v],check=True)
    subprocess.run(git+['add','.'],check=True);subprocess.run(git+['commit','-qm','Initialize real attempt'],check=True)
    return manifest


class Controller:
    def __init__(self,root,mode='demo',agent_runner=run_agent):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.lease=(self.root/'owner.lock').open('a');fcntl.flock(self.lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.machine=machine_paths();self.mode=mode;self.runner=agent_runner;self.lock=threading.RLock();self.thread=None;self.gate=None;self.service=None;self.api=None;self.cancel=threading.Event()
        self.resource_lease=None;self.resource_lock=threading.RLock();self.preview_cameras=None;self.camera_lock=threading.Lock();self.workflow=None;self.workflow_path=None
        self.state_file=self.root/'campaign.json'
        self.data=json.loads(self.state_file.read_text()) if self.state_file.exists() else dict(version=1,next_index=1,phase='idle',attempts=[],mode=mode)
        if self.data.get('robot_name',self.machine['name'])!=self.machine['name']:raise ValueError('Use a separate experiment records directory for another robot')
        self.data['robot_name']=self.machine['name']
        if self.data['mode']!=mode:raise ValueError('Demo and real records must use separate directories')
        if self.data['phase'] not in ('idle','paused','ended','error'):
            # Preserve an interrupted attempt; never silently retry it as a fresh sample.
            self.data['phase']='error';self.data['recovery_note']='Previous process stopped mid-attempt. Inspect its records; do not resume the old attempt.'
            if self.data['attempts'] and self.data['attempts'][-1]['status']=='running':self.data['attempts'][-1]['status']='interrupted'
        self.persist()
    def persist(self):save(self.state_file,self.data)
    def snapshot(self):
        with self.lock:
            d=copy.deepcopy(self.data);d['operator']=self.gate.status() if self.gate else None;d['busy']=bool(self.thread and self.thread.is_alive());d['holding']=self.service is not None
            d['observation']=copy.deepcopy(self.gate.latest_observation) if self.gate else None
            d['feed']=[]
            if self.data['attempts']:
                run=self.data['attempts'][-1].get('path')
                if run:
                    private=Path(run)/'private'
                    if self.workflow_path!=private:
                        if self.workflow:self.workflow.close()
                        self.workflow=Workflow(private,private/'agent-workflow.jsonl');self.workflow_path=private
                    d['workflow']=self.workflow.snapshot();d['feed']=d['workflow'].get('entries',[])
            return d
    def acquire_resources(self):
        with self.resource_lock:
            if self.mode!='real' or self.resource_lease:return
            lease=(REAL/('.panel-'+self.machine['name']+'.lock')).open('a')
            try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                lease.close();raise ValueError('另一试跑/正式面板正在占用这台机器人；请先在该面板暂停并断开。')
            self.resource_lease=lease
    def release_resources(self):
        with self.resource_lock:
            if self.resource_lease:self.resource_lease.close();self.resource_lease=None
    def preview_off(self):
        self.close_preview()
        if self.service is None:self.release_resources()
    def preview(self,role):
        if self.mode!='real':raise RuntimeError('Demo has no live camera')
        with self.camera_lock:
            self.acquire_resources()
            if self.api is not None:return rpc(self.api,'preview',role=role)
            if self.preview_cameras is None:
                self.preview_cameras=Cameras(json.loads(self.machine['cameras'].read_text()));self.preview_cameras.start()
            return self.preview_cameras.preview(role)
    def close_preview(self):
        with self.camera_lock:
            if self.preview_cameras:self.preview_cameras.close();self.preview_cameras=None
    def attempt_spec(self,index):return dict(id=f'pilot-{index:03d}',condition='I0E0',purpose='pilot')
    def prepare_inputs(self,destination):return prepare_subject(destination)
    def attempt_finished(self):pass
    def start(self,prepare_only=False):
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('An attempt is already active')
            if self.service is not None:raise ValueError('Release previous session before starting')
            self.acquire_resources()
            self.begin_event=threading.Event();self.prepare_only=prepare_only;self.cancel.clear();index=self.data['next_index'];spec=self.attempt_spec(index);name=spec['id'];run=self.root/name;run.mkdir()
            private=run/'private';private.mkdir();manifest=self.prepare_inputs(run/'subject');save(private/'input-manifest.json',manifest)
            sources=[*HERE.glob('*.py'),* (HERE/'runtime').glob('*.py'),* (REAL/'control_api').glob('*.py'),self.machine['cameras'],self.machine['calibration'],self.machine['pose']]
            save(private/'runtime-manifest.json',{(str(p.relative_to(REAL)) if p.is_relative_to(REAL) else str(p)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
            self.data['next_index']+=1;self.data['phase']='preparing';self.data['attempts'].append(dict(**spec,status='running',path=str(run),created_unix=time.time(),target_id='initial-opposite-down'))
            self.persist();self.thread=threading.Thread(target=self._attempt,args=(run,),daemon=True);self.thread.start();return name
    def begin(self):
        with self.lock:
            if self.data['phase']!='ready' or self.cancel.is_set():raise ValueError('Initial pose is not ready')
            self.begin_event.set()

    def _attempt(self,run):
        private=run/'private';gate_server=None;self.gate=None
        try:
            if self.mode=='real':
                for seconds in range(5,0,-1):
                    with self.lock:self.data['countdown']=seconds;self.persist()
                    if self.cancel.wait(1):raise RuntimeError('Preparation stopped')
                with self.lock:self.data['countdown']=None;self.persist()
            runtime=Path('/tmp')/('real-'+uuid.uuid4().hex[:12]);runtime.mkdir(mode=0o700)
            with self.camera_lock:
                self.api=runtime/'motor.sock'
                if self.preview_cameras:self.preview_cameras.close();self.preview_cameras=None
            command=[PYTHON,str(REAL/'control_api/supervised.py'),'--arm','--enable-base','--socket',str(self.api)]
            if self.mode=='demo':command.append('--demo')
            else:command.extend(['--recording-dir',str(private/'video')])
            self.service_env=dict(os.environ)
            if getattr(self,'profile_dir',None) or os.environ.get('ASTRA_ROBOT_PROFILE'):
                frozen=private/'robot-profile';frozen.mkdir();(frozen/'calibration').mkdir()
                profile_dir=Path(getattr(self,'profile_dir',None) or os.environ['ASTRA_ROBOT_PROFILE'])
                shutil.copy2(profile_dir/'profile.json',frozen/'profile.json')
                for source,dest in [(self.machine['calibration'],frozen/'calibration/calibration.json'),(self.machine['cameras'],frozen/'camera-config.json'),(self.machine['pose'],frozen/'task-pose.json')]:shutil.copy2(source,dest)
                self.active_pose=frozen/'task-pose.json';self.service_env['ASTRA_ROBOT_PROFILE']=str(frozen)
            with (private/'service.log').open('w') as log:self.service=subprocess.Popen(command,stdout=log,stderr=log,start_new_session=True,env=self.service_env)
            save(private/'process.json',dict(supervisor_pid=self.service.pid,socket=str(self.api)))
            for _ in range(150):
                if self.service.poll() is not None:raise RuntimeError('Motor service failed to start; inspect service.log')
                if self.cancel.is_set():raise RuntimeError('Preparation stopped')
                try:rpc(self.api,'state');break
                except (OSError,RuntimeError):time.sleep(.1)
            else:raise TimeoutError('Motor startup timed out')
            self.gate=Gate(run.name,lambda op,**kw:rpc(self.api,op,**kw),private/'operator-events.jsonl',feedback_policy='silent_retry')
            if self.mode=='real':
                for _ in range(100):
                    recording=rpc(self.api,'recording_status')
                    if recording.get('error'):raise RuntimeError('Recording unavailable: '+recording['error'])
                    if all(recording.get('frames',{}).get(role,0)>0 for role in ('head','left_wrist','right_wrist')):break
                    if self.cancel.wait(.1):raise RuntimeError('Preparation stopped')
                else:raise RuntimeError('Three-view recording startup timed out')
            self._prepare_pose(private)
            if self.cancel.is_set():raise RuntimeError('Preparation stopped')
            save(private/'pose-ready.json',dict(unix=time.time(),state=rpc(self.api,'state'),criterion='timed coordinated preparation; no tracking-error or temperature gate'))
            if self.prepare_only:
                with self.lock:self.data['phase']='ready';self.persist()
                while not self.begin_event.wait(.05):
                    if self.cancel.is_set():raise RuntimeError('Preparation stopped')
                if self.cancel.is_set():raise RuntimeError('Preparation stopped')
            gate_server=GateServer(runtime/'subject.sock',self.gate)
            with self.lock:self.data['phase']='running';self.persist()
            if self.mode=='demo':self._demo_agent()
            else:self.runner(run/'subject',runtime/'subject.sock',private,self.gate,max_seconds=1800.,reasoning='xhigh')
            if not self.gate.terminal:self.gate.end('failure','agent_returned')
            with self.lock:
                row=self.data['attempts'][-1];row.update(status='completed',result=self.gate.status(),end_unix=time.time());self.data['phase']='ended';self.persist()
        except BaseException as e:
            if self.gate:
                try:self.gate.end('failure','infrastructure_error')
                except Exception:pass
            with self.lock:
                self.data['phase']='error';self.data['attempts'][-1].update(status='error',error=str(e),end_unix=time.time(),result=self.gate.status() if self.gate else None);self.persist()
        finally:
            if gate_server:gate_server.close()
            # Hold arms after a run. Release is a separate, explicit operator action.
            if self.api:
                try:rpc(self.api,'stop')
                except Exception:pass
            if self.mode=='real' and self.api:
                try:save(private/'recording-result.json',rpc(self.api,'recording_stop'))
                except Exception as e:save(private/'recording-result.json',dict(error=str(e)))
            if self.gate:save(private/'result.json',self.gate.status())
            if self.api and self.api.parent.exists():
                for f in self.api.parent.glob('api-*.jsonl'):shutil.copyfile(f,private/f.name)
            self.attempt_finished()
    def _prepare_pose(self,private):
        if self.mode=='demo':time.sleep(.1);return
        state=rpc(self.api,'state');schema=rpc(self.api,'schema');targets=json.loads(getattr(self,'active_pose',self.machine['pose']).read_text())['targets'];end={n:v['q_commanded_rad'] for n,v in targets.items()};end.update(head_1=math.pi,head_2=0.0);start={n:state['joints'][n]['target'] for n in end}
        for n,q in end.items():
            if not schema['joints'][n]['minimum']<=q<=schema['joints'][n]['maximum']:raise ValueError('Initial pose outside current interface limits: '+n)
        # Segment long preparation without violating the public 10-second limit.
        count=max(1,max(math.ceil(abs(end[n]-start[n])/(schema['joints'][n]['max_target_speed']*4)) for n in end))
        last=start
        for i in range(1,count+1):
            if self.cancel.is_set():raise RuntimeError('Preparation stopped')
            target={n:max(schema['joints'][n]['minimum'],min(schema['joints'][n]['maximum'],start[n]+(end[n]-start[n])*i/count)) for n in end}
            duration=max(1.,max(max(1.5*abs(target[n]-last[n])/schema['joints'][n]['max_target_speed'],math.sqrt(6*abs(target[n]-last[n])/schema['joints'][n]['max_target_acceleration'])) for n in end))+.1
            rpc(self.api,'move',targets=target,duration=duration)
            deadline=time.monotonic()+duration+.1
            while time.monotonic()<deadline:
                if self.cancel.wait(.05):rpc(self.api,'stop');raise RuntimeError('Preparation stopped')
            if rpc(self.api,'state')['fault']:raise RuntimeError('Motor communication/enable fault')
            last=target
    def _demo_agent(self):
        self.gate.start()
        while not self.cancel.wait(.05):
            for event in self.gate.pending():
                self.gate.delivered(event['event_id']);self.gate.request(dict(op='ack_events',id=uuid.uuid4().hex,event_ids=[event['event_id']]))
            if self.gate.terminal:return
    def outcome(self,**fields):
        if not self.gate:raise ValueError('No active attempt')
        return self.gate.operator(**fields)
    def stop(self):
        self.cancel.set()
        if self.gate and not self.gate.terminal:
            self.gate.operator(self.gate.attempt_id,uuid.uuid4().hex,'stop')
        elif self.api:rpc(self.api,'stop')
    def release(self):
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('Stop and wait for the attempt to close before releasing')
            if self.service:
                self.service.terminate();self.service.wait(timeout=8);self.service=None
            if self.mode=='real':
                self.acquire_resources()
                env=getattr(self,'service_env',dict(os.environ))
                if getattr(self,'profile_dir',None):env={**env,'ASTRA_ROBOT_PROFILE':str(self.profile_dir)}
                result=subprocess.run([PYTHON,str(REAL/'control_api/manage.py'),'release'],capture_output=True,text=True,timeout=20,env=env)
                if result.returncode:raise RuntimeError('Release not confirmed: '+result.stderr)
                self.data['release_evidence']=result.stdout
            self.api=None;self.data['released_unix']=time.time();self.persist()
    def pause(self):
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('请在完整一轮结束后暂停')
            if self.service:
                self.service.terminate();self.service.wait(timeout=8);self.service=None;self.api=None
            self.close_preview();self.release_resources();self.data['phase']='paused';self.persist()
    def note(self,text):
        if not isinstance(text,str) or not text.strip() or len(text)>2000:raise ValueError('Invalid audit note')
        with (self.root/'operator-notes.jsonl').open('a') as f:f.write(json.dumps(dict(unix=time.time(),text=text,attempt_id=self.data['attempts'][-1]['id'] if self.data['attempts'] else None),ensure_ascii=False)+'\n')
    def close(self):
        if self.thread and self.thread.is_alive():self.stop();self.thread.join(timeout=65)
        if (not self.thread or not self.thread.is_alive()) and self.service:
            self.service.terminate();self.service.wait(timeout=8);self.service=None
            self.api=None
        # Server shutdown preserves torque; release remains an explicit action.
        self.close_preview()
        if self.workflow:self.workflow.close()
        self.release_resources()
        self.lease.close()
