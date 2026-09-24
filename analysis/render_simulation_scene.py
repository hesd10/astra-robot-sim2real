"""Render the saved simulation start and target panel for the manuscript.

Run in the simulation Python environment. This uses mj_forward only and never
launches an agent or opens hardware. The near wall is hidden in memory for the
external presentation camera; model files and recorded states stay unchanged.
"""
from pathlib import Path
import hashlib
import json
import os

os.environ.setdefault("MUJOCO_GL", "egl")
import mujoco
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "sim/models/elevator_four_mecanum.xml"
STATE = ROOT / "sim/studies/body-experience-001/private-initial-reference.json"
m = mujoco.MjModel.from_xml_path(str(MODEL))
d = mujoco.MjData(m)
d.qpos[:] = json.loads(STATE.read_text())["qpos"]
mujoco.mj_forward(m, d)
m.vis.global_.offwidth = 1800
m.vis.global_.offheight = 1000
m.vis.global_.fovy = 45
m.vis.quality.shadowsize = 2048
m.vis.quality.offsamples = 4
m.geom_rgba[m.geom("wall_front").id, 3] = 0


def render(name, width, height, lookat, distance, azimuth, elevation):
    cam = mujoco.MjvCamera()
    cam.lookat[:] = lookat
    cam.distance, cam.azimuth, cam.elevation = distance, azimuth, elevation
    with mujoco.Renderer(m, height=height, width=width) as renderer:
        renderer.update_scene(d, camera=cam)
        renderer.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION] = False
        path = ROOT / "media" / name
        Image.fromarray(renderer.render()).save(path)
        cameras = renderer.scene.camera
        eye = np.mean([c.pos for c in cameras], axis=0)
        forward = np.mean([c.forward for c in cameras], axis=0)
        up = np.mean([c.up for c in cameras], axis=0)
        right = np.cross(forward, up)
        focal = height / (2 * np.tan(np.deg2rad(m.vis.global_.fovy) / 2))

        def project(point):
            delta = np.asarray(point) - eye
            depth = np.dot(delta, forward)
            return [float(width / 2 + focal * np.dot(delta, right) / depth),
                    float(height / 2 - focal * np.dot(delta, up) / depth)]

        return {"path": str(path.relative_to(ROOT)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_px": [width, height], "lookat": lookat,
                "distance": distance, "azimuth": azimuth, "elevation": elevation,
                "target_pixel": project(d.body("button_2_up").xpos),
                "robot_pixel": project(d.body("chassis").xpos + [0, 0, .3])}


images = [
    render("simulation-lobby-start.png", 1800, 1000, [6.1, 2.6, 1.0], 5.8, 90, -18),
    render("simulation-target-panel.png", 520, 1000, [6.8525, 3.989, 1.005], .17, 90, 0),
]
manifest = {
    "figure": "simulation-scene", "renderer": f"MuJoCo {mujoco.__version__}",
    "model": str(MODEL.relative_to(ROOT)),
    "model_sha256": hashlib.sha256(MODEL.read_bytes()).hexdigest(),
    "state": str(STATE.relative_to(ROOT)),
    "state_sha256": hashlib.sha256(STATE.read_bytes()).hexdigest(),
    "state_description": "Saved original starting state after settling",
    "simulation_advanced": False,
    "presentation": "External cutaway: near wall hidden in memory, reflections disabled; labels added to the manuscript figure only",
    "vertical_fov_degrees": 45, "images": images,
}
(ROOT / "results/simulation-scene-provenance.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("Saved scene renders and provenance; no trial inputs changed.")
