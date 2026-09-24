"""Named calibration workflow, explicit writes and bounded active tests."""
import sys,os,json,time,math,uuid,threading,subprocess,base64,shutil
from pathlib import Path
from registry import Registry,ROOT,read,write,digest,control_digest
from snapshots import capture,seal
sys.path.insert(0,str(ROOT/'control_api'))
from transport import Transport,FakeTransport
from engine import Engine
from profiles import joint_profile,base_raw_acceleration

def camera_port_label(path):
 import re
 path=Path(path);match=re.search(r'usb-\d+:([^:]+):',path.name)
 return 'USB '+(match.group(1) if match else path.name)+' · '+path.resolve().name

def rpc(path,op,**kw):
 import socket
 with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
  s.settimeout(12);s.connect(str(path));s.sendall((json.dumps(dict(op=op,id=uuid.uuid4().hex,**kw))+'\n').encode())
  with s.makefile('rb') as f:d=json.loads(f.readline(8*1024*1024))
 if not d['ok']:raise RuntimeError(d['error'])
 return d['result']

class Workflow:
 def __init__(self,registry,controller_factory):
  self.registry=registry;self.factory=controller_factory;self.name=None;self.controller=None;self.job=None;self.thread=None;self.process=None;self.socket=None;self.cancel=threading.Event();self.cameras={};self.service_kind=None;self.command_lock=threading.RLock()
 def load(self,name):
  if self.thread and self.thread.is_alive():raise ValueError('请先停止并等候当前任务结束')
  if self.process:raise ValueError('请先停止主动测试连接（不释放torque）再切换机器')
  p=self.registry.path(name);meta=read(p/'profile.json')
  if not meta or meta['demo']!=self.registry.demo:raise ValueError('工作区模式不匹配')
  if self.controller:
   with self.controller.lock:self.controller.running=False;self.controller.disconnect()
  self.name=name;self.controller=self.factory(p/'calibration',self.registry.demo,backup=meta.get('initial_backup'),on_save=lambda:self.registry.checkpoint(name,'calibration edit'));self.controller.start_loop();return self.controller
 def state(self):return dict(names=self.registry.names(),selected=self.name,profile=self.registry.status(self.name) if self.name else None,job=self.job,holding_connection=self.process is not None,serials=sorted(p.name for p in Path('/dev/serial/by-id').glob('*')),camera_devices=sorted(str(p) for p in Path('/dev/v4l/by-path').glob('*video-index0')),camera_labels={str(p):camera_port_label(p) for p in Path('/dev/v4l/by-path').glob('*video-index0')},serial_labels={p.name:p.resolve().name+' · '+p.name.split('_')[-1].split('-')[0] for p in Path('/dev/serial/by-id').glob('*')})
 def path(self):
  if not self.name:raise ValueError('先新建或加载机器配置')
  return self.registry.path(self.name)
 def require_idle(self):
  if self.thread and self.thread.is_alive():raise ValueError('任务执行中，请等待或停止')
 def run(self,kind,fn):
  self.require_idle();self.cancel.clear();self.job=dict(kind=kind,status='running',robot=self.name,started=time.time(),message='进行中')
  if self.controller and self.controller.connected:self.controller.disconnect()
  def worker():
   try:
    result=fn();self.job.update(status='completed',result=result,message='完成；没有自动恢复参数或释放torque')
   except Exception as e:
    self.job.update(status='error',error=str(e),message=str(e))
    if self.socket:
     try:rpc(self.socket,'stop')
     except Exception:pass
   finally:
    self.job['ended']=time.time();write(self.path()/'jobs'/(str(int(self.job['started']*1000))+'-'+kind+'.json'),self.job)
  self.thread=threading.Thread(target=worker,daemon=True);self.thread.start()
 def close_service(self):
  if self.process:
   process=self.process
   try:
    if process.poll() is None:rpc(self.socket,'stop')
   finally:
    if process.poll() is None:process.terminate();process.wait(timeout=8)
    if self.socket:
     for source in Path(self.socket).parent.glob('api-*.jsonl'):
      destination=self.path()/'service-logs'/Path(self.socket).parent.name/source.name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
    self.process=None;self.socket=None
 def stop(self):
  self.cancel.set()
  with self.command_lock:
   if self.socket:rpc(self.socket,'stop')
 def motion(self,op,**fields):
  with self.command_lock:
   if self.cancel.is_set():raise RuntimeError('已停止，拒绝后续运动')
   return rpc(self.socket,op,**fields)
 def hardware(self):
  meta=read(self.path()/'profile.json')
  if not meta.get('initial_backup'):raise ValueError('先建立初始备份')
  return Transport(Path(meta['initial_backup']),lambda e:self.controller.audit(e))
 def backup(self,kind,serials):
  self.close_service();p=self.path();meta=read(p/'profile.json')
  if self.registry.demo:raise ValueError('演示模式不创建实机寄存器备份')
  initial=meta.get('initial_backup')
  if kind=='initial' and initial:raise ValueError('初始备份已存在；请使用修改前快照，不能覆盖')
  if kind=='ready':
   status=self.registry.status(self.name)
   if not all(v['valid'] for v in status['validation'].values()):raise ValueError('请完成当前配置的关节、底盘和相机验收')
   if not (p/'parameters.json').exists():raise ValueError('先生成并应用运行参数')
  folder=p/'backups'/(time.strftime('%Y%m%d-%H%M%S')+'-'+kind+'-'+uuid.uuid4().hex[:4])
  expected=read(Path(initial)/'REPORT.json') if initial else None
  chosen=sorted({m['usb_serial_path'] for m in expected['motors']}) if expected else serials
  if not chosen:raise ValueError('请选择要绑定的串口')
  capture(folder,self.name,chosen,expected)
  if kind=='ready':
   plan=read(p/'parameters.json');report=read(folder/'REPORT.json')
   for m in report['motors']:
    key=m['usb_serial_path']+':'+str(m['id']);v=read(folder/m['folder']/'pass-1.json');expected_p=plan['motors'][key]
    if v[41]!=expected_p['acceleration'] or v[46]+256*v[47]!=expected_p['speed']:raise ValueError('当前运行参数与计划不一致；快照保留但不能标成ready')
   for name in ('profile.json','camera-config.json','parameters.json','validation.json','task-pose.json'):
    if (p/name).exists():shutil.copy2(p/name,folder/name)
   shutil.copy2(p/'calibration/calibration.json',folder/'calibration.json')
   for sub in ('test-results','parameter-writes','service-logs','calibration/camera-import'):
    if (p/sub).exists():shutil.copytree(p/sub,folder/'evidence'/sub)
   for f in (p/'calibration').glob('capture-*.json'):
    out=folder/'evidence/calibration'/f.name;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,out)
  package=seal(folder)
  external=Path('/home/sida/Documents/robot-register-backups')/self.name;external.mkdir(parents=True,exist_ok=True);target=external/(self.name+'-'+Path(package['archive']).name);shutil.copy2(package['archive'],target)
  import hashlib
  if hashlib.sha256(target.read_bytes()).hexdigest()!=package['sha256']:raise RuntimeError('项目外副本校验失败')
  package['external_copy']=str(target);self.registry.checkpoint(self.name,'backup '+kind);meta=read(p/'profile.json')
  if kind=='initial':meta['initial_backup']=str(folder);self.controller.backup=folder
  meta['latest_'+kind]=package;write(p/'profile.json',meta);return package
 def generate(self):
  p=self.path();cal=read(p/'calibration/calibration.json');meta=read(p/'profile.json')
  if not self.controller.summary()['passive_complete']:raise ValueError('请先完成关节及底盘被动标定')
  if not meta.get('initial_backup'):raise ValueError('先保存初始备份')
  backup=Path(meta['initial_backup']);report=read(backup/'REPORT.json');known={m['usb_serial_path']+':'+str(m['id']):m for m in report['motors']}
  fake=FakeTransport(cal);plan={}
  reviewed=ROOT/'register-backups/20260922-094516-before-calibration';reviewed_report=read(reviewed/'REPORT.json');unit_reference={}
  for m in reviewed_report['motors']:
   unit_reference.setdefault(m['model_candidates'][0].lower(),read(reviewed/m['folder']/'pass-1.json'))
  for m in known.values():
   values=read(backup/m['folder']/'pass-1.json');reference=unit_reference.get(m['model_candidates'][0].lower())
   if reference is None or any(values[a]!=reference[a] for a in (0,1,2,80,82,86)):raise ValueError('固件或速度/加速度单位配置不同，需要核对换算后再写参数')
  for key,m in known.items():
   if key not in fake.motors:raise ValueError('标定映射与备份电机不一致')
   fake.motors[key]['original']=read(backup/m['folder']/'pass-1.json')
  for n,j in cal['joints'].items():
   key=j['motor'];m=known[key]
   if m['model_candidates'][0].lower()!='sts3215':raise ValueError('关节型号需要单独核对')
   v=joint_profile(n);plan[key]=dict(role=n,acceleration=v['raw_acceleration'],speed=v['raw_velocity'],time=0)
  for n,w in cal['wheels'].items():
   key=w['motor']
   if known[key]['model_candidates'][0].lower()!='sts3250':raise ValueError('轮电机型号需要单独核对')
   plan[key]=dict(role=n,acceleration=base_raw_acceleration(cal),speed=0)
  if len(plan)!=18:raise ValueError('电机映射重复或缺失')
  engine=Engine(cal,fake);template=read(ROOT/'control/elevator-task-initial-pose.json');targets={}
  for n,t in template['targets'].items():
   lo,hi=sorted(engine.q(n,c) for c in engine.bounds[n]);q=lo if t['xml_q_requested']=='jaw_min' else t['xml_q_requested']
   if not lo<=q<=hi:raise ValueError('任务初态超出该机器人范围：'+n)
   j=cal['joints'][n];ref=j['reference'];count=round(ref['continuous']+(q-ref['reference_q'])*4096/(j['sign']*2*math.pi));targets[n]=dict(motor=j['motor'],count=count,xml_q_requested=t['xml_q_requested'],q_commanded_rad=engine.q(n,count))
  data=dict(robot_name=self.name,calibration_hash=control_digest(cal),motors=plan,units='Acceleration:100 counts/s²; speed:counts/s; validated model family STS3215/STS3250',software_ranges=engine.schema()['joints'])
  self.registry.checkpoint(self.name,'generate runtime parameters and pose');write(p/'parameters.json',data);write(p/'task-pose.json',dict(name='elevator-task-initial-pose',robot_name=self.name,targets=targets));return data
 def parameters(self,restore=False,preview=False):
  self.close_service();p=self.path();plan=read(p/'parameters.json')
  if not restore and (not plan or plan['calibration_hash']!=control_digest(self.controller.data)):raise ValueError('先重新生成参数预览')
  h=self.hardware()
  try:
   live=h.connect();before={k:h.read(k,40,16) for k in h.motors}
   if preview:return {k:dict(current_acceleration=v[1],current_speed=v[6]+256*v[7],proposed=plan['motors'][k]) for k,v in before.items()}
   if restore and any(v['torque'] for v in live.values()):raise ValueError('人工恢复前请先单独释放torque')
   if restore:
    acc={k:m['original'][41] for k,m in h.motors.items()};speeds={k:int.from_bytes(bytes(m['original'][46:48]),'little') for k,m in h.motors.items()}
    wheelkeys=[k for k,m in h.motors.items() if m['model'].lower()=='sts3250']
    if any(speeds[k]!=0 for k in wheelkeys):raise ValueError('不恢复非零轮速')
   else:
    acc={k:v['acceleration'] for k,v in plan['motors'].items()};speeds={k:v['speed'] for k,v in plan['motors'].items()}
   write(p/'parameter-writes'/(str(time.time_ns())+'-before.json'),dict(before=before,restore_requested=restore))
   h.sync(41,1,acc,True)
   try:
    h.sync(46,2,speeds,True)
    if not restore:h.sync(44,2,{j['motor']:0 for j in self.controller.data['joints'].values()},True)
   finally:
    # Preserve the starting torque state; zero wheel speed can auto-enable firmware.
    h.sync(40,1,{k:v['torque'] for k,v in live.items()},True)
   after={k:h.read(k,40,16) for k in h.motors};h.check_configs();evidence=dict(before=before,after=after,restored=restore,torque_preserved=True);write(p/'parameter-writes'/(str(time.time_ns())+'.json'),evidence)
   meta=read(p/'profile.json');meta['parameters_applied_hash']=None if restore else digest(plan);write(p/'profile.json',meta);return evidence
  finally:h.close()
 def release(self):
  self.close_service();h=self.hardware()
  try:
   h.connect();wheels=[k for k,m in h.motors.items() if m['model'].lower()=='sts3250']
   if wheels:h.sync(46,2,{k:0 for k in wheels},True)
   h.sync(40,1,{k:0 for k in h.motors},True);return {'all_torque_released':True}
  finally:h.close()
 def service(self,base=False):
  kind='base' if base else 'arms'
  if self.process and self.service_kind==kind:
   if self.service_fingerprint!=control_digest(self.controller.data):raise ValueError('配置已修改，请先结束测试连接')
   return
  self.close_service();meta=read(self.path()/'profile.json');plan=read(self.path()/'parameters.json')
  if not plan or plan['calibration_hash']!=control_digest(self.controller.data) or meta.get('parameters_applied_hash')!=digest(plan):raise ValueError('先生成并应用当前标定的参数')
  folder=Path('/tmp')/('calib-test-'+uuid.uuid4().hex[:12]);folder.mkdir();self.socket=folder/'motor.sock'
  frozen=folder/'profile';frozen.mkdir()
  for name in ('profile.json','camera-config.json','task-pose.json','parameters.json'):shutil.copy2(self.path()/name,frozen/name)
  (frozen/'calibration').mkdir();shutil.copy2(self.path()/'calibration/calibration.json',frozen/'calibration/calibration.json')
  env={**os.environ,'ASTRA_ROBOT_PROFILE':str(frozen)};cmd=[sys.executable,str(ROOT/'control_api/supervised.py'),'--arm','--socket',str(self.socket)]
  if base:cmd+=['--enable-base','--base-only']
  log=(self.path()/'active-service.log').open('a');self.process=subprocess.Popen(cmd,env=env,stdout=log,stderr=log);log.close();self.service_kind=kind;self.service_fingerprint=control_digest(self.controller.data)
  for _ in range(100):
   if self.cancel.is_set():raise RuntimeError('已停止')
   if self.process.poll() is not None:raise RuntimeError('控制服务启动失败，见日志')
   try:rpc(self.socket,'state');return
   except OSError:time.sleep(.1)
  raise RuntimeError('控制服务启动超时')
 def test(self,kind):
  for remaining in range(5,0,-1):
   self.job['message']=f'{remaining}秒后开始，请留出运动空间'
   if self.cancel.wait(1):raise RuntimeError('已取消')
  with self.command_lock:
   if self.cancel.is_set():raise RuntimeError('已取消')
   self.service(base=kind=='base')
  if kind=='base':
   for direction,vec in [('前进',[.02,0,0]),('后退',[-.02,0,0]),('左移',[0,.02,0]),('右移',[0,-.02,0]),('左转',[0,0,math.pi/60]),('右转',[0,0,-math.pi/60])]:
    self.job['message']=direction+' · 2.5秒，保持低速';end=time.monotonic()+2.5
    while time.monotonic()<end:
     if self.cancel.is_set():raise RuntimeError('已停止')
     self.motion('base',vx=vec[0],vy=vec[1],wz=vec[2],duration=min(.6,max(.01,end-time.monotonic())));self.cancel.wait(.3)
    if self.cancel.wait(1):raise RuntimeError('已停止')
   self.motion('base',vx=.01,vy=0,wz=0,duration=.5);self.cancel.wait(.15);rpc(self.socket,'stop')
  else:
   state=rpc(self.socket,'state');schema=rpc(self.socket,'schema')['joints']
   end={n:t['q_commanded_rad'] for n,t in read(self.path()/'task-pose.json')['targets'].items()} if kind=='home' else {n:max(s['minimum'],min(s['maximum'],math.pi if n=='head_1' else 0.)) for n,s in schema.items()}
   start={n:state['joints'][n]['target'] for n in end};count=max(1,max(math.ceil(abs(end[n]-start[n])/(schema[n]['max_target_speed']*4)) for n in end));last=start
   for i in range(1,count+1):
    if self.cancel.is_set():raise RuntimeError('已停止')
    goal={n:max(schema[n]['minimum'],min(schema[n]['maximum'],start[n]+(end[n]-start[n])*i/count)) for n in end};duration=max(1.,max(max(1.5*abs(goal[n]-last[n])/schema[n]['max_target_speed'],math.sqrt(6*abs(goal[n]-last[n])/schema[n]['max_target_acceleration'])) for n in end))+.1
    self.motion('move',targets=goal,duration=duration)
    if self.cancel.wait(duration+.1):raise RuntimeError('已停止')
    last=goal
  rpc(self.socket,'stop');sample=rpc(self.socket,'state');write(self.path()/'test-results'/(str(time.time_ns())+'-'+kind+'.json'),dict(sample=sample,fingerprint=self.registry.fingerprint(self.name,'base' if kind=='base' else 'joints')))
  return dict(test=kind,operator_confirmation_required=True,torque='retained; release manually only')
 def camera_capture(self):
  self.close_service()
  if self.registry.demo:raise ValueError('离线模式不读取真实相机')
  import cv2
  devices=sorted(str(p) for p in Path('/dev/v4l/by-path').glob('*video-index0'));result={};folder=self.path()/'camera-preview';folder.mkdir(exist_ok=True)
  for index,path in enumerate(devices):
   cap=cv2.VideoCapture(path,cv2.CAP_V4L2)
   try:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,640);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
    for _ in range(3):ok,frame=cap.read()
    if ok:
     name=str(index)+'.jpg';cv2.imwrite(str(folder/name),frame);result[str(index)]=dict(device=path,url='/api/machine/image/'+str(index),captured=time.time())
   finally:cap.release()
  self.cameras=result;return result
 def action(self,op,data):
  if op=='stop':self.stop();return
  if data.get('_robot',self.name)!=self.name:raise ValueError('选中的机器人已变化，请刷新页面')
  if '_revision' in data and data['_revision']!=read(self.path()/'profile.json')['revision']:raise ValueError('配置版本已变化，请刷新后重试')
  if op=='load':return self.load(data['name'])
  self.require_idle()
  if op=='create':self.registry.create(data['name']);return self.load(data['name'])
  p=self.path()
  if op=='disconnect_active':self.close_service();return
  if op=='generate':
   if self.process:raise ValueError('先结束主动测试连接再生成新参数')
   return self.generate()
  if op=='save_cameras':
   if self.process:raise ValueError('先结束主动测试连接，再修改相机配置')
   devices=data['devices']
   if set(devices)!={'head','left_wrist','right_wrist'} or len(set(devices.values()))!=3:raise ValueError('请选择三个不同的相机')
   allowed={str(x) for x in Path('/dev/v4l/by-path').glob('*video-index0')}|set(read(p/'camera-config.json',{}).get('devices',{}).values())
   if not self.registry.demo and any(v not in allowed for v in devices.values()):raise ValueError('相机路径不在已发现设备中')
   self.registry.checkpoint(self.name,'camera roles changed');write(p/'camera-config.json',dict(roles_confirmed=True,devices=devices,parameter_source='simulation_reference',parameters=read(ROOT/'calibration/review/simulation-camera-reference.json')));return
  if op=='accept':
   section=data['section']
   if section not in ('camera','joints','base'):raise ValueError('无效验收模块')
   if section=='camera' and not read(p/'camera-config.json',{}).get('roles_confirmed'):raise ValueError('先保存相机对应关系')
   if section!='camera':
    kinds=['home','zero'] if section=='joints' else ['base']
    if not all(any(read(f).get('fingerprint')==self.registry.fingerprint(self.name,section) for f in (p/'test-results').glob('*-'+kind+'.json')) for kind in kinds):raise ValueError('先用当前配置执行相关测试，再确认现场表现')
   self.registry.accept(self.name,section,str(data.get('note','现场确认正常')));return
  if self.registry.demo and op not in ('camera_capture',):raise ValueError('此操作需要实机模式；离线模式不会访问或驱动硬件')
  if op in ('initial','snapshot','ready'):self.run(op,lambda:self.backup(op,data.get('serials',[])))
  elif op=='preview':self.run(op,lambda:self.parameters(False,True))
  elif op=='apply':self.run(op,lambda:self.parameters(False))
  elif op=='restore':self.run(op,lambda:self.parameters(True))
  elif op=='release_all':self.run(op,self.release)
  elif op in ('zero','home','base'):self.run(op,lambda:self.test(op))
  elif op=='camera_capture':self.run(op,self.camera_capture)
  else:raise ValueError('未知工作流操作')
