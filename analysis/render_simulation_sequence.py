"""Render six archived task states; never step physics or access hardware."""
from pathlib import Path
import hashlib
import json
import os

os.environ.setdefault("MUJOCO_GL", "egl")
import mujoco
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results/simulation-sequence-snapshots.json"
records = json.loads(SOURCE.read_text())
model_path = ROOT / records["model"]
assert hashlib.sha256(model_path.read_bytes()).hexdigest() == records["model_sha256"]
m = mujoco.MjModel.from_xml_path(str(model_path))
d = mujoco.MjData(m)
m.vis.global_.offwidth = 1200
m.vis.global_.offheight = 1000
m.vis.global_.fovy = 42
m.vis.quality.shadowsize = 2048
m.vis.quality.offsamples = 4


def render(path, lookat, distance, azimuth, elevation, width=1200, height=1000):
    cam = mujoco.MjvCamera()
    cam.lookat[:] = lookat
    cam.distance, cam.azimuth, cam.elevation = distance, azimuth, elevation
    with mujoco.Renderer(m, height=height, width=width) as renderer:
        renderer.update_scene(d, camera=cam)
        renderer.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION] = False
        Image.fromarray(renderer.render()).save(path)
        eye = np.mean([c.pos for c in renderer.scene.camera], axis=0)
        forward = np.mean([c.forward for c in renderer.scene.camera], axis=0)
        up = np.mean([c.up for c in renderer.scene.camera], axis=0)
        right = np.cross(forward, up)
        delta = d.body("button_2_up").xpos - eye
        focal = height / (2 * np.tan(np.deg2rad(m.vis.global_.fovy) / 2))
        scale = focal / np.dot(delta, forward)
        target_pixel = [float(width / 2 + scale * np.dot(delta, right)),
                        float(height / 2 - scale * np.dot(delta, up))]
    return dict(path=str(path.relative_to(ROOT)),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                lookat=lookat, distance=distance, azimuth=azimuth, elevation=elevation,
                size_px=[width, height], target_pixel=target_pixel)


images = []
for i, row in enumerate(records["snapshots"]):
    d.qpos[:] = row["qpos"]
    m.geom_rgba[:] = row["rgba"]
    m.geom_rgba[m.geom("wall_front").id, 3] = 0
    mujoco.mj_forward(m, d)
    image = render(ROOT / "media" / f"simulation-sequence-{i + 1}.png",
                   [6.95, 2.65, .50], 4.4, 135, -34)
    image.update(time_seconds=row["time_seconds"], archive_line=row["archive_line"])
    if i >= 4:
        image["inset"] = render(ROOT / "media" / f"simulation-sequence-{i + 1}-detail.png",
                                [6.853, 3.965, 1.015], .30, 125, -8, 650, 520)
    images.append(image)

(ROOT / "results/simulation-sequence-provenance.json").write_text(json.dumps(dict(
    renderer=f"MuJoCo {mujoco.__version__}", episode=records["episode"],
    snapshots=str(SOURCE.relative_to(ROOT)),
    snapshots_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    simulation_advanced=False, vertical_fov_degrees=42,
    presentation="Six recorded configurations, one fixed external camera focused on the middle elevator and approach corridor; near wall hidden in memory, reflections disabled. Last two frames include a separate fixed close view of the button and gripper.",
    images=images), indent=2) + "\n")
print("Rendered six archived states and two contact details without advancing simulation.")
