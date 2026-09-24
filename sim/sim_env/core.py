"""Single-owner physics, bounded commands and experiment-defined health."""
import math
import time
import numpy as np
import mujoco
from .model import CHANNELS, prepare, command


def number(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError('expected a finite number')
    value = float(value)
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError('number outside allowed range')
    return value


class Core:
    def __init__(self, *, standoff=.9, lateral=0., yaw=0., max_seconds=3600.):
        self.m, self.d, self.panel = prepare(standoff, lateral, yaw)
        self.dt = float(self.m.opt.timestep)
        self.max_seconds = max_seconds
        self.channels = {}
        for public, name in CHANNELS.items():
            j = self.m.joint(name)
            a = self.m.actuator('act_' + name).id
            v = math.radians(20 if public.startswith('head') else 15 if public.endswith(('_4', '_5')) else 10)
            self.channels[public] = dict(q=int(j.qposadr[0]), v=int(j.dofadr[0]), a=a,
                                         lo=float(j.range[0]) if j.limited[0] else -math.inf,
                                         hi=float(j.range[1]) if j.limited[0] else math.inf,
                                         limited=bool(j.limited[0]), speed=v, accel=3*v)
        self.motion = None
        self.base_goal = np.zeros(3)
        self.base_current = np.zeros(3)
        self.base_until = -1.
        self.risk = dict.fromkeys(self.channels, 0.)
        self.blocked = dict.fromkeys(self.channels, 0.)
        self.fault = None
        self.finished = False
        self.declared_outcome = None
        self.finish_result = None
        self.events = []
        self.steps = 0
        self.peak_contact = 0.
        self.impact_window = 0.
        self.first_press = None
        self.released_since = None
        self.public_action_count = 0
        self.robot_bodies = set()
        for b in range(self.m.nbody):
            cur = b
            while cur:
                if self.m.body(cur).name == 'chassis':
                    self.robot_bodies.add(b)
                    break
                cur = int(self.m.body_parentid[cur])

    def schema(self):
        return {'protocol': 'astra-sim-v1', 'cameras': ['head', 'left_wrist', 'right_wrist'],
                'attempt_budget_seconds': self.max_seconds,
                'joint_units': 'rad', 'zero_reference': 'fixed encoder reference, not startup pose',
                'joints': {k: {'minimum': c['lo'] if c['limited'] else None,
                                'maximum': c['hi'] if c['limited'] else None,
                                'continuous': not c['limited'], 'zero': 0.,
                                'max_target_speed': c['speed'], 'max_target_acceleration': c['accel']}
                           for k, c in self.channels.items()},
                'base': {'frame': 'robot', 'vx': 'forward m/s', 'vy': 'left m/s', 'wz': 'CCW rad/s',
                         'max_translation_speed': .1, 'max_yaw_speed': math.pi/12,
                         'max_translation_acceleration': .2, 'max_yaw_acceleration': math.pi/6,
                         'max_duration': 1.},
                'max_joint_duration': 10., 'health_kind': 'virtual risk, not motor registers'}

    def status(self):
        return {'sim_time': float(self.d.time), 'sample_monotonic': time.monotonic(),
                'joints': {k: {'position': float(self.d.qpos[c['q']]),
                               'target': float(self.d.ctrl[c['a']]),
                               'velocity': float(self.d.qvel[c['v']]),
                               'risk': self.risk[k]} for k, c in self.channels.items()},
                'health': 'fault' if self.fault else 'warning' if max(self.risk.values()) > .25 else 'normal',
                'fault': self.fault, 'finished': self.finished,
                'motion_active': self.motion is not None,
                'base_command': self.base_current.tolist()}

    def stop(self):
        # Preserve the currently applied arm targets; do not jump to a HOME pose.
        self.motion = None
        self.base_goal[:] = 0
        self.base_until = -1.

    def trip(self, reason):
        if self.fault is None:
            self.fault = reason
            self.stop()
            self.events.append({'event': 'fault', 'reason': reason, 'sim_time': float(self.d.time)})

    def dispatch(self, req, now=None):
        now = time.monotonic() if now is None else now
        op = req.get('op')
        allowed = {'schema': {'op', 'id'}, 'state': {'op', 'id'}, 'stop': {'op', 'id'},
                   'move': {'op', 'id', 'targets', 'duration'},
                   'base': {'op', 'id', 'vx', 'vy', 'wz', 'duration'},
                   'finish': {'op', 'id', 'outcome'}}
        if op not in allowed or set(req) - allowed[op]:
            raise ValueError('unknown operation or field')
        if op == 'schema':
            return self.schema()
        if op == 'state':
            return self.status()
        if op == 'stop':
            self.stop()
            return self.status()
        if op == 'finish':
            outcome = req.get('outcome')
            if outcome not in ('success', 'failure', 'contamination'):
                raise ValueError('invalid outcome')
            if not self.finished:
                self.declared_outcome = outcome
                self.finished = True
                self.stop()
                self.finish_result = self.private_result()
                self.events.append({'event': 'subject_finish', 'outcome': outcome, 'sim_time': float(self.d.time)})
            return self.status()
        if self.fault or self.finished:
            raise ValueError('motion disabled for this attempt')
        if op == 'base':
            goal = np.array([number(req.get('vx', 0), -.1, .1),
                             number(req.get('vy', 0), -.1, .1),
                             number(req.get('wz', 0), -math.pi/12, math.pi/12)])
            if np.linalg.norm(goal[:2]) > .1000000001:
                raise ValueError('combined translation speed exceeds limit')
            duration = number(req.get('duration'), .01, 1.)
            self.base_goal = goal
            self.base_until = now + duration
        elif op == 'move':
            if self.motion:
                raise ValueError('joint motion busy')
            targets = req.get('targets')
            if not isinstance(targets, dict) or not targets or set(targets) - set(self.channels):
                raise ValueError('unknown joint or empty targets')
            duration = number(req.get('duration'), .02, 10.)
            rows = []
            for k, value in targets.items():
                c = self.channels[k]
                end = number(value, c['lo'], c['hi'])
                start = float(self.d.ctrl[c['a']])
                distance = abs(end-start)
                # Cubic smoothstep: peak speed 1.5*d/T, peak accel 6*d/T^2.
                if 1.5*distance/duration > c['speed']+1e-9 or 6*distance/duration**2 > c['accel']+1e-9:
                    raise ValueError('duration too short for target speed/acceleration limits')
                rows.append((c['a'], start, end))
            self.motion = (float(self.d.time), duration, rows)
        self.public_action_count += 1
        return {'accepted': True, 'sim_time': float(self.d.time), 'action_number': self.public_action_count}

    def step(self, now=None):
        now = time.monotonic() if now is None else now
        if now >= self.base_until:
            self.base_goal[:] = 0
        delta = self.base_goal - self.base_current
        n = float(np.linalg.norm(delta[:2]))
        delta[:2] *= min(1., .2*self.dt/max(n, 1e-30))
        delta[2] = np.clip(delta[2], -math.pi/6*self.dt, math.pi/6*self.dt)
        self.base_current += delta
        command(self.m, self.d, *self.base_current)
        if self.motion:
            start, duration, rows = self.motion
            u = min(1., (float(self.d.time)+self.dt-start)/duration)
            s = u*u*(3-2*u)
            for a, begin, end in rows:
                self.d.ctrl[a] = begin + s*(end-begin)
            if u >= 1.:
                self.motion = None
        mujoco.mj_step(self.m, self.d)
        self.steps += 1
        if not np.isfinite(self.d.qpos).all() or not np.isfinite(self.d.qvel).all() or abs(self.d.time-self.steps*self.dt) > 1e-5:
            self.trip('invalid_physics')
            raise RuntimeError('physics state invalid')
        if any(self.d.warning.number):
            self.trip('physics_warning')
        self.panel.update(self.m, self.d)
        self._health()
        self._evaluate()
        if self.d.time >= self.max_seconds and not self.finished:
            self.trip('attempt_timeout')

    def _health(self):
        for k, c in self.channels.items():
            effort = abs(float(self.d.actuator_force[c['a']]))
            error = abs(float(self.d.ctrl[c['a']] - self.d.qpos[c['q']]))
            jammed = effort > .9*2.941995 and error > .08 and abs(self.d.qvel[c['v']]) < .02
            self.blocked[k] = self.blocked[k]+self.dt if jammed else 0.
            if self.blocked[k] > .5:
                self.risk[k] = min(1., self.risk[k]+self.dt/2.)
                if self.risk[k] >= 1.:
                    self.trip('joint_overload')
        peak = 0.
        force = np.empty(6)
        for i in range(self.d.ncon):
            c = self.d.contact[i]
            bodies = [int(self.m.geom_bodyid[g]) for g in (c.geom1, c.geom2)]
            if not any(b in self.robot_bodies for b in bodies):
                continue
            names = [self.m.geom(g).name or '' for g in (c.geom1, c.geom2)]
            # Exempt ONLY wheel tread/floor support, not arbitrary chassis/floor collisions.
            if 'floor' in names and any('_tread_' in n for n in names):
                continue
            mujoco.mj_contactForce(self.m, self.d, i, force)
            peak = max(peak, float(np.linalg.norm(force[:3])))
        self.peak_contact = max(self.peak_contact, peak)
        self.impact_window = self.impact_window+self.dt if peak > 100. else 0.
        if peak > 250. or self.impact_window >= .05:
            self.trip('severe_contact')
        rot = self.d.body('chassis').xmat.reshape(3, 3)
        if rot[2, 2] < math.cos(math.radians(20)):
            self.trip('base_tilt')

    def _evaluate(self):
        if self.panel.called[(2, 'up')] and self.first_press is None:
            self.first_press = float(self.d.time)
            self.events.append({'event': 'target_pressed', 'sim_time': self.first_press})
        target_j = self.m.joint('btn_2_up').qposadr[0]
        touching = False
        button_body = self.m.body('button_2_up').id
        for c in self.d.contact:
            b1, b2 = [int(self.m.geom_bodyid[g]) for g in (c.geom1, c.geom2)]
            if (b1 == button_body and b2 in self.robot_bodies) or (b2 == button_body and b1 in self.robot_bodies):
                touching = True
        released = self.first_press is not None and self.d.qpos[target_j] < .0005 and not touching
        if released and self.released_since is None:
            self.released_since = float(self.d.time)
        elif not released:
            self.released_since = None

    def private_result(self):
        if self.finish_result is not None:
            return dict(self.finish_result)
        wrong = any(v for k, v in self.panel.called.items() if k != (2, 'up'))
        stable = self.released_since is not None and self.d.time-self.released_since >= 2.
        base_v = self.m.joint('base_free').dofadr[0]
        stopped = np.linalg.norm(self.d.qvel[base_v:base_v+6]) < .01 and self.motion is None
        return {'target_pressed': self.first_press is not None, 'wrong_button': wrong,
                'released_for_2s': bool(stable), 'stopped': bool(stopped),
                'physical_success': bool(self.first_press is not None and not wrong and not self.fault),
                'subject_outcome': self.declared_outcome, 'fault': self.fault,
                'actions': self.public_action_count, 'sim_seconds': float(self.d.time),
                'peak_non_support_contact_N': self.peak_contact,
                'health_parameters': {'jam_effort_fraction': .9, 'jam_error_rad': .08,
                    'jam_speed_rad_s': .02, 'jam_grace_s': .5, 'risk_accumulation_s': 2.,
                    'severe_contact_N': 250., 'sustained_contact_N': 100., 'sustained_contact_s': .05},
                'health_scope': 'experimental thresholds, not real damage prediction'}
