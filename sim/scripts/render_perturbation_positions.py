"""Render operator-only point previews from the actual MuJoCo indoor scene."""
import json,math
from pathlib import Path
import mujoco
import numpy as np
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'studies/position-perturbation-001/rendered'
OUT.mkdir(exist_ok=True)
r=json.loads((OUT.parent/'positions.json').read_text());ref=json.loads((ROOT/'studies/body-experience-001/private-initial-reference.json').read_text())
m=mujoco.MjModel.from_xml_path(str(ROOT/'models/elevator_four_mecanum.xml'));d=mujoco.MjData(m);q=int(m.joint('base_free').qposadr[0]);m.vis.global_.offwidth=1280;m.vis.global_.offheight=960
colors={.1:[.05,.8,.6,1],.5:[1,.55,.05,1],1.:[.7,.3,1,1]}
def pose(offset=(0,0)):
 d.qpos[:]=ref['qpos'];d.qpos[q:q+2]+=offset;mujoco.mj_forward(m,d)
def marker(scene,pos,color,label='',size=.045):
 g=scene.geoms[scene.ngeom];mujoco.mjv_initGeom(g,mujoco.mjtGeom.mjGEOM_SPHERE,np.array([size]*3),np.array(pos,dtype=float),np.eye(3).flatten(),np.array(color,dtype=np.float32));g.label=label;scene.ngeom+=1
cam=mujoco.MjvCamera();cam.lookat[:]=[7.25,2.1,.5];cam.distance=4.6;cam.azimuth=25;cam.elevation=-42
with mujoco.Renderer(m,height=900,width=1200) as renderer:
 pose();renderer.update_scene(d,camera=cam)
 for p in r['points']:marker(renderer.scene,[*p['world_xy_m'],.07],colors[p['radius_m']],p['id'])
 marker(renderer.scene,[*r['origin_world_xy_m'],.03],[.2,.9,1,1],'START',.05)
 for radius in r['radii_m']:
  for a in np.linspace(0,2*np.pi,100,endpoint=False):
   x,y=np.array(r['origin_world_xy_m'])+radius*np.array([np.cos(a),np.sin(a)])
   marker(renderer.scene,[x,y,.012],colors[radius],size=.007)
 renderer.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION]=False
 Image.fromarray(renderer.render()).save(OUT/'overview.png')
# Nine separate poses, same camera in every image; each pose is an independent start.
cam.lookat[:]=[7.25,2.15,.75];cam.distance=4.8;cam.elevation=-24;cam.azimuth=25
font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',21)
board=Image.new('RGB',(1920,3*520),(245,247,250));draw=ImageDraw.Draw(board)
with mujoco.Renderer(m,height=480,width=640) as renderer:
 for i,p in enumerate(r['points']):
  pose(p['offset_world_xy_m']);renderer.update_scene(d,camera=cam);renderer.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION]=False
  marker(renderer.scene,[*r['origin_world_xy_m'],.03],[.2,.9,1,1],'',.055)
  img=Image.fromarray(renderer.render());img.save(OUT/(p['id']+'.png'))
  col=i%3;row=i//3;board.paste(img,(col*640,row*520+40));f,l=p['offset_initial_body_forward_left_m']
  draw.text((col*640+12,row*520+8),f'{p["id"]}  Forward {f*100:+.1f} cm / Left {l*100:+.1f} cm',font=font,fill=(30,40,55))
board.save(OUT/'nine-starts.png')
(OUT/'README.md').write_text('Actual MuJoCo scene renders. Overview robot is at the original start; coloured rings/markers are operator annotations (green=10cm, orange=50cm, purple=100cm). Nine-starts shows one independently translated robot per panel, with a fixed camera; cyan floor marker is the original start. Camera, overlays and renders are not provided to subjects. No simulation assets or frozen trial inputs changed.\n')
print(OUT)
