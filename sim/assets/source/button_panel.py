"""Call-button state for the elevator lobby.

The button caps are sprung slide joints, so pressing one is a real physical
interaction: a robot finger pushes the cap in, and the spring returns it. The
cap springing back does NOT clear the call, though -- like a real elevator, the
lamp latches until the car actually arrives and something calls `clear()`.

Each cap carries a thin glowing square outline (four bars) plus a dark chevron
engraving. Only the outline changes colour -- cyan when idle, red once called,
matching the reference photos; the chevron stays dark throughout. MuJoCo has no
per-geom light, so the outline is emissive geometry whose colour is overwritten
at runtime through `model.geom_rgba`.

Typical use:

    panel = ButtonPanel(model)
    ...
    while running:
        mujoco.mj_step(model, data)
        panel.update(model, data)          # latches presses, updates colours
        if panel.consume_press(2, "up"):   # fires once per press
            start_opening_door(2)
        ...
        panel.clear(model, elevator=2)     # car arrived -> lamp back to cyan
"""
import mujoco
import numpy as np

# Lamp colours. The targets are what the reference photos measure:
#   idle   rgb(162, 221, 246)  cyan
#   called rgb(249,   6,  12)  red
# The rgba values below are deliberately deeper than those targets. MuJoCo adds
# an ambient/emissive term and clamps, so feeding the photographed cyan straight
# in saturates every channel and renders pure white. These values land on the
# photographed colour after that clipping (verified by _verify_lamp_colour.py).
COLOUR_IDLE = np.array([0.55, 1.0, 1.0, 1.0])
COLOUR_CALLED = np.array([0.976, 0.024, 0.047, 1.0])

# Cap travel is 0..2.5 mm. The switch trips at 1.5 mm (60% of travel, ~2.3 N of
# spring force), matching a real button where you must push well past initial
# contact before it registers.
PRESS_TRIP = 0.0015

ELEVATORS = (1, 2, 3)
DIRECTIONS = ("up", "down")


class ButtonPanel:
    """Tracks latched call state and halo colour for all call buttons."""

    def __init__(self, model):
        self._jnt = {}
        self._glow = {}
        for idx in ELEVATORS:
            for direction in DIRECTIONS:
                key = (idx, direction)
                jid = mujoco.mj_name2id(
                    model, mujoco.mjtObj.mjOBJ_JOINT, f"btn_{idx}_{direction}")
                if jid < 0:
                    raise RuntimeError(f"button {key} missing from model")
                self._jnt[key] = model.jnt_qposadr[jid]

                # Only the four ring bars change colour. The chevron engraving
                # stays dark in both reference photos, so it is not touched.
                names = [f"ring_{idx}_{direction}_{side}"
                         for side in ("top", "bottom", "left", "right")]
                gids = []
                for n in names:
                    g = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, n)
                    if g < 0:
                        raise RuntimeError(f"geom {n} missing from model")
                    gids.append(g)
                self._glow[key] = gids

        self.called = {k: False for k in self._jnt}
        self._pending = {k: False for k in self._jnt}
        self._apply_colours(model)

    def _apply_colours(self, model):
        for key, gids in self._glow.items():
            colour = COLOUR_CALLED if self.called[key] else COLOUR_IDLE
            for g in gids:
                model.geom_rgba[g] = colour

    def update(self, model, data):
        """Latch any button pushed past the trip point. Call once per step.

        Once latched the call stays lit even after the cap springs back out;
        only `clear()` resets it.
        """
        changed = False
        for key, qadr in self._jnt.items():
            if data.qpos[qadr] >= PRESS_TRIP and not self.called[key]:
                self.called[key] = True
                self._pending[key] = True
                changed = True
        if changed:
            self._apply_colours(model)

    def consume_press(self, elevator, direction):
        """Return True once for a newly latched call, then reset the flag."""
        key = (elevator, direction)
        fired = self._pending[key]
        self._pending[key] = False
        return fired

    def clear(self, model, elevator=None, direction=None):
        """Cancel calls (e.g. once the car arrives), turning the halo white."""
        for key in self._jnt:
            if elevator is not None and key[0] != elevator:
                continue
            if direction is not None and key[1] != direction:
                continue
            self.called[key] = False
        self._apply_colours(model)

    def press(self, model, data, elevator, direction, depth=0.0025):
        """Push a cap in from code, for scripted demos and previews."""
        key = (elevator, direction)
        data.qpos[self._jnt[key]] = depth
        self.called[key] = True
        self._pending[key] = True
        self._apply_colours(model)
        mujoco.mj_forward(model, data)
