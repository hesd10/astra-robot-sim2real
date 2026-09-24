import time
from PIL import Image
from operate import request,check,obs,log
check()
for i in range(5):
    r=request('base',vx=.04,vy=.008,wz=0,duration=.8)
    if not r.get('accepted'):raise RuntimeError(r)
    time.sleep(1.1)
    s=check()
    o=obs()
    counts={}
    for view in ('head','right_wrist'):
        im=Image.open(o['files'][view]).convert('RGB')
        box=(400,250,570,410) if view=='head' else (180,260,420,440)
        counts[view]=sum(1 for r,g,b in im.crop(box).getdata() if r>160 and r>1.7*g and r>1.7*b)
    log('red_check',counts,step=i+1)
    if max(counts.values())>30:
        request('stop')
        break
request('stop')
check()
