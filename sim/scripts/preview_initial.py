"""Operator-only initial state preview; never invokes a model or reads saved images."""
import argparse
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def scene_metrics(core, setup_record):
    import numpy as np
    from sim_env.model import OUTPUT
    m, d = core.m, core.d
    base = d.body('chassis').xpos
    button = d.body('button_2_up').xpos
    head = m.camera('head').id
    camera_position = d.cam_xpos[head]
    camera_rotation = d.cam_xmat[head].reshape(3, 3)
    heading = math.atan2(d.body('chassis').xmat.reshape(3, 3)[1, 0],
                         d.body('chassis').xmat.reshape(3, 3)[0, 0])
    bearing = math.atan2(button[1]-base[1], button[0]-base[0])
    panel = m.geom('panel_2').id
    corners = np.array(list(itertools.product([-1, 1], repeat=3)))*m.geom_size[panel]
    world = corners@d.geom_xmat[panel].reshape(3, 3).T+d.geom_xpos[panel]
    local = (world-camera_position)@camera_rotation
    focal = 480/(2*math.tan(math.radians(m.cam_fovy[head])/2))
    uv = np.column_stack([320+focal*local[:, 0]/-local[:, 2],
                          240-focal*local[:, 1]/-local[:, 2]])
    return {'setup': setup_record, 'model_sha256': hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
            'chassis_xyz_m': base.tolist(), 'target_button_xyz_m': button.tolist(),
            'head_camera_xyz_m': camera_position.tolist(),
            'base_to_button_horizontal_m': float(np.linalg.norm((button-base)[:2])),
            'base_to_button_3d_m': float(np.linalg.norm(button-base)),
            'head_to_button_3d_m': float(np.linalg.norm(button-camera_position)),
            'lateral_offset_m': float(base[0]-button[0]),
            'chassis_heading_deg': math.degrees(heading),
            'heading_offset_from_button_deg': math.degrees(math.atan2(math.sin(bearing-heading), math.cos(bearing-heading))),
            'head_panel_projection_640x480': {'min_xy': uv.min(axis=0).tolist(),
                'max_xy': uv.max(axis=0).tolist(),
                'fully_in_frame': bool((local[:, 2] < 0).all() and (uv >= 0).all() and
                                       (uv[:, 0] < 640).all() and (uv[:, 1] < 480).all())},
            'initial_qpos_sha256': hashlib.sha256(d.qpos.tobytes()).hexdigest(),
            'onboard_image_size': [640, 480], 'third_person_image_size': [960, 720],
            'model_called': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--gui', action='store_true', help='Interactive local viewer; close to exit')
    parser.add_argument('--output', default='preview')
    parser.add_argument('--setup', help='private starting-pose JSON, shared with start_experiment.py')
    args = parser.parse_args()
    if not args.gui:
        os.environ.setdefault('MUJOCO_GL', 'egl')
    os.environ.setdefault('LP_NUM_THREADS', '2')
    import mujoco
    from sim_env.core import Core
    from sim_env.model import CAMERAS
    from sim_env.rendering import follow_camera
    from sim_env.setup import load_setup
    setup_record = load_setup(args.setup) if args.setup else None
    c = Core(**(setup_record['parameters'] if setup_record else {}))
    camera = follow_camera(c.m, c.d)
    camera.lookat[:] = (c.d.body('chassis').xpos+c.d.body('button_2_up').xpos)/2
    camera.lookat[2] = .85
    camera.distance, camera.azimuth, camera.elevation = 3.3, 45, -18
    if c.d.body('button_2_up').xpos[1]-c.d.body('chassis').xpos[1] > 1.5:
        # The hall is only 4 m deep: a distant 45-degree camera crosses the front wall.
        camera.lookat[2] = .9
        camera.distance, camera.azimuth, camera.elevation = 4.8, 25, -24
    if args.gui:
        import time
        import mujoco.viewer
        with mujoco.viewer.launch_passive(c.m, c.d) as viewer:
            viewer.cam.lookat[:] = camera.lookat
            viewer.cam.distance = camera.distance
            viewer.cam.azimuth = camera.azimuth
            viewer.cam.elevation = camera.elevation
            while viewer.is_running():
                # Freeze physics so the exact initial configuration can be inspected.
                viewer.sync()
                time.sleep(.03)
        return
    from PIL import Image
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    c.m.vis.quality.shadowsize = 1024
    c.m.vis.quality.offsamples = 2
    with mujoco.Renderer(c.m, height=720, width=960) as renderer:
        for name, view in {'overview': camera, 'follow': follow_camera(c.m, c.d)}.items():
            renderer.update_scene(c.d, camera=view)
            renderer.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION] = False
            Image.fromarray(renderer.render()).save(out/(name+'.png'))
    # Match the actual observation resolution, rather than previewing extra detail.
    with mujoco.Renderer(c.m, height=480, width=640) as renderer:
        for name, view in CAMERAS.items():
            renderer.update_scene(c.d, camera=view)
            renderer.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION] = False
            Image.fromarray(renderer.render()).save(out/(name+'.png'))
    (out/'state.json').write_text(json.dumps(c.status(), indent=2)+'\n')
    metrics = scene_metrics(c, setup_record)
    metrics['overview_camera'] = {'lookat': camera.lookat.tolist(), 'distance': camera.distance,
                                  'azimuth': camera.azimuth, 'elevation': camera.elevation}
    (out/'setup.json').write_text(json.dumps(metrics, indent=2)+'\n')
    print('Initial preview saved to', out.resolve(), '(no model called)')


if __name__ == '__main__':
    main()
