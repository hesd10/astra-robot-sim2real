"""One bounded pulse and fresh observation; no visual continue/stop judgment."""
import math,time,json
from pathlib import Path

def validate(vx,vy,duration):
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in [vx,vy,duration]):raise ValueError('finite numeric pulse required')
    if math.hypot(vx,vy)>.060000001 or not .1<=duration<=.8:raise ValueError('pulse exceeds local limits')
def healthy(api):
    s=api.call('state')
    if s.get('fault') or s.get('finished') or s.get('health')!='normal':raise RuntimeError('state does not permit local motion')
    return s
def step(api,*,vx,vy,duration):
    validate(vx,vy,duration);healthy(api)
    try:
        ack=api.call('base',vx=vx,vy=vy,wz=0,duration=duration)
        if not ack.get('accepted'):raise RuntimeError('motion rejected')
        api.sleep(duration+.3)
        api.call('stop');healthy(api)
        return api.observe()
    except BaseException:
        api.call('stop');raise
class Live:
    def __init__(self):
        import robot
        self.call=robot.call;self.observe=robot.observe;self.sleep=time.sleep
