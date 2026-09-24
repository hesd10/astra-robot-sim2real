"""Private model adapter and public channel mapping."""
import sys
from pathlib import Path
import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from wheel_contact_model import load, command, OUTPUT, SOURCE
sys.path.insert(0, str(SOURCE))
from button_panel import ButtonPanel

CHANNELS = {}
for side, suffix in [('left', 'R'), ('right', 'L')]:
    for i, name in enumerate(('Rotation', 'Pitch', 'Elbow', 'Wrist_Pitch', 'Wrist_Roll', 'Jaw'), 1):
        CHANNELS[f'{side}_{i}'] = f'{name}_{suffix}'
CHANNELS.update(head_1='head_pan_joint', head_2='head_tilt_joint')
CAMERAS = {'head': 'head', 'left_wrist': 'right_wrist', 'right_wrist': 'left_wrist'}
STATE_SPEC = mujoco.mjtState.mjSTATE_INTEGRATION


def prepare(standoff=.9, lateral=0., yaw=0.):
    m, d = load()
    q = m.joint('base_free').qposadr[0]
    # Private initialization only. Body +X faces the button wall.
    angle = np.pi / 2 + yaw
    x = float(d.body('button_2_up').xpos[0]) + lateral
    d.qpos[q:q+7] = [x, 4.-standoff, .375, np.cos(angle/2), 0, 0, np.sin(angle/2)]
    mujoco.mj_forward(m, d)
    for _ in range(2000):
        mujoco.mj_step(m, d)
    d.time = 0.
    return m, d, ButtonPanel(m)


def snapshot(m, d):
    state = np.empty(mujoco.mj_stateSize(m, STATE_SPEC))
    mujoco.mj_getState(m, d, state, STATE_SPEC)
    return {'sim_time': float(d.time), 'state': state,
            'rgba': m.geom_rgba.copy()}


def restore(m, d, row):
    mujoco.mj_setState(m, d, np.asarray(row['state']), STATE_SPEC)
    m.geom_rgba[:] = row['rgba']
    mujoco.mj_forward(m, d)
