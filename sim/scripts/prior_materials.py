"""Operator-only construction of orthogonal robot/initial-target information."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mujoco
import numpy as np
from sim_env.model import CHANNELS, CAMERAS, OUTPUT

GROUPS = {'A': (False, False), 'B': (True, False),
          'C': (False, True), 'D': (True, True)}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hashes(folder):
    return {str(p.relative_to(folder)): digest(p) for p in sorted(Path(folder).rglob('*')) if p.is_file()}


def initial_target(m, d):
    """Outward face center and normal, relative to the settled initial chassis."""
    base = d.body('chassis')
    cap = d.geom('button_2_up_geom')
    rotation = base.xmat.reshape(3, 3)
    face_normal_world = cap.xmat.reshape(3, 3) @ np.array([0., -1., 0.])
    center_world = cap.xpos + face_normal_world * m.geom('button_2_up_geom').size[1]
    return {
        'target': 'middle elevator UP call button',
        'frame': 'initial chassis frame; +X forward, +Y left, +Z up',
        'origin': 'chassis body-frame origin, not the floor projection or a hand',
        'length_unit': 'metre',
        'capture_sim_seconds': float(d.time),
        'reference_time': 'after initial settling, before the realtime task clock starts',
        'button_face_center_m': (rotation.T @ (center_world-base.xpos)).tolist(),
        'button_outward_unit_normal': (rotation.T @ face_normal_world).tolist(),
        'update_policy': 'one initial measurement only; coordinates remain in the initial frame',
    }


def export_robot(destination):
    """Whitelist the chassis subtree and its dependencies; never export the lobby."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    original = ET.parse(OUTPUT).getroot()
    root = ET.Element('mujoco', model='robot_description')
    compiler = copy.deepcopy(original.find('compiler'))
    compiler.set('meshdir', 'meshes')
    compiler.attrib.pop('texturedir', None)
    root.append(compiler)
    root.append(copy.deepcopy(original.find('option')))
    chassis = copy.deepcopy(original.find("worldbody/body[@name='chassis']"))
    chassis.set('pos', '0 0 0')
    chassis.set('quat', '1 0 0 0')
    names = {node.get('name') for node in chassis.iter() if node.get('name')}
    assert all(node.get('class') is None and node.get('childclass') is None for node in chassis.iter())
    assert all(node.get('material') is None for node in chassis.iter())
    required_meshes = {node.get('mesh') for node in chassis.iter() if node.get('mesh')}
    asset = ET.SubElement(root, 'asset')
    meshdir = destination/'meshes'
    meshdir.mkdir()
    source_meshdir = (OUTPUT.parent/original.find('compiler').get('meshdir')).resolve()
    for source in original.findall('asset/mesh'):
        if source.get('name') not in required_meshes:
            continue
        node = copy.deepcopy(source)
        filename = Path(source.get('file')).name
        node.set('file', filename)
        asset.append(node)
        shutil.copyfile(source_meshdir/source.get('file'), meshdir/filename)
    assert {node.get('name') for node in asset} == required_meshes
    contact = ET.SubElement(root, 'contact')
    for node in original.findall('contact/exclude'):
        if node.get('body1') in names and node.get('body2') in names:
            contact.append(copy.deepcopy(node))
    ET.SubElement(root, 'worldbody').append(chassis)
    actuator = ET.SubElement(root, 'actuator')
    for node in original.findall('actuator/*'):
        if node.get('joint') in names:
            actuator.append(copy.deepcopy(node))
    ET.indent(root, space='  ')
    ET.ElementTree(root).write(destination/'robot.xml', encoding='unicode')
    write_json(destination/'interface_mapping.json', {
        'joint_channels_to_xml_joint_names': CHANNELS,
        'camera_roles_to_xml_camera_names': CAMERAS,
        'angle_unit': 'radian',
        'joint_readback_to_xml_qpos': 'identity: same sign and zero reference; no added offset',
        'base_frame': 'chassis; +X forward, +Y left, +Z up',
        'root_pose_in_xml': 'identity reference convention, not a supplied world pose',
        'command_surface': 'Only channels in API.md are directly controllable; wheel joints are internal.',
    })
    (destination/'README.md').write_text('''# Robot description

robot.xml and meshes/ describe this robot relative to its chassis frame.
interface_mapping.json maps public channels and camera names to the description.
The root pose is a reference convention, not the robot's pose in the task scene.
The model contains no task scene, target, initial encoder values or action plan.
Current joint states and enforced command bounds come from the shared robot API.
XML angles are radians; API joint positions use the same joint sign and zero.
Only the low-level API controls the actual robot. This description is data;
you may interpret it using the installed dependencies and code you write.
''')
    return mujoco.MjModel.from_xml_path(str(destination/'robot.xml'))


def common_files(destination):
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(ROOT/'subject_template/robot.py', destination/'robot.py')
    api = (ROOT/'subject_template/API.md').read_text()
    start = api.index('Use a fresh workspace/conversation.')
    stop = api.index('Task completion requires', start)
    api = api[:start]+'''Use a fresh workspace/conversation. Read PRIOR.md for the information supplied
for this attempt. Files explicitly listed there are authorized task inputs,
including a robot description or initial target measurement when present.
Unprovided model assets, scene internals, previous workspaces/conversations,
external controllers, demonstrations, policies and hidden evaluation remain
unavailable. You may infer relationships and write controllers from authorized
inputs and current-run observations. Do not reset or bypass protections.
On contamination, stop safely and finish with outcome contamination.

This attempt starts without a skill. No skill, controller, calibration, evidence
or conversation from another attempt is available or transferred onward.
There is no required exploration phase; choose your own observation and action
strategy. All reading, programming, exploration, observations and recovery use
the same task budget. Do not create a cross-run skill. After finish, write a
brief evidence report; report generation and video export are outside task time.
The chassis frame is the robot base frame: +X forward, +Y left, +Z up. An initial
target measurement, if supplied, refers to the chassis origin before motion,
not a floor-projected origin or a hand, and is never updated during the attempt.

'''+api[stop:]
    (destination/'API.md').write_text(api)
    (destination/'PROMPT.md').write_text('''Physically control XLeRobot to approach the middle elevator and press only its UP call button. Verify from fresh observations that the target button has turned red before declaring success. Work alone without questions; minimize time and online decisions without damage.

Read API.md and PRIOR.md. Use the shared low-level interface, the explicitly supplied information, installed dependencies and code you write. Choose your observation and action strategy freely; there is no required exploration phase. Keep head pan within ±90 degrees of its fresh initial orientation and use the permitted tilt range.

No previous conversations, workspaces, skills, evidence, prior Git history, external controllers/information, unprovided simulation internals/assets, datasets, demonstrations, pretrained policies or hidden evaluation. Stop on contamination or unavailable essential capabilities. Never bypass protections or reset; the whole session is one attempt.

On termination, stop safely and call finish. Then save a brief report in evidence/ describing outcome, fresh visual verification, final state, elapsed time, motion commands and decision points. Do not produce a skill for another attempt.
''')


def prepare_subject(destination, input_dir, expected):
    destination, input_dir = Path(destination), Path(input_dir)
    if hashes(input_dir) != expected:
        raise RuntimeError('Assigned prior input changed')
    shutil.copytree(input_dir, destination)
    write_json(destination/'infrastructure.json', expected)
    subprocess.run(['git', 'init', '-q', str(destination)], check=True)
    (destination/'.gitconfig').write_text('[safe]\n\tdirectory = '+str(destination.resolve())+'\n')
    git = ['git', '--git-dir='+str(destination/'.git'), '--work-tree='+str(destination)]
    for key, value in [('user.name', 'Astra experiment'), ('user.email', 'experiment@localhost')]:
        subprocess.run(git+['config', key, value], check=True)
    subprocess.run(git+['add', '.'], check=True)
    subprocess.run(git+['commit', '-qm', 'Initialize shared interface and assigned prior information'], check=True)
    return destination
