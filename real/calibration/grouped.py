"""Arm-level mapping/reference/range; individual joint direction checks."""
import copy, time
from datetime import datetime, timezone
from domain import JOINTS, CPR, candidate_mapping, measured_limits

GROUPS={'left':'左臂','right':'右臂','head':'头部'}
def members(group):
    if group not in GROUPS:raise ValueError('未知分组')
    return [k for k,s in JOINTS.items() if s['group']==group]

def expected_id(channel):
    n=int(channel.split('_')[1])
    return n+6 if channel.startswith('head') else n

class GroupedCalibration:
    def group_keys(self,kind,group):
        channels=members(group)
        if kind=='group_mapping':
            ids={expected_id(k) for k in channels}
            occupied={j['motor'] for k,j in self.data['joints'].items() if k not in channels}
            return [k for k,m in self.hw.motors.items() if m['model']=='sts3215' and m['id'] in ids and k not in occupied and self.live[k]['torque']==0]
        if kind=='group_range':
            keys=[]
            for channel in channels:
                j=self.data['joints'].get(channel,{})
                if not all(k in j for k in ['motor','reference','sign']):raise ValueError('请先完成本组对应关系、整组参考姿态和各关节正方向')
                if j['reference']['epoch']!=self.epoch:raise ValueError('连接已变化，请重新记录本组参考姿态')
                keys.append(j['motor'])
            return keys
        raise ValueError('未知分组采集类型')
    def finish_group(self,c):
        group=c['target'];channels=members(group)
        if c['kind']=='group_mapping':
            scores={}
            for key,stat in c['stats'].items():
                serial=self.hw.motors[key]['serial'];scores[serial]=scores.get(serial,0)+stat['high']-stat['low']
            serial=candidate_mapping(scores)
            motor_map={}
            for channel in channels:
                found=[k for k,m in self.hw.motors.items() if m['serial']==serial and m['id']==expected_id(channel)]
                if len(found)!=1:raise ValueError('所识别总线不包含本组完整电机 ID')
                motor_map[channel]=found[0]
            self.result=dict(kind='group_mapping',target=group,serial=serial,motor_map=motor_map,capture_id=c['id'],scores=scores)
            return self.result
        rejected={};updates={}
        for channel in channels:
            j=self.data['joints'][channel];stat=c['stats'][j['motor']]
            lo,hi=stat['low'],stat['high']
            previous=j.get('limits')
            if previous:
                lo=min(lo,previous['counts'][0]);hi=max(hi,previous['counts'][1])
            try:
                limits=measured_limits(lo,hi,j['reference']['continuous'],j['sign'],JOINTS[channel]['reference_q'])
                limits.update(capture_id=c['id'],counts=[lo,hi])
                updates[channel]=limits
            except ValueError as e:rejected[channel]=str(e)
        for channel,limits in updates.items():self.data['joints'][channel]['limits']=limits
        self.save()
        self.result=dict(kind='group_range',target=group,ok=not rejected,partial=bool(rejected),rejected=rejected,saved=list(updates))
        self.audit(dict(kind='group_range_saved',capture_id=c['id'],group=group,rejected=rejected,saved=list(updates)))
        return self.result
    def confirm_group(self,group):
        self.fresh()
        r=self.result
        if self.capture or not r or r.get('kind')!='group_mapping' or r['target']!=group:raise ValueError('请先识别并确认本组总线')
        channels=members(group)
        other={j['motor'] for k,j in self.data['joints'].items() if k not in channels}
        if other.intersection(r['motor_map'].values()):raise ValueError('这条总线的电机已分配给其他分组，请核对左右臂')
        for channel,key in r['motor_map'].items():
            j=self.data['joints'].get(channel,{})
            if j.get('motor')!=key:j={'motor':key}
            j['mapping_capture']=r['capture_id'];j['mapping_method']='group_bus_and_standard_id_order'
            self.data['joints'][channel]=j
        self.data.setdefault('groups',{})[group]=dict(serial=r['serial'],mapping_capture=r['capture_id'])
        self.audit(dict(kind='group_mapping_confirmed',group=group,motor_map=r['motor_map']))
        self.result=None;self.save()
    def group_reference(self,group):
        self.fresh()
        if self.capture:raise ValueError('先结束采集')
        self.hw.check_configs()
        staged={}
        for channel in members(group):
            j=copy.deepcopy(self.data['joints'].get(channel,{}))
            if 'motor' not in j:raise ValueError('先识别整组电机')
            key=j['motor'];recent=[v for t,v in self.history[key] if time.monotonic()-t<.6]
            if len(recent)<4 or max(recent)-min(recent)>12:raise ValueError(f'{JOINTS[channel]["label"]} 还在变化，请将整组保持约半秒后记录')
            if self.live[key]['torque']!=0:raise ValueError('请先释放本组扭矩，手动粗摆')
            value=sum(recent)/len(recent)
            j['reference']=dict(continuous=value,present_modulo=value%CPR,reference_q=JOINTS[channel]['reference_q'],epoch=self.epoch,utc=datetime.now(timezone.utc).isoformat(),spread_counts=max(recent)-min(recent),method='group_snapshot')
            j.pop('limits',None);j.pop('sign',None);j.pop('sign_capture',None)
            staged[channel]=j
        # All validate before any saved joint is changed.
        self.data['joints'].update(staged);self.save()
        self.audit(dict(kind='group_reference_recorded',group=group,channels=staged))
    def reset_group(self,group,scope):
        if self.capture:raise ValueError('先结束采集')
        if scope not in ['mapping','range']:raise ValueError('未知重录范围')
        channels=members(group)
        self.audit(dict(kind='group_reset',group=group,scope=scope,previous={k:self.data['joints'].get(k) for k in channels}))
        for k in channels:
            if scope=='mapping':self.data['joints'].pop(k,None)
            else:self.data['joints'].get(k,{}).pop('limits',None)
        if scope=='mapping':self.data.get('groups',{}).pop(group,None)
        self.result=None;self.save()
