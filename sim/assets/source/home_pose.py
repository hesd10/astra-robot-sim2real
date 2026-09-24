"""The robot's home pose: arms folded where they can reach the call buttons.

Pose tables in this file are the only numeric source. POLICY_ZERO is
the XML qpos at VLA 0° (pans ±pi/2, lift/elbow pi/2, wrists 0, head
pan=pi / tilt=HEAD_TILT_DEG). HOME is the folded press start.
"""
import os

import numpy as np

PI = np.pi
HEAD_TILT_DEG = float(os.environ.get("ELEVATOR_HEAD_TILT_DEG", "0"))

HOME = {
    "Rotation_L": -PI / 2,
    "Pitch_L": PI,
    "Elbow_L": PI / 2,
    "Wrist_Pitch_L": PI / 2,
    "Wrist_Roll_L": PI / 2,
    "Jaw_L": "jaw_min",
    "Rotation_R": PI / 2,
    "Pitch_R": PI,
    "Elbow_R": 2.6,
    "Wrist_Pitch_R": PI / 2,
    "Wrist_Roll_R": PI / 2,
    "Jaw_R": "jaw_min",
}

HEAD = {
    "head_pan_joint": PI,
    "head_tilt_joint": PI * HEAD_TILT_DEG / 180.0,
}

POLICY_ZERO = {
    "Rotation_L": -PI / 2,
    "Pitch_L": PI / 2,
    "Elbow_L": PI / 2,
    "Wrist_Pitch_L": 0.0,
    "Wrist_Roll_L": 0.0,
    "Rotation_R": PI / 2,
    "Pitch_R": PI / 2,
    "Elbow_R": PI / 2,
    "Wrist_Pitch_R": 0.0,
    "Wrist_Roll_R": 0.0,
}
POLICY_ZERO.update(HEAD)

JITTER_JOINTS = tuple(n for n in HOME if not n.startswith("Jaw"))


def _set_joint(model, data, name, val):
    import mujoco
    jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
    data.qpos[model.jnt_qposadr[jid]] = val
    aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, "act_%s" % name)
    if aid >= 0:
        data.ctrl[aid] = val


def resolve(model):
    import mujoco
    out = {}
    for name, want in HOME.items():
        jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
        if jid < 0:
            raise RuntimeError("joint %s not in model" % name)
        lo, hi = model.jnt_range[jid]
        val = lo if want == "jaw_min" else float(want)
        if model.jnt_limited[jid] and not (lo - 1e-9 <= val <= hi + 1e-9):
            raise RuntimeError(
                "%s=%s outside range [%s, %s]" % (name, val, lo, hi))
        out[name] = val
    return out


def apply(model, data, head=True):
    import mujoco
    mujoco.mj_forward(model, data)
    pose = resolve(model)
    if head:
        pose.update(HEAD)
    for name, val in pose.items():
        _set_joint(model, data, name, val)
    mujoco.mj_forward(model, data)
    return pose


def apply_arm_jitter(model, data, rng, max_deg=5.0):
    import mujoco
    max_rad = float(np.radians(max_deg))
    applied = {}
    for name in JITTER_JOINTS:
        jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
        adr = model.jnt_qposadr[jid]
        lo, hi = model.jnt_range[jid]
        base = float(data.qpos[adr])
        val = float(np.clip(base + rng.uniform(-max_rad, max_rad), lo, hi))
        data.qpos[adr] = val
        aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, "act_%s" % name)
        if aid >= 0:
            data.ctrl[aid] = val
        applied[name] = val - base
    mujoco.mj_forward(model, data)
    return applied


def apply_head(model, data, tilt=None):
    import mujoco
    pose = dict(HEAD)
    if tilt is not None:
        pose["head_tilt_joint"] = float(tilt)
    for name, val in pose.items():
        _set_joint(model, data, name, val)
    mujoco.mj_forward(model, data)
    return pose
