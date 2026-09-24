"""Pure calibration math. No hardware access or motion commands."""
import math

TAU = 2 * math.pi
CPR = 4096
JOINTS = {}
for side, suffix, label in [('left', 'R', '左臂'), ('right', 'L', '右臂')]:
    for i, (xml, name) in enumerate(zip(
        ['Rotation', 'Pitch', 'Elbow', 'Wrist_Pitch', 'Wrist_Roll', 'Jaw'],
        ['肩部旋转', '肩部俯仰', '肘部', '腕部俯仰', '腕部滚转', '夹爪']), 1):
        JOINTS[f'{side}_{i}'] = dict(xml=f'{xml}_{suffix}', label=f'{label} · {name}', group=side, reference_q=0.0)
JOINTS['head_1'] = dict(xml='head_pan_joint', label='头部 · 水平转动', group='head', reference_q=math.pi)
JOINTS['head_2'] = dict(xml='head_tilt_joint', label='头部 · 俯仰', group='head', reference_q=0.0)
WHEELS = ['front_left', 'front_right', 'rear_left', 'rear_right']
WHEEL_LABELS = dict(zip(WHEELS, ['左前轮', '右前轮', '左后轮', '右后轮']))
DIRECTIONS = dict(forward='前推', backward='后拉', left='向左平移', right='向右平移', ccw='向左旋转', cw='向右旋转')

def signed_magnitude(value, bit=15):
    return -(value & ((1 << bit) - 1)) if value & (1 << bit) else value

def unwrap_delta(new, old):
    return (new - old + CPR // 2) % CPR - CPR // 2

def angle(count, reference_count, sign, reference_q):
    if sign not in [-1, 1]: raise ValueError('缺少正方向标定')
    return reference_q + sign * (count - reference_count) * TAU / CPR

def candidate_mapping(samples):
    """samples: key -> measured continuous count span; do not silently resolve ties."""
    ordered = sorted(samples.items(), key=lambda kv: kv[1], reverse=True)
    if not ordered or ordered[0][1] < 35:
        raise ValueError('变化太小，请只移动当前关节约 5–15° 后重试')
    if len(ordered) > 1 and ordered[1][1] > max(18, ordered[0][1] * .35):
        raise ValueError('多个电机同时明显变化，请只移动当前关节后重试')
    return ordered[0][0]

def infer_sign(delta, travel):
    if abs(delta) < 35: raise ValueError('净变化太小：顺正方向移动后停住，不要摆回起点')
    if travel > abs(delta) * 1.8 + 20: raise ValueError('往返变化较多，请沿动画正方向单向移动后重试')
    return 1 if delta > 0 else -1

def measured_limits(low, high, reference, sign, qref, margin_deg=3):
    lo, hi = sorted([angle(low, reference, sign, qref), angle(high, reference, sign, qref)])
    margin = math.radians(margin_deg)
    if hi - lo < 2 * margin + math.radians(5): raise ValueError('采集范围太小，无法保留边界余量')
    if high - low >= CPR - 32: raise ValueError('范围接近或超过一整圈；请缩小为本次实际需要的范围')
    return dict(observed_min_rad=lo, observed_max_rad=hi, usable_min_rad=lo+margin, usable_max_rad=hi-margin, margin_deg=margin_deg)

def wheel_matrix(diameter_mm, track_mm, wheelbase_mm, pattern='X'):
    dimensions = [float(diameter_mm), float(track_mm), float(wheelbase_mm)]
    if not all(math.isfinite(x) and 10 <= x <= 3000 for x in dimensions):
        raise ValueError('尺寸请填 10–3000 范围内的毫米数')
    if pattern != 'X': raise ValueError('当前仅支持图示的 X 型滚子排列；不匹配时先停在此页核实')
    r = dimensions[0] / 2000
    k = (dimensions[1] + dimensions[2]) / 2000
    return [[1/r, -1/r, -k/r], [1/r, 1/r, k/r], [1/r, 1/r, -k/r], [1/r, -1/r, k/r]]

def solve_base(trials, dimensions):
    matrix = wheel_matrix(**dimensions)
    axes = dict(forward=(0, 1), backward=(0, -1), left=(1, 1), right=(1, -1), ccw=(2, 1), cw=(2, -1))
    missing = [d for d in DIRECTIONS if d not in trials]
    if missing: raise ValueError('尚未完成：' + '、'.join(DIRECTIONS[x] for x in missing))
    signs = {}; checks = []
    for wi, wheel in enumerate(WHEELS):
        f = trials['forward'][wheel]['delta']
        if abs(f) < 45: raise ValueError(f'{WHEEL_LABELS[wheel]} 前推读数太小，请重采')
        signs[wheel] = 1 if f > 0 else -1
        for direction, (axis, ds) in axes.items():
            evidence = trials[direction][wheel]
            delta = evidence['delta']; expected = matrix[wi][axis] * ds
            if abs(delta) < 35 or delta * signs[wheel] * expected <= 0:
                raise ValueError(f'{DIRECTIONS[direction]} / {WHEEL_LABELS[wheel]} 方向不一致或变化太小；检查滑动、轮子对应和滚子排列后重采')
            if evidence['travel'] > abs(delta) * 1.8 + 30:
                raise ValueError(f'{DIRECTIONS[direction]} / {WHEEL_LABELS[wheel]} 往返变化过多，请单向重采')
            checks.append(dict(direction=direction, wheel=wheel, delta=delta))
    return dict(wheel_order=WHEELS, matrix_body_mps_radps_to_wheel_radps=matrix,
                encoder_sign_for_forward_roll=signs, counts_per_wheel_revolution=CPR,
                assumed_direct_drive=True, scale_status='nominal_geometry_only',
                active_motor_command_sign_verified=False, velocity_register_units_verified=False,
                stop_response_verified=False, passive_direction_checks=checks)
