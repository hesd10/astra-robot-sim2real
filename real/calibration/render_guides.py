"""Render real XML kinematics only (mj_forward); never connects to hardware."""
import os
os.environ.setdefault('MUJOCO_GL','egl')
from pathlib import Path
import json, math, hashlib
import xml.etree.ElementTree as ET
import numpy as np
import mujoco
from PIL import Image, ImageDraw
from domain import JOINTS
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'static/guides';OUT.mkdir(exist_ok=True)
tree=ET.parse(ROOT/'model/robot.xml');xml=tree.getroot()
xml.find('compiler').set('meshdir',str(ROOT/'model/meshes'))
ET.SubElement(xml.find('asset'),'texture',dict(name='guide_sky',type='skybox',builtin='gradient',rgb1='.92 .96 .97',rgb2='.7 .8 .84',width='512',height='512'))
ET.SubElement(xml.find('worldbody'),'light',dict(pos='2 -2 3',dir='-1 1 -1',diffuse='.8 .8 .8',ambient='.5 .5 .5'))
m=mujoco.MjModel.from_xml_string(ET.tostring(xml,encoding='unicode'));d=mujoco.MjData(m)
m.vis.headlight.ambient[:]=[.65,.65,.65];m.vis.headlight.diffuse[:]=[.7,.7,.7]
# Hide collision proxies and duplicate collision meshes, keep actual visual meshes and wheel rollers.
for gi in range(m.ngeom):
    if m.geom_group[gi]==0 and (m.geom_type[gi]==mujoco.mjtGeom.mjGEOM_MESH or m.geom_bodyid[gi]==m.body('chassis').id):m.geom_group[gi]=2
r=mujoco.Renderer(m,height=480,width=640)
opt=mujoco.MjvOption();opt.geomgroup[1]=1;opt.geomgroup[2]=0
base_colors=m.geom_rgba.copy()
manifest={}
for channel,spec in JOINTS.items():
    jid=m.joint(spec['xml']).id; body=int(m.jnt_bodyid[jid]); subtree={body}
    for bid in range(body+1,m.nbody):
        if int(m.body_parentid[bid]) in subtree:subtree.add(bid)
    m.geom_rgba[:]=base_colors
    for gi in range(m.ngeom):
        if int(m.geom_bodyid[gi]) in subtree:m.geom_rgba[gi]=[.11,.72,.64,1]
    d.qpos[:]=m.qpos0
    for c,s in JOINTS.items(): d.qpos[m.joint(s['xml']).qposadr[0]]=s['reference_q']
    mujoco.mj_forward(m,d)
    anchor=d.xanchor[jid].copy()
    # Include distal geometry around selected joint, while keeping context.
    points=[d.xpos[bid].copy() for bid in subtree]
    center=(anchor+np.mean(points,axis=0))/2
    reach=max(np.linalg.norm(p-center) for p in points)
    distance=max(.38,reach*3.8+.18)
    if channel.endswith('_1') and not channel.startswith('head'):distance=max(.9,distance)
    specviews={}
    for view,az,el in [('front',0,-15),('side',90 if spec['group']!='right' else -90,-15),('angle',45 if spec['group']!='right' else -45,-48)]:
        camera=mujoco.MjvCamera();camera.type=mujoco.mjtCamera.mjCAMERA_FREE;camera.lookat[:]=center;camera.distance=distance;camera.azimuth=az;camera.elevation=el
        paths=[]
        for frame in range(13):
            dq=.4*frame/12
            d.qpos[m.joint(spec['xml']).qposadr[0]]=spec['reference_q']+dq
            mujoco.mj_forward(m,d)
            r.update_scene(d,camera=camera,scene_option=opt)
            im=Image.fromarray(r.render())
            draw=ImageDraw.Draw(im)
            draw.rounded_rectangle([12,12,300,48],radius=8,fill=(20,34,43))
            draw.text((24,23),f'{channel}  q={spec["reference_q"]+dq:.3f} rad   +{math.degrees(dq):.0f} deg',fill='white')
            rel=f'guides/{channel}-{view}-{frame:02d}.webp';im.save(ROOT/'static'/rel,quality=86)
            paths.append('/'+rel)
        specviews[view]=paths
        d.qpos[m.joint(spec['xml']).qposadr[0]]=spec['reference_q']
    manifest[channel]=dict(**spec,views=specviews,delta_rad=.4)
    print('Rendered',channel,flush=True)
# Whole reference pose, with head pan pi.
m.geom_rgba[:]=base_colors
d.qpos[:]=m.qpos0
for c,s in JOINTS.items():d.qpos[m.joint(s['xml']).qposadr[0]]=s['reference_q']
mujoco.mj_forward(m,d)
cam=mujoco.MjvCamera();cam.lookat[:]=[0,0,.2];cam.distance=1.8;cam.azimuth=35;cam.elevation=-20
r.update_scene(d,camera=cam,scene_option=opt)
Image.fromarray(r.render()).save(OUT/'reference.webp',quality=90)
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
(OUT/'provenance.json').write_text(json.dumps(dict(source='model/robot.xml',sha256=hashlib.sha256((ROOT/'model/robot.xml').read_bytes()).hexdigest(),engine='MuJoCo mj_forward (no physics stepping)',head_pan_reference_rad=math.pi,other_reference_rad=0),indent=2))
r.close()
