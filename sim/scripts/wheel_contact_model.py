"""Build a local, physically supported four-mecanum-wheel scene.

Source assets remain external read-only dependencies. No hardware access.
Wheel dimensions/masses are approximate, not a CAD reconstruction.
"""
from pathlib import Path
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'assets' / 'source'
if not SOURCE.is_dir():
    SOURCE = ROOT.parent / 'mujoco_sim_elevator_button' / 'elevators'
OUTPUT = ROOT / 'models' / 'elevator_four_mecanum.xml'
WHEELS = ('front_left', 'front_right', 'rear_left', 'rear_right')
RADIUS = .05
HALF_LENGTH = .125
HALF_WIDTH = .25


def vec(values):
    return ' '.join(f'{v:.10g}' for v in values)


def build():
    # Source comments contain double hyphens accepted by MuJoCo's XML parser.
    text = re.sub(r'<!--.*?-->', '', (SOURCE / 'elevator_scene_robot.xml').read_text(), flags=re.S)
    tree = ET.ElementTree(ET.fromstring(text))
    root = tree.getroot()
    root.set('model', 'elevator_four_mecanum')
    compiler = root.find('compiler')
    for key in ('meshdir', 'texturedir'):
        compiler.set(key, os.path.relpath((SOURCE / compiler.get(key, '')).resolve(), OUTPUT.parent))
    pan = root.find(".//joint[@name='head_pan_joint']")
    pan.set('limited', 'false')
    pan.attrib.pop('range', None)
    chassis = root.find(".//body[@name='chassis']")
    for node in list(chassis):
        if node.tag == 'joint' or (node.tag == 'body' and node.get('name') in ('left_wheel', 'right_wheel')):
            chassis.remove(node)
        # Remove obsolete rear caster spheres and decorative caster meshes.
        elif node.tag == 'geom' and (node.get('mesh') in ('raskogwheel1', 'raskogwheel2') or node.get('size') == '0.02'):
            chassis.remove(node)
    chassis.insert(0, ET.Element('freejoint', name='base_free'))
    # Match previous total wheel mass (2 kg), redistributed over four wheels.
    actuator = root.find('actuator')
    for node in list(actuator):
        if node.get('name', '').startswith('act_base_'):
            actuator.remove(node)
        elif node.get('name', '').startswith('act_') and not node.get('name', '').startswith('act_door_'):
            node.set('forcerange', '-2.941995 2.941995')
    for node in root.findall('.//joint'):
        if node.get('actuatorfrcrange'):
            node.set('actuatorfrcrange', '-2.941995 2.941995')
    equality = root.find('equality')
    for node in list(equality):
        if node.get('name', '').startswith('lock_base_'):
            equality.remove(node)
    floor = root.find(".//geom[@name='floor']")
    floor.set('friction', '0.8 0.002 0.0001')
    # X arrangement: at the bottom, the roller axis is (-handedness, 1, 0).
    # Its no-slip projection gives r*w = vx - h*vy - (y+h*x)*yaw_rate.
    for name, x, y, handedness in (
        ('front_left', HALF_LENGTH, HALF_WIDTH, 1),
        ('front_right', HALF_LENGTH, -HALF_WIDTH, -1),
        ('rear_left', -HALF_LENGTH, HALF_WIDTH, -1),
        ('rear_right', -HALF_LENGTH, -HALF_WIDTH, 1),
    ):
        # Wheel axle is local +Y. Passive roller axes are tilted +/-45 deg.
        wheel = ET.SubElement(chassis, 'body', name=name, pos=vec((x, y, -.32)))
        ET.SubElement(wheel, 'joint', name=name+'_axle', axis='0 1 0', damping='0.002', armature='0.0001')
        ET.SubElement(wheel, 'inertial', pos='0 0 0', mass='.32', diaginertia='.00025 .0004 .00025')
        ET.SubElement(wheel, 'geom', name=name+'_hub', type='cylinder', size='.031 .018',
                      quat='0.7071067812 0.7071067812 0 0', rgba='.22 .25 .29 1',
                      contype='0', conaffinity='0', group='1', mass='0')
        for i in range(12):
            theta = 2*math.pi*(i+.5)/12
            radial = np.array([math.sin(theta), 0., math.cos(theta)])
            tangent = np.array([math.cos(theta), 0., -math.sin(theta)])
            axis = (np.array([0., 1., 0.]) + handedness*tangent)/math.sqrt(2)
            roller = ET.SubElement(wheel, 'body', name=f'{name}_roller_{i}', pos=vec(.041*radial))
            ET.SubElement(roller, 'joint', name=f'{name}_roller_{i}_spin', axis=vec(axis), damping='0.00001')
            ET.SubElement(roller, 'geom', name=f'{name}_tread_{i}', type='ellipsoid',
                          size='.009 .009 .023', zaxis=vec(axis), mass='.015',
                          rgba='.13 .15 .17 1', friction='0.8 0.002 0.0001',
                          priority='1', condim='4', solref='.006 1', solimp='.95 .99 .001')
        ET.SubElement(actuator, 'velocity', name='act_'+name, joint=name+'_axle',
                      kv='.25', forcerange='-.4 .4', ctrlrange='-5 5')
    # Adjacent rollers belong to sibling bodies: suppress their internal contacts.
    contact = root.find('contact')
    if contact is None:
        contact = ET.SubElement(root, 'contact')
    for name in WHEELS:
        for i in range(12):
            for j in range(i+1, 12):
                ET.SubElement(contact, 'exclude', body1=f'{name}_roller_{i}', body2=f'{name}_roller_{j}')
            ET.SubElement(contact, 'exclude', body1='chassis', body2=f'{name}_roller_{i}')
    ET.indent(tree, space='  ')
    tree.write(OUTPUT, encoding='unicode')
    return OUTPUT


def load():
    if not OUTPUT.exists():
        build()
    model = mujoco.MjModel.from_xml_path(str(OUTPUT))
    data = mujoco.MjData(model)
    sys.path.insert(0, str(SOURCE))
    import home_pose
    home_pose.apply(model, data)
    # Open floor, away from walls. Initialization only; subsequent pose is dynamic.
    adr = model.joint('base_free').qposadr[0]
    data.qpos[adr:adr+7] = [6.85, 2.5, .375, 1., 0., 0., 0.]
    mujoco.mj_forward(model, data)
    return model, data


def command(model, data, vx=0., vy=0., yaw_rate=0.):
    """Body-frame m/s and rad/s; use a ramp at the caller for acceleration limits."""
    k = HALF_LENGTH + HALF_WIDTH
    speeds = np.array([vx-vy-k*yaw_rate, vx+vy+k*yaw_rate,
                       vx+vy-k*yaw_rate, vx-vy+k*yaw_rate]) / RADIUS
    speeds /= max(1., float(np.max(np.abs(speeds)))/5.)
    for name, speed in zip(WHEELS, speeds):
        data.ctrl[model.actuator('act_'+name).id] = speed


if __name__ == '__main__':
    print(build())
    m, d = load()
    print(f'Compiled: nq={m.nq}, nv={m.nv}, geoms={m.ngeom}, robot mass={m.body_subtreemass[m.body("chassis").id]:.4f} kg')
