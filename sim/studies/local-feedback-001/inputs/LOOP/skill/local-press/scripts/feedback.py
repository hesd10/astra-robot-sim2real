"""Local visual feedback derived from er001-t005; no target identity inference."""
import time
from PIL import Image
from primitive import step,healthy,validate

def detect(obs,regions):
    counts={}
    for view,box in regions.items():
        with Image.open(obs['files'][view]) as im:
            im=im.convert('RGB');x0,y0,x1,y1=box
            if not (0<=x0<x1<=im.width and 0<=y0<y1<=im.height):raise ValueError('ROI outside current image')
            counts[view]=sum(r>160 and r>1.7*g and r>1.7*b for r,g,b in im.crop(box).getdata())
    return counts

def run(api,*,vx,vy,duration,regions,max_steps=6,max_seconds=30):
    validate(vx,vy,duration)
    if not isinstance(max_steps,int) or isinstance(max_steps,bool) or not 1<=max_steps<=8:raise ValueError('max_steps 1..8')
    if not 0<max_seconds<=60:raise ValueError('max_seconds 0..60')
    if not regions or set(regions)-{'head','right_wrist'}:raise ValueError('head/right_wrist ROI required')
    if any(len(b)!=4 or any(type(v)!=int for v in b) for b in regions.values()):raise ValueError('integer ROI boxes required')
    started=time.monotonic();history=[];last=None
    try:
        healthy(api);last=api.observe();initial=detect(last,regions)
        if max(initial.values())>30:return dict(reason='already_red_recheck',steps=0,observation=last,counts=initial)
        for i in range(max_steps):
            if time.monotonic()-started>=max_seconds:return dict(reason='time_budget',steps=i,observation=last,history=history)
            last=step(api,vx=vx,vy=vy,duration=duration);counts=detect(last,regions)
            history.append(dict(step=i+1,counts=counts,sim_time=last.get('sim_time')))
            if max(counts.values())>30:return dict(reason='red_detected_verify',steps=i+1,observation=last,history=history)
        return dict(reason='step_budget',steps=max_steps,observation=last,history=history)
    finally:
        api.call('stop')
