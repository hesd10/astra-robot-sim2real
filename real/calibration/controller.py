from pathlib import Path
from collections import deque
from datetime import datetime, timezone
import copy, json, os, math, time, threading, uuid, hashlib
from domain import *
from hardware import Hardware
from grouped import GroupedCalibration, GROUPS

ROOT=Path(__file__).resolve().parent
BACKUP=ROOT.parent/'register-backups/20260922-094516-before-calibration'

def atomic_json(path, data):
    tmp=path.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(data,f,ensure_ascii=False,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

class Controller(GroupedCalibration):
    def __init__(self, workspace, demo=False, driver_factory=None, backup=None, on_save=None):
        self.ws=Path(workspace); self.ws.mkdir(parents=True,exist_ok=True)
        self.backup=Path(backup) if backup else BACKUP;self.on_save=on_save
        self.demo=demo; self.lock=threading.RLock(); self.hw=None
        self.driver_factory=driver_factory or (DemoHardware if demo else Hardware)
        p=self.ws/'calibration.json'
        self.data=json.loads(p.read_text()) if p.exists() else dict(version=1,mounting='reverse',joints={},wheels={},base={},camera={'status':'not_imported'})
        self.live={}; self.history={}; self.capture=None;self.result=None;self.error=None
        self.connected=False;self.epoch=None;self.last_tick=0;self.last_config=0
        self.running=True;self.thread=None
    def audit(self,event):
        event=dict(event,utc=datetime.now(timezone.utc).isoformat())
        with (self.ws/'events.jsonl').open('a') as f:
            f.write(json.dumps(event,ensure_ascii=False,allow_nan=False)+'\n');f.flush();os.fsync(f.fileno())
    def save(self):
        if self.on_save:self.on_save()
        atomic_json(self.ws/'calibration.json',self.data)
    def invalidate_base(self): self.data['base'].pop('solution',None)
    def connect(self):
        if self.connected:return
        self.hw=self.driver_factory(self.backup,self.audit)
        try:
            samples=self.hw.connect()
            self.epoch=str(uuid.uuid4());self.live={};self.history={};self.error=None
            self.connected=True;self.capture=None;self.result=None
            self.ingest(samples);self.last_config=time.monotonic()
            self.audit(dict(kind='connected_read_only',epoch=self.epoch,demo=self.demo))
        except Exception:
            self.hw.close();self.hw=None;raise
    def disconnect(self):
        if self.capture:self.audit(dict(kind='capture_aborted_disconnect',capture=self.capture['kind']))
        self.capture=None;self.result=None
        if self.hw:self.hw.close()
        self.hw=None;self.connected=False
        self.audit(dict(kind='disconnected_no_torque_change'))
    def ingest(self,samples):
        now=time.monotonic()
        if self.last_tick and self.connected and now-self.last_tick>1.5 and self.live:
            raise RuntimeError('采集间隔过长，连续角度可能丢失，请重新连接并重录当前参考姿态')
        for key,v in samples.items():
            old=self.live.get(key);count=v['present']
            if old:
                delta=unwrap_delta(v['present'],old['present'])
                if abs(delta)>900: raise RuntimeError('读数跳变过大，请缓慢手动移动并重新连接')
                count=old['continuous']+delta
            item=dict(v,continuous=count)
            self.live[key]=item
            h=self.history.setdefault(key,deque(maxlen=60));h.append((now,count))
        self.last_tick=now
        if self.capture:
            c=self.capture
            if now-c['started_mono']>(600 if c['kind']=='group_range' else 180):
                raise RuntimeError('单次采集超时（整组范围十分钟，其他三分钟），请结束后重新采集')
            row={}
            for key,stat in c['stats'].items():
                v=self.live[key]
                if v['torque']!=0:raise RuntimeError('采集期间发现所选电机未释放扭矩，已取消采集')
                count=v['continuous'];stat['low']=min(stat['low'],count);stat['high']=max(stat['high'],count)
                stat['travel']+=abs(count-stat['end']);stat['end']=count;row[key]=count
            c['samples'].append(dict(t=round(now-c['started_mono'],4),counts=row))
    def start_loop(self):
        def loop():
            while self.running:
                with self.lock:
                    if self.connected:
                        try:
                            if time.monotonic()-self.last_config>5:
                                self.hw.check_configs();self.last_config=time.monotonic()
                            self.ingest(self.hw.sample())
                        except Exception as e:
                            self.error=str(e);self.audit(dict(kind='sampling_fault',error=str(e)))
                            self.disconnect()
                time.sleep(.075)
        self.thread=threading.Thread(target=loop,daemon=True);self.thread.start()
    def fresh(self):
        if not self.connected or time.monotonic()-self.last_tick>1:raise ValueError('请先连接设备，等待新鲜读数')
    def meta(self):
        return {k:{n:v for n,v in m.items() if n!='original'} for k,m in (self.hw.motors.items() if self.hw else [])}
    def get_target(self,target):
        if target in JOINTS:return self.data['joints'].get(target)
        if target in WHEELS:return self.data['wheels'].get(target)
        raise ValueError('未知关节或轮子')
    def mapped_keys(self):return [v['motor'] for group in ['joints','wheels'] for v in self.data[group].values() if 'motor' in v]
    def select_keys(self,kind,target):
        if kind.startswith('group_'):return self.group_keys(kind,target)
        if kind=='mapping':
            if target not in JOINTS and target not in WHEELS:raise ValueError('目标无效')
            model='sts3250' if target in WHEELS else 'sts3215'
            # Known device inventory; expected model class avoids confusing a wheel with an arm.
            return [k for k,m in self.hw.motors.items() if m['model']==model and k not in self.mapped_keys() and self.live[k]['torque']==0]
        if kind=='base':
            if target not in DIRECTIONS:raise ValueError('方向无效')
            if any(w not in self.data['wheels'] for w in WHEELS):raise ValueError('先完成四个轮子的对应识别')
            return [self.data['wheels'][w]['motor'] for w in WHEELS]
        if kind in ['positive','range']:
            if target not in JOINTS:raise ValueError('请选择关节')
            j=self.get_target(target)
            if not j or 'reference' not in j:raise ValueError('先识别电机并记录参考姿态')
            if j['reference']['epoch']!=self.epoch:raise ValueError('连接已变化，请重新记录该关节参考姿态')
            if kind=='range' and 'sign' not in j:raise ValueError('先确认正方向')
            return [j['motor']]
        raise ValueError('未知采集类型')
    def start_capture(self,kind,target):
        self.fresh()
        if self.capture:raise ValueError('先完成或取消正在进行的采集')
        keys=self.select_keys(kind,target)
        if not keys:raise ValueError('没有可用的未分配电机')
        if any(self.live[k]['torque']!=0 for k in keys):raise ValueError('请先在连接页释放待采集电机的扭矩，并托住相关部件')
        self.hw.check_configs()
        self.result=None
        self.capture=dict(id=str(uuid.uuid4()),kind=kind,target=target,started_mono=time.monotonic(),started_utc=datetime.now(timezone.utc).isoformat(),
             stats={k:dict(start=self.live[k]['continuous'],end=self.live[k]['continuous'],low=self.live[k]['continuous'],high=self.live[k]['continuous'],travel=0) for k in keys},samples=[])
        self.audit(dict(kind='capture_started',capture_id=self.capture['id'],capture_kind=kind,target=target))
    def finish_capture(self):
        self.fresh()
        if not self.capture:raise ValueError('没有进行中的采集')
        c=self.capture;self.capture=None
        duration=time.monotonic()-c['started_mono']
        trace=copy.deepcopy(c);trace['duration_s']=duration
        atomic_json(self.ws/f"capture-{c['id']}.json",trace)
        if duration<.4 or len(c['samples'])<3:raise ValueError('采集时间太短，请重试')
        kind,target=c['kind'],c['target']
        try:
            if kind.startswith('group_'):return self.finish_group(c)
            if kind=='mapping':
                spans={k:s['high']-s['low'] for k,s in c['stats'].items()}
                motor=candidate_mapping(spans)
                self.result=dict(kind='mapping',target=target,motor=motor,spans=spans,capture_id=c['id'])
                return self.result
            if kind in ['positive','range']:
                j=self.get_target(target);stat=c['stats'][j['motor']]
                if kind=='positive':
                    j['sign']=infer_sign(stat['end']-stat['start'],stat['travel']);j['sign_capture']=c['id'];j.pop('limits',None)
                else:
                    j['limits']=measured_limits(stat['low'],stat['high'],j['reference']['continuous'],j['sign'],JOINTS[target]['reference_q'])
                    j['limits']['capture_id']=c['id'];j['limits']['counts']=[stat['low'],stat['high']]
                self.save();self.result=dict(kind=kind,target=target,ok=True)
            elif kind=='base':
                trial={w:dict(delta=c['stats'][self.data['wheels'][w]['motor']]['end']-c['stats'][self.data['wheels'][w]['motor']]['start'],travel=c['stats'][self.data['wheels'][w]['motor']]['travel']) for w in WHEELS}
                if any(abs(x['delta'])<35 for x in trial.values()):raise ValueError('有轮子的变化太小，请检查是否滑动并重采')
                if any(x['travel']>abs(x['delta'])*1.8+30 for x in trial.values()):raise ValueError('有轮子发生明显往返，请沿指定方向单向推车并重采')
                self.data['base'].setdefault('trials',{})[target]=trial
                self.data['base'].setdefault('trace_ids',{})[target]=c['id'];self.invalidate_base();self.save()
                self.result=dict(kind='base',target=target,ok=True)
            self.audit(dict(kind='capture_completed',capture_id=c['id']))
            return self.result
        except Exception as e:
            self.audit(dict(kind='capture_rejected',capture_id=c['id'],reason=str(e)));raise
    def confirm_mapping(self,target,motor):
        r=self.result
        if not r or r.get('kind')!='mapping' or r['target']!=target or r['motor']!=motor:raise ValueError('请先采集并确认识别结果')
        if motor in self.mapped_keys():raise ValueError('此电机已分配给另一个关节')
        group='joints' if target in JOINTS else 'wheels'
        self.data[group][target]=dict(motor=motor,mapping_capture=r['capture_id'])
        self.result=None
        if group=='wheels':self.data['base'].pop('trials',None);self.invalidate_base()
        self.save()
    def reference(self,target):
        self.fresh()
        if self.capture:raise ValueError('先结束采集')
        if target not in JOINTS:raise ValueError('请选择关节')
        j=self.get_target(target)
        if not j:raise ValueError('先识别对应电机')
        key=j['motor'];recent=[v for t,v in self.history[key] if time.monotonic()-t<.6]
        if len(recent)<4 or max(recent)-min(recent)>12:raise ValueError('姿态还在变化，请保持约半秒后再记录')
        if self.live[key]['torque']!=0:raise ValueError('请先释放该电机扭矩，手动粗摆')
        value=sum(recent)/len(recent)
        j['reference']=dict(continuous=value,present_modulo=value%CPR,reference_q=JOINTS[target]['reference_q'],epoch=self.epoch,utc=datetime.now(timezone.utc).isoformat(),spread_counts=max(recent)-min(recent))
        j.pop('limits',None);j.pop('sign',None)
        self.save();self.audit(dict(kind='reference_recorded',target=target,value=value))
    def status(self):
        summary=self.summary()
        return dict(demo=self.demo,connected=self.connected,epoch=self.epoch,error=self.error,workspace=str(self.ws),data=self.data,live=self.live,motors=self.meta(),joints=JOINTS,groups=GROUPS,wheels=WHEEL_LABELS,directions=DIRECTIONS,capture=None if not self.capture else {k:v for k,v in self.capture.items() if k not in ['samples','started_mono']},result=self.result,summary=summary)
    def summary(self):
        missing=[]
        for key in JOINTS:
            j=self.data['joints'].get(key,{})
            if not all(k in j for k in ['motor','reference','sign','limits']):missing.append(JOINTS[key]['label'])
        base_ok='solution' in self.data['base']
        return dict(joints_complete=14-len(missing),missing_joints=missing,base_complete=base_ok,
            passive_complete=not missing and base_ok,ready_for_active_control=False,
            outstanding=['速度指令单位与主动方向未验证','主动停止响应未验证','相机历史参数尚需核对' if self.data['camera']['status']=='not_imported' else '相机参数沿用，未重标定'])
    def export(self):
        import io,zipfile
        self.save()
        payload=copy.deepcopy(self.data)
        payload['status']=self.summary();payload['backup_path']=str(self.backup);payload['demo']=self.demo
        payload['conversion']={'counts_per_revolution':4096,'formula':'q = q_ref + sign * (unwrapped_present_count - reference_count) * 2*pi/4096',
             'reconnect':'resolve modulo count into recorded count interval; reject ambiguity; continuous state is not preserved across disconnected periods',
             'head_reference_q':math.pi,'persistent_servo_registers_modified':False,'active_control_implemented':False}
        files={'calibration.json':json.dumps(payload,ensure_ascii=False,indent=2).encode()}
        files['README.txt']='被动粗标定结果；未验收主动控制。不可直接作为已经完成的实机控制器。每个 reference_count 属于当次连续展开坐标，重新连接须按范围消歧；不能将 raw Present_Position 当 XML 零位。\n'.encode()
        files['model/robot.xml']=(ROOT/'model/robot.xml').read_bytes()
        files['model/interface_mapping.json']=(ROOT/'model/interface_mapping.json').read_bytes()
        for p in (ROOT/'model/meshes').iterdir():
            if p.is_file():files['model/meshes/'+p.name]=p.read_bytes()
        for p in self.ws.glob('capture-*.json'):files['evidence/'+p.name]=p.read_bytes()
        if (self.ws/'events.jsonl').exists():files['evidence/events.jsonl']=(self.ws/'events.jsonl').read_bytes()
        for p in (self.ws/'camera-import').glob('*') if (self.ws/'camera-import').exists() else []:
            if p.is_file():files['camera/'+p.name]=p.read_bytes()
        # Keep original XML geometry; this tool exports the measured motor mapping as a sidecar.
        files['SHA256SUMS.json']=json.dumps({k:hashlib.sha256(v).hexdigest() for k,v in files.items()},indent=2).encode()
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
            for k,v in files.items():z.writestr(k,v)
        return output.getvalue()
    def action(self,op,p):
        if op=='connect':self.connect()
        elif op=='disconnect':self.disconnect()
        elif op=='release':
            self.fresh()
            if self.capture:raise ValueError('先结束采集')
            if p.get('supported') is not True:raise ValueError('请确认已托住选中的部件')
            self.hw.release(p.get('motors',[]));self.ingest(self.hw.sample())
        elif op=='capture_start':self.start_capture(p['kind'],p['target'])
        elif op=='capture_finish':self.finish_capture()
        elif op=='capture_cancel':
            if self.capture:self.audit(dict(kind='capture_cancelled',capture_id=self.capture['id']))
            self.capture=None;self.result=None
        elif op=='group_mapping_confirm':self.confirm_group(p['group'])
        elif op=='group_reference':self.group_reference(p['group'])
        elif op=='group_reset':self.reset_group(p['group'],p['scope'])
        elif op=='mapping_confirm':self.confirm_mapping(p['target'],p['motor'])
        elif op=='reference':self.reference(p['target'])
        elif op=='reset_target':
            if self.capture:raise ValueError('先结束采集')
            target=p['target'];group='joints' if target in JOINTS else 'wheels' if target in WHEELS else None
            if not group:raise ValueError('无效目标')
            previous=self.data[group].pop(target,None);self.audit(dict(kind='target_reset',target=target,previous=previous))
            if group=='wheels':self.data['base'].pop('trials',None);self.invalidate_base()
            self.save()
        elif op=='dimensions':
            dims={k:float(p[k]) for k in ['diameter_mm','track_mm','wheelbase_mm']};dims['pattern']='X'
            if p.get('pattern_confirmed') is not True or p.get('direct_drive_confirmed') is not True:raise ValueError('请先核对滚子排列与直驱关系')
            wheel_matrix(**dims);self.data['base']['dimensions']=dims;self.invalidate_base();self.save()
        elif op=='solve_base':
            base=self.data['base']
            if 'dimensions' not in base:raise ValueError('先保存底盘尺寸')
            base['solution']=solve_base(base.get('trials',{}),base['dimensions']);self.save()
        else:raise ValueError('未知操作')
        return self.status()

class DemoHardware:
    """Offline preview only. Never imports serial transport or opens a device."""
    def __init__(self,backup,audit):
        self.motors={};self.positions={};self.torques={}
        for bus,ids in [('DEMO-A',[1,2,3,4,5,6,9,10,11,12]),('DEMO-B',[1,2,3,4,5,6,7,8])]:
            for i in ids:
                key=f'{bus}:{i}';self.motors[key]=dict(serial=bus,id=i,short=f'{bus} · ID {i}',model='sts3250' if i>=9 else 'sts3215');self.positions[key]=2048;self.torques[key]=0
    def connect(self):return self.sample()
    def sample(self):return {k:dict(present_raw=int(p)%4096,present=int(p)%4096,torque=self.torques[k],voltage=12.0,temperature=25,velocity_raw=0,stamp=time.time()) for k,p in self.positions.items()}
    def check_configs(self):pass
    def release(self,keys):
        if any(k not in self.motors for k in keys):raise ValueError('无效电机')
        for k in keys:self.torques[k]=0
    def close(self):pass
