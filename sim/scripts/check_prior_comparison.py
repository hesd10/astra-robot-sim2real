"""Check information separation and FK/camera parity; never call a real model."""
import json
from pathlib import Path
import sys
import tempfile
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mujoco
import numpy as np
from prior_materials import GROUPS, CHANNELS, CAMERAS, export_robot, hashes, common_files, initial_target
from sim_env.core import Core
from sim_env.setup import load_setup
from prior_service import verify_initial


def check_geometry():
    core = Core(**load_setup(ROOT/'setups/formal-001.json')['parameters'], max_seconds=1800.)
    full, fd = core.m, core.d
    with tempfile.TemporaryDirectory(prefix='prior-geometry-') as temp:
        folder = Path(temp)/'robot'
        robot = export_robot(folder)
        rd = mujoco.MjData(robot)
        tree = ET.parse(folder/'robot.xml').getroot()
        assert {n.tag for n in tree} == {'compiler', 'option', 'asset', 'contact', 'worldbody', 'actuator'}
        assert len(tree.find('worldbody')) == 1
        assert tree.find('worldbody/body').get('name') == 'chassis'
        assert tree.find('worldbody/body').get('pos') == '0 0 0'
        assert not any(n.tag in ('include', 'keyframe', 'custom', 'text', 'numeric') for n in tree.iter())
        assert not any(word in (folder/'robot.xml').read_text().lower() for word in ('elevator', 'button', 'panel', 'door', 'floor'))
        for asset in tree.findall('asset/*'):
            assert asset.tag == 'mesh'
            assert Path(asset.get('file')).name == asset.get('file')
            assert (folder/'meshes'/asset.get('file')).is_file()
        mapping = json.loads((folder/'interface_mapping.json').read_text())
        assert mapping['joint_channels_to_xml_joint_names'] == CHANNELS
        assert mapping['camera_roles_to_xml_camera_names'] == CAMERAS
        robot_bodies = {robot.body(i).name for i in range(1, robot.nbody)}
        assert robot_bodies == {full.body(i).name for i in core.robot_bodies}
        expected_geoms = [i for i in range(full.ngeom) if full.body(int(full.geom_bodyid[i])).name in robot_bodies]
        assert len(expected_geoms) == robot.ngeom
        rng = np.random.default_rng(920)
        maximum_error = 0.
        for trial in range(8):
            if trial:
                for public, name in CHANNELS.items():
                    j = full.joint(name)
                    lo, hi = j.range if j.limited[0] else (-2., 2.)
                    fd.qpos[j.qposadr[0]] = rng.uniform(lo, hi)
            for jid in range(robot.njnt):
                name = robot.joint(jid).name
                if name == 'base_free':
                    adr = robot.joint(name).qposadr[0]
                    rd.qpos[adr:adr+7] = [0, 0, 0, 1, 0, 0, 0]
                else:
                    rd.qpos[robot.joint(name).qposadr[0]] = fd.qpos[full.joint(name).qposadr[0]]
            mujoco.mj_forward(full, fd)
            mujoco.mj_forward(robot, rd)
            rotation = fd.body('chassis').xmat.reshape(3, 3)
            translation = fd.body('chassis').xpos
            for gid, full_gid in enumerate(expected_geoms):
                np.testing.assert_allclose(robot.geom_size[gid], full.geom_size[full_gid], atol=1e-10, rtol=0)
                expected = rotation.T @ (fd.geom_xpos[full_gid]-translation)
                maximum_error = max(maximum_error, float(np.max(np.abs(rd.geom_xpos[gid]-expected))))
                np.testing.assert_allclose(rd.geom_xpos[gid], expected, atol=1e-8, rtol=0)
                np.testing.assert_allclose(rd.geom_xmat[gid].reshape(3, 3),
                    rotation.T @ fd.geom_xmat[full_gid].reshape(3, 3), atol=1e-8, rtol=0)
            for name in CAMERAS.values():
                fid, rid = full.camera(name).id, robot.camera(name).id
                np.testing.assert_allclose(rd.cam_xpos[rid], rotation.T@(fd.cam_xpos[fid]-translation), atol=1e-8, rtol=0)
                np.testing.assert_allclose(rd.cam_xmat[rid].reshape(3,3), rotation.T@fd.cam_xmat[fid].reshape(3,3), atol=1e-8, rtol=0)
        return {'poses_checked': 8, 'robot_geoms_checked_per_pose': robot.ngeom,
                'cameras_checked_per_pose': robot.ncam, 'maximum_position_error_m': maximum_error}


def check_frozen():
    from run_prior_comparison import STUDY, validate
    manifest = validate()
    variants = manifest['variants']
    for filename in ('PROMPT.md', 'API.md', 'robot.py'):
        assert len({(ROOT/v['input_dir']/filename).read_bytes() for v in variants.values()}) == 1
    assert (STUDY/'inputs/A/robot.py').read_bytes() == (ROOT/'subject_template/robot.py').read_bytes()
    for group, (self_known, target_known) in GROUPS.items():
        directory = STUDY/'inputs'/group
        assert (directory/'prior/robot').exists() == self_known
        assert (directory/'prior/initial_target.json').exists() == target_known
        assert not (directory/'skill').exists()
        assert not any(p.is_symlink() for p in directory.rglob('*'))
        if self_known:
            assert hashes(directory/'prior/robot') == hashes(STUDY/'robot-description')
    assert (STUDY/'inputs/C/prior/initial_target.json').read_bytes() == (STUDY/'inputs/D/prior/initial_target.json').read_bytes()
    core = Core(**load_setup(ROOT/'setups/formal-001.json')['parameters'], max_seconds=1800.)
    verification = verify_initial(core, STUDY/'private-initial-reference.json')
    initial = initial_target(core.m, core.d)
    assert initial == json.loads((STUDY/'inputs/C/prior/initial_target.json').read_text())
    core.d.qpos[core.m.joint('base_free').qposadr[0]] += .01
    try:
        verify_initial(core, STUDY/'private-initial-reference.json')
    except AssertionError:
        pass
    else:
        raise AssertionError('Initial-state mismatch was not rejected')
    # No privileged localization was added to the shared API/schema/state.
    assert set(core.status()) == {'sim_time','sample_monotonic','joints','health','fault','finished','motion_active','base_command'}
    for block in manifest['planned_blocks']:
        assert {label[0] for label in block} == set(GROUPS) and len(block) == 4
    assert all(len({block.index(next(x for x in block if x[0] == g)) for block in manifest['planned_blocks']}) == 3 for g in GROUPS)
    return {'orthogonal_inputs': True, 'shared_prompt_api_transport': True,
            'initial_pose_verified': verification['passed'], 'incorrect_pose_rejected': True,
            'no_live_localization': True, 'no_skill_inheritance': True,
            'blocks': manifest['planned_blocks']}


if __name__ == '__main__':
    result = {'geometry': check_geometry(), 'real_model_called': False}
    if '--geometry-only' not in sys.argv:
        result['frozen'] = check_frozen()
    print(json.dumps(result, indent=2))
