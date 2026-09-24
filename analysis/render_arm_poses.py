"""Render recorded arm configurations, without stepping physics or using hardware."""
from pathlib import Path
import hashlib
import json
import os

os.environ.setdefault("MUJOCO_GL", "egl")
import mujoco
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results/arm-pose-snapshots.json"
records = json.loads(SOURCE.read_text())
model_path = ROOT / records["model"]
assert hashlib.sha256(model_path.read_bytes()).hexdigest() == records["model_sha256"]
m = mujoco.MjModel.from_xml_path(str(model_path))
d = mujoco.MjData(m)
m.vis.global_.offwidth = 1000
m.vis.global_.offheight = 1000
m.vis.global_.fovy = 40
m.vis.quality.shadowsize = 2048
m.vis.quality.offsamples = 4
images = []
for row in records["snapshots"]:
    d.qpos[:] = row["qpos"]
    m.geom_rgba[:] = row["rgba"]
    m.geom_rgba[m.geom("wall_front").id, 3] = 0
    mujoco.mj_forward(m, d)
    yaw = np.degrees(np.arctan2(d.body("chassis").xmat.reshape(3, 3)[1, 0],
                                d.body("chassis").xmat.reshape(3, 3)[0, 0]))
    cam = mujoco.MjvCamera()
    cam.lookat[:] = d.body("chassis").xpos + [0, 0, .55]
    cam.distance, cam.azimuth, cam.elevation = 1.35, yaw + 80, -12
    with mujoco.Renderer(m, height=1000, width=1000) as renderer:
        renderer.update_scene(d, camera=cam)
        renderer.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION] = False
        path = ROOT / "media" / f"arm-pose-{row['label']}.png"
        Image.fromarray(renderer.render()).save(path)
        eye = np.mean([c.pos for c in renderer.scene.camera], axis=0)
        forward = np.mean([c.forward for c in renderer.scene.camera], axis=0)
        up = np.mean([c.up for c in renderer.scene.camera], axis=0)
        right = np.cross(forward, up)
        def project(point):
            delta = np.asarray(point) - eye
            scale = 500 / np.tan(np.deg2rad(20)) / np.dot(delta, forward)
            return [float(500 + scale * np.dot(delta, right)),
                    float(500 - scale * np.dot(delta, up))]
        images.append(dict(label=row["label"], episode=row["episode"],
                           time_seconds=row["time_seconds"],
                           path=str(path.relative_to(ROOT)),
                           sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                           lookat=cam.lookat.tolist(), distance=cam.distance,
                           azimuth=cam.azimuth, elevation=cam.elevation,
                           right_gripper_pixel=project(d.body("Fixed_Jaw_2").xpos)))
(ROOT / "results/arm-pose-provenance.json").write_text(json.dumps(dict(
    renderer=f"MuJoCo {mujoco.__version__}", snapshots=str(SOURCE.relative_to(ROOT)),
    snapshots_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    simulation_advanced=False, vertical_fov_degrees=40,
    presentation="Recorded configurations rendered from the same robot-relative external camera; near wall hidden in memory, reflections disabled.",
    images=images), indent=2) + "\n")
print("Rendered three recorded arm poses; no simulation stepping or hardware access.")
