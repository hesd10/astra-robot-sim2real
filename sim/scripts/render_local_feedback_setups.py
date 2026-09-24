import sys
from pathlib import Path
import mujoco
from PIL import Image,ImageDraw
sys.path.insert(0,'scripts')
from prepare_local_feedback_states import OUT,load_stage
from sim_env.rendering import follow_camera
out=OUT/'previews';out.mkdir(exist_ok=True)
room_cam=None
for name in ['S1','S2','S3']:
 c=load_stage(OUT/'states'/f'{name}.json')
 with mujoco.Renderer(c.m,height=720,width=960) as r:
  if room_cam is None: room_cam=follow_camera(c.m,c.d)
  cam=room_cam
  r.update_scene(c.d,camera=cam);Image.fromarray(r.render()).save(out/f'{name}-room.png')
  # Identical world-fixed camera for the three setups, close enough to show the gap.
  cam=mujoco.MjvCamera();cam.lookat[:]=[float(c.d.body('button_2_up').xpos[0]),3.9,float(c.d.body('button_2_up').xpos[2])];cam.distance=.65;cam.azimuth=30;cam.elevation=-10
  r.update_scene(c.d,camera=cam);Image.fromarray(r.render()).save(out/f'{name}-close.png')
rows=[('room',960,720),('close',960,720),('head',640,480),('right_wrist',640,480)]
for role,w,h in rows:
 sheet=Image.new('RGB',(3*w,h+50),'white');d=ImageDraw.Draw(sheet)
 for i,name in enumerate(['S1','S2','S3']):
  f=out/f'{name}-{role}.png' if role in ['room','close'] else OUT/'states'/f'{name}-{role}.jpg'
  sheet.paste(Image.open(f),(i*w,50));d.text((i*w+20,15),f'{name} | backward offset: {i*2} cm | reference pulses: {i+1}',fill='black')
 sheet.save(out/f'comparison-{role}.jpg',quality=92)
print(out.resolve())
