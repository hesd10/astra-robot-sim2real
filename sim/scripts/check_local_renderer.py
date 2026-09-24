"""Operator-only local GPU identification and render smoke test; no model calls."""
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('MUJOCO_GL', 'egl')

import mujoco
from OpenGL import GL
from sim_env.core import Core
from sim_env.model import CAMERAS


def main():
    core = Core()
    core.m.vis.quality.shadowsize = 1024
    core.m.vis.quality.offsamples = 2
    with mujoco.Renderer(core.m, height=480, width=640) as renderer:
        graphics = {
            name: GL.glGetString(enum).decode()
            for name, enum in [('vendor', GL.GL_VENDOR), ('renderer', GL.GL_RENDERER),
                               ('version', GL.GL_VERSION)]
        }
        frames = {}
        for role, camera in CAMERAS.items():
            started = time.monotonic()
            renderer.update_scene(core.d, camera=camera)
            renderer.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION] = False
            pixels = renderer.render()
            assert pixels.shape == (480, 640, 3) and pixels.std() > 1, role
            frames[role] = {'shape': list(pixels.shape),
                            'render_seconds': time.monotonic() - started}
    report = {
        'python': sys.version, 'executable': sys.executable, 'platform': platform.platform(),
        'packages': {name: importlib.metadata.version(name)
                     for name in ['mujoco', 'numpy', 'Pillow', 'PyOpenGL', 'imageio-ffmpeg']},
        'backend': os.environ.get('MUJOCO_GL'),
        'egl_device_id': os.environ.get('MUJOCO_EGL_DEVICE_ID'),
        'graphics': graphics, 'frames': frames, 'real_model_called': False,
    }
    out = ROOT / 'reports' / 'local' / 'renderer.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
