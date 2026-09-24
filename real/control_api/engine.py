"""Timed coordinated trajectories. No thermal, load or tracking-error controller."""
import math,time,json,copy,hashlib
from transport import signed_word
from profiles import base_raw_acceleration,joint_profile,BASE_TRANSLATION_ACCELERATION,BASE_YAW_ACCELERATION
CPR=4096;TAU=2*math.pi

def number(x,lo,hi):
    if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or not lo<=x<=hi:raise ValueError('Invalid numeric field')
    return float(x)

class Engine:
    def __init__(self,calibration,hw,audit=lambda e:None,clock=time.monotonic,base_enabled=False):
        self.cal=calibration;self.hw=hw;self.audit=audit;self.clock=clock;self.base_enabled=base_enabled
        self.channels=calibration['joints'];self.arm_keys=[j['motor'] for j in self.channels.values()]
        self.max_translation_speed=number(calibration['base'].get('max_translation_speed_mps',.1),.001,.1)
        self.solution=calibration['base']['solution'];self.wheels=self.solution['wheel_order']
        self.wheel_keys=[calibration['wheels'][w]['motor'] for w in self.wheels]
        self.hw.connect();self.hw.modes_valid(self.arm_keys,self.wheel_keys)
        self.started=clock();self.motion=None;self.base_until=0;self.base_command=[0.,0.,0.];self.base_goal=[0.,0.,0.];self.last_base_tick=clock();self.fault=None;self.finished=False
        self.armed=False;self.arm_enabled=False;self.wheel_started=False;self.counts={};self.previous={};self.targets={};self.bounds={};self.last_profile={};self.cache={};self.action_number=0;self.outcome=None
        for n,j in self.channels.items():
            r=j['reference'];a,b=sorted(r['continuous']+(j['limits'][v]-r['reference_q'])*CPR/(j['sign']*TAU) for v in ['usable_min_rad','usable_max_rad'])
            orig=hw.motors[j['motor']]['original'];lo=orig[9]+256*orig[10];hi=orig[11]+256*orig[12]
            if (lo,hi)!=(0,4095):a=max(a,lo);b=min(b,hi)
            self.bounds[n]=(max(0,math.ceil(a)),min(4095,math.floor(b)))
        self.sample();goals=hw.goals(self.arm_keys)
        for n,j in self.channels.items():
            k=j['motor'];self.targets[n]=self._lift(n,goals[k]) if self.live[k]['torque'] else self.counts[n]
    def _lift(self,n,raw):
        j=self.channels[n];lo,hi=j['limits']['counts'];options=[raw%CPR+CPR*i for i in range(-3,4) if lo-12<=raw%CPR+CPR*i<=hi+12]
        if len(options)!=1:raise ValueError('Encoder branch cannot be resolved: '+n)
        return options[0]
    def q(self,n,c):
        j=self.channels[n];r=j['reference'];return r['reference_q']+j['sign']*(c-r['continuous'])*TAU/CPR
    def sample(self):
        live=self.hw.sample()
        for n,j in self.channels.items():
            raw=live[j['motor']]['position']%CPR
            if n in self.previous:self.counts[n]+=(raw-self.previous[n]+CPR//2)%CPR-CPR//2
            else:self.counts[n]=self._lift(n,raw)
            self.previous[n]=raw
        self.live=live;self.sample_time=self.clock()
    def arm(self,arms=True):
        if self.finished or self.fault:raise RuntimeError('Session ended/faulted')
        if self.armed:return
        if not arms and not self.base_enabled:raise ValueError('Base-only arming requires base enabled')
        self.sample()
        if arms:
            disabled=[n for n,j in self.channels.items() if not self.live[j['motor']]['torque']]
            for n in disabled:self.targets[n]=self.counts[n]
            if disabled:self.hw.sync(42,2,{self.channels[n]['motor']:round(self.targets[n])%CPR for n in disabled},True)
            self.hw.sync(41,1,{j['motor']:joint_profile(n)['raw_acceleration'] for n,j in self.channels.items()},True)
            self.hw.sync(44,2,{k:0 for k in self.arm_keys},True)
            self.hw.sync(46,2,{j['motor']:joint_profile(n)['raw_velocity'] for n,j in self.channels.items()},True)
        if self.base_enabled:
            self.wheel_started=True
            self.hw.sync(41,1,{k:base_raw_acceleration(self.cal) for k in self.wheel_keys},True)
            self.hw.sync(46,2,{k:0 for k in self.wheel_keys},True)
        keys=(self.arm_keys if arms else [])+(self.wheel_keys if self.base_enabled else [])
        self.hw.sync(40,1,{k:1 for k in keys},True);self.armed=True;self.arm_enabled=arms;self.sample()
    def schema(self):
        return {'protocol':'astra-real-v1','cameras':['head','left_wrist','right_wrist'],'joint_units':'rad',
          'zero_reference':'calibrated XML reference; not startup pose',
          'joints':{n:dict(minimum=min(self.q(n,c) for c in self.bounds[n]),maximum=max(self.q(n,c) for c in self.bounds[n]),continuous=False,zero=0.,max_target_speed=joint_profile(n)['speed'],max_target_acceleration=joint_profile(n)['acceleration']) for n in self.channels},
          'base':dict(frame='robot',vx='forward m/s',vy='left m/s',wz='CCW rad/s',max_translation_speed=self.max_translation_speed,max_yaw_speed=math.pi/12,max_translation_acceleration=BASE_TRANSLATION_ACCELERATION,max_yaw_acceleration=BASE_YAW_ACCELERATION,max_duration=5.,enabled=self.base_enabled,calibration_status='nominal geometry; wheel signs and stop paths tested; operator confirmed body directions; ground scale remains nominal'),
          'max_joint_duration':10.,'protection':'motor firmware; no temperature sampling or tracking-error gating'}
    def state(self):
        return dict(elapsed=self.clock()-self.started,sample_monotonic=self.sample_time,joints={n:dict(position=self.q(n,self.counts[n]),target=self.q(n,self.targets[n]),velocity=self.live[j['motor']]['velocity']*j['sign']*TAU/CPR,torque_enabled=bool(self.live[j['motor']]['torque'])) for n,j in self.channels.items()},fault=self.fault,finished=self.finished,armed=self.armed,motion_active=self.motion is not None,base_command=list(self.base_command),base_target=list(self.base_goal),wheels={w:dict(self.live[k]) for w,k in zip(self.wheels,self.wheel_keys)},base_readback_kind='command, not odometry',declared_outcome=self.outcome)
    def wheel_values(self,vec):
        values={}
        for i,w in enumerate(self.wheels):
            radps=sum(a*b for a,b in zip(self.solution['matrix_body_mps_radps_to_wheel_radps'][i],vec))
            raw=round(radps*CPR/TAU*self.solution['encoder_sign_for_forward_roll'][w])
            values[self.wheel_keys[i]]=signed_word(raw)
        return values
    def zero_base(self):
        if self.wheel_started:self.hw.sync(46,2,{k:0 for k in self.wheel_keys},True)
        self.base_command=[0.,0.,0.];self.base_goal=[0.,0.,0.];self.base_until=0
    def step_base(self,now):
        dt=max(0,min(.1,now-self.last_base_tick));self.last_base_tick=now
        if not self.wheel_started:return
        if self.base_until and now>=self.base_until:
            self.base_goal=[0.,0.,0.];self.base_until=0
        delta=[a-b for a,b in zip(self.base_goal,self.base_command)]
        length=math.hypot(*delta[:2]);scale=min(1,BASE_TRANSLATION_ACCELERATION*dt/max(length,1e-30))
        delta[:2]=[x*scale for x in delta[:2]]
        cap=BASE_YAW_ACCELERATION*dt;delta[2]=max(-cap,min(cap,delta[2]))
        command=[a+b for a,b in zip(self.base_command,delta)]
        if command!=self.base_command:
            self.hw.sync(46,2,self.wheel_values(command))
            self.base_command=command
    def stop(self):
        self.motion=None;self.zero_base() # retain last applied joint targets, never home/release
    def release(self):
        self.stop();self.hw.sync(40,1,{k:0 for k in self.arm_keys+self.wheel_keys},True);self.armed=False;self.arm_enabled=False;self.wheel_started=False
    def tick(self):
        now=self.clock()
        # Expiry precedes position sampling; slow sensor read cannot extend a completed pulse.
        self.step_base(now)
        if self.motion:
            m=self.motion;u=min(1,(now-m['start_time'])/m['duration']);f=u*u*(3-2*u)
            new={n:round(a+(m['end'][n]-a)*f) for n,a in m['start'].items()}
            self.hw.sync(42,2,{self.channels[n]['motor']:c%CPR for n,c in new.items()});self.targets.update(new)
            if u>=1:self.motion=None
        self.sample()
        if self.armed:
            keys=(self.arm_keys if self.arm_enabled else [])+(self.wheel_keys if self.base_enabled else [])
            if any(self.live[k]['torque']!=1 for k in keys):raise RuntimeError('Motor torque enable was lost')
    def request(self,r):
        op=r.get('op');rid=r.get('id')
        if not isinstance(rid,str) or not 1<=len(rid)<=128:raise ValueError('Request id required')
        canonical=json.dumps(r,sort_keys=True,allow_nan=False)
        if rid in self.cache:
            old,result=self.cache[rid]
            if old!=canonical:raise ValueError('Request id reused with different content')
            return copy.deepcopy(result)
        if len(self.cache)>=100000:raise RuntimeError('Session request budget exhausted')
        if op=='schema':result=self.schema()
        elif op=='state':result=self.state()
        elif op=='stop':self.stop();result={'stopped':True}
        elif op=='finish':
            if r.get('outcome') not in ['success','failure','contamination']:raise ValueError('Invalid outcome')
            self.stop();self.finished=True;self.outcome=r['outcome'];result={'finished':True,'outcome':self.outcome,'operator_confirmation_separate':True}
        elif op in ['move','base']:
            if self.fault or self.finished or not self.armed:raise RuntimeError('Motion unavailable: operator must arm a healthy session')
            if op=='move':
                if not self.arm_enabled:raise ValueError('Arms not enabled in this session')
                if self.motion:raise ValueError('Joint motion busy')
                ts=r.get('targets');duration=number(r.get('duration'),.02,10)
                if not isinstance(ts,dict) or not ts or set(ts)-set(self.channels):raise ValueError('Invalid joint targets')
                end={};start={}
                for n,q in ts.items():
                    q=number(q,-100,100);j=self.channels[n];ref=j['reference'];c=round(ref['continuous']+(q-ref['reference_q'])*CPR/(j['sign']*TAU));lo,hi=self.bounds[n]
                    if not lo<=c<=hi:raise ValueError('Target outside calibrated/register intersection: '+n)
                    a=self.targets[n]
                    if not 0<=a<=4095:raise ValueError('Current branch needs operator repositioning; multi-turn position command not commissioned')
                    dist=abs(c-a)*TAU/CPR
                    if 1.5*dist/duration>joint_profile(n)['speed']+1e-9 or 6*dist/duration**2>joint_profile(n)['acceleration']+1e-9:raise ValueError('Duration too short')
                    # Small timed updates cross modulo zero continuously; firmware/encoder coordinates stay unchanged.
                    end[n]=c;start[n]=a
                self.motion=dict(start=start,end=end,duration=duration,start_time=self.clock())
            else:
                if not self.base_enabled:raise RuntimeError('Base commissioning not enabled by operator')
                vx=number(r.get('vx',0),-self.max_translation_speed,self.max_translation_speed);vy=number(r.get('vy',0),-self.max_translation_speed,self.max_translation_speed);wz=number(r.get('wz',0),-math.pi/12,math.pi/12);duration=number(r.get('duration'),.01,5)
                if math.hypot(vx,vy)>self.max_translation_speed+1e-9:raise ValueError('Translation speed too large')
                self.base_goal=[vx,vy,wz];self.base_until=self.clock()+duration
            self.action_number+=1;result=dict(accepted=True,action_number=self.action_number)
        else:raise ValueError('Unknown operation')
        self.cache[rid]=(canonical,copy.deepcopy(result));self.audit(dict(event='request',request=r,result=result));return result
