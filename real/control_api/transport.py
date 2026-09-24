"""Exclusive motor owner. Temperature sensor address 63 is never read.
Only RAM writes: torque enable, profile, positions and wheel velocities.
"""
import sys, time, json, math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'calibration'))
from hardware import Hardware
from domain import signed_magnitude
BACKUP=ROOT/'register-backups/20260922-094516-before-calibration'

class Transport(Hardware):
    def sample(self):
        result={}
        for key in self.motors:
            # Two narrow reads deliberately omit load/voltage/temperature/status.
            p=self.read(key,56,4)
            result[key]={'position':signed_magnitude(p[0]|p[1]<<8),
                         'velocity':signed_magnitude(p[2]|p[3]<<8),
                         'torque':self.read(key,40,1)[0]}
        return result
    def goals(self,keys):
        return {k:signed_magnitude(int.from_bytes(bytes(self.read(k,42,2)),'little')) for k in keys}
    def sync(self,address,size,values,verify=False):
        from scservo_sdk import GroupSyncWrite
        if (address,size) not in {(40,1),(41,1),(42,2),(44,2),(46,2)}:
            raise ValueError('Register write not permitted')
        if not values or set(values)-set(self.motors):raise ValueError('Unknown motor')
        self.audit(dict(event='write',address=address,size=size,values=values))
        for serial,port in self.ports.items():
            group=GroupSyncWrite(port,self.packet,address,size);count=0
            for k,v in values.items():
                if self.motors[k]['serial']!=serial:continue
                if not isinstance(v,int) or not 0<=v<2**(size*8):raise ValueError('Invalid register value')
                assert group.addParam(self.motors[k]['id'],list(v.to_bytes(size,'little')));count+=1
            if count and group.txPacket()!=0:raise RuntimeError('Motor sync write failed')
        if verify:
            time.sleep(.003)
            for k,v in values.items():
                if int.from_bytes(bytes(self.read(k,address,size)),'little')!=v:raise RuntimeError('Register readback mismatch')
    def modes_valid(self,arm_keys,wheel_keys):
        for k in arm_keys:
            if self.read(k,33,1)[0]!=0:raise RuntimeError('Arm/head must use position mode')
        for k in wheel_keys:
            if self.read(k,33,1)[0]!=1:raise RuntimeError('Wheel must use velocity mode')

def signed_word(value):
    if not -32767<=value<=32767:raise ValueError('Velocity register overflow')
    return abs(value)|(0x8000 if value<0 else 0)

class FakeTransport:
    def __init__(self,config,audit=lambda e:None):
        self.audit=audit;self.writes=[];self.motors={};self.values={};self.wheel_keys={w['motor'] for w in config['wheels'].values()}
        for j in config['joints'].values():
            k=j['motor'];p=round(j['reference']['continuous'])%4096
            self.values[k]={'position':p,'velocity':0,'torque':0,'goal':p}
        for w in config['wheels'].values():self.values[w['motor']]={'position':2048,'velocity':0,'torque':0,'goal':2048}
        for k in self.values:
            original=[0]*87;original[11]=255;original[12]=15
            self.motors[k]={'original':original}
    def connect(self):return self.sample()
    def sample(self):return {k:dict(v) for k,v in self.values.items()}
    def goals(self,keys):return {k:self.values[k]['goal'] for k in keys}
    def sync(self,address,size,values,verify=False):
        self.writes.append((address,dict(values)))
        for k,v in values.items():
            if address==40:self.values[k]['torque']=v
            elif address==42:self.values[k]['goal']=v
            elif address==46:
                self.values[k]['velocity']=signed_magnitude(v)
                if k in self.wheel_keys:self.values[k]['torque']=1
    def modes_valid(self,*args):pass
    def check_configs(self):pass
    def close(self):pass
