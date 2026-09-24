"""Freeze the four prior conditions; run only the first four-attempt block."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import random
import secrets
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prior_materials import GROUPS, common_files, export_robot, initial_target, hashes, digest, write_json
from sim_env.core import Core
from sim_env.setup import load_setup
from sim_env.agent import DEFAULT_CODEX
from account_preflight import preflight
from run_skill_comparison import measure

NAME = 'prior-information-001'
STUDY = ROOT/'studies'/NAME
BATCH = ROOT/'reports/batches'/(NAME+'-block-1')
NEW_SCRIPTS = ('prior_materials.py', 'prior_service.py', 'start_prior_experiment.py',
               'run_prior_comparison.py', 'check_prior_comparison.py')


def prepare():
    if STUDY.exists():
        raise RuntimeError('Frozen study already exists; never replace after viewing results')
    STUDY.mkdir(parents=True)
    common_files(STUDY/'common')
    export_robot(STUDY/'robot-description')
    core = Core(**load_setup(ROOT/'setups/formal-001.json')['parameters'], max_seconds=1800.)
    initial = initial_target(core.m, core.d)
    write_json(STUDY/'private-initial-reference.json', {
        'public_measurement': initial, 'qpos': core.d.qpos.tolist(),
        'qvel': core.d.qvel.tolist(), 'ctrl': core.d.ctrl.tolist()})
    variants = {}
    for group, (robot_known, target_known) in GROUPS.items():
        dest = STUDY/'inputs'/group
        shutil.copytree(STUDY/'common', dest)
        supplied = []
        if robot_known:
            shutil.copytree(STUDY/'robot-description', dest/'prior/robot')
            supplied.append('prior/robot/robot.xml, prior/robot/interface_mapping.json, prior/robot/README.md and prior/robot/meshes/')
        if target_known:
            write_json(dest/'prior/initial_target.json', initial)
            supplied.append('prior/initial_target.json')
        (dest/'PRIOR.md').write_text('# Supplied information\n\n'
            'All attempts have the shared low-level interface documented in API.md.\n'
            'The following additional data, if listed, are authorized inputs for this attempt:\n\n'
            + ('\n'.join('- '+name for name in supplied) if supplied else '- No additional robot description or target measurement is supplied.')
            + '\n\nNo target or base localization measurements are updated during the attempt. No previous skill is supplied.\n')
        variants[group] = {'robot_description': robot_known, 'initial_target': target_known,
                           'input_dir': str(dest.relative_to(ROOT)), 'sha256': hashes(dest)}
    seed = secrets.randbits(64)
    order = list(GROUPS)
    random.Random(seed).shuffle(order)
    blocks = [[g+str(i+1) for g in order[i:]+order[:i]] for i in range(3)]
    binary = Path(os.environ.get('ASTRA_CODEX_BIN', DEFAULT_CODEX)).resolve()
    runtime = []
    for folder in ('sim_env', 'assets', 'models', 'subject_template'):
        runtime.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    runtime.extend(ROOT/'scripts'/name for name in NEW_SCRIPTS+(
        'account_preflight.py', 'run_skill_comparison.py', 'run_iterations.py', 'wheel_contact_model.py'))
    runtime.append(ROOT/'setups/formal-001.json')
    manifest = {'study': NAME, 'created_unix': time.time(), 'variants': variants,
        'order_seed': seed, 'planned_blocks': blocks,
        'order_method': 'one pre-outcome shuffle; cyclic rotations in subsequent blocks',
        'first_block_only': True, 'followup_requires_review': True,
        'configuration': {'model': 'gpt-6-astra', 'reasoning': 'xhigh', 'task_seconds': 1800.,
                          'agent_session_seconds': 1980., 'setup': 'setups/formal-001.json', 'monitor_fps': 10},
        'runtime_sha256': {str(p.relative_to(ROOT)): digest(p) for p in sorted(runtime)},
        'reference_sha256': digest(STUDY/'private-initial-reference.json'),
        'codex_binary': str(binary), 'codex_binary_sha256': digest(binary),
        'codex_version': subprocess.check_output([str(binary), '--version'], text=True).strip(),
        'skill_inheritance': False, 'online_localization': False,
        'launch_watchdog_seconds': 4500, 'automatic_retries': False}
    write_json(STUDY/'manifest.json', manifest)
    (STUDY/'PROTOCOL.zh-CN.md').write_text('''# 机器人构型资料 × 初始目标空间信息

目的：比较提供机器人构型资料、提供一次初始目标位置和表面朝向的影响及其交互。
A 两者无；B 只有机器人资料；C 只有初始目标测量；D 两者都有。
“无”表示没有额外资料；所有组共享关节编号、限位、当前角度、三路相机、
动作接口、保护机制与任务成功要求。不强制探索，不提供或继承 skill。

## 分批实施

先各组一次，共四次；首轮内部也交错随机。预先生成后两轮的循环交错顺序，
保存在 manifest.json 中，但当前运行器只允许执行首轮，完成后等待审阅。
首轮检查输入正确、坐标正确、接口一致、日志和视频完整；不把获得预期排序
作为继续条件。普通任务失败和不单调结果保留，不按结果更换组别或重跑。
若修改信息内容、提示词、接口、预算或运行配置，首轮仅作预实验，必须新建
协议版本并另起三轮；未修改时首轮可与后两轮合并，明确属于探索性比较。

## 信息与隔离

机器人资料只包含以 chassis 为根的机器人 XML、必要网格、接口关节/相机
映射；根位姿归零，没有按钮、电梯、世界坐标或本轮初始关节值。保留实际
几何、转轴、关节范围和驱动信息，没有附加控制器、轨迹、IK 或导航程序。
各组运行环境相同，沿用原受试环境（标准库、NumPy 等），不额外给某组工具。

初始目标信息是初始化沉降结束、实时物理计时开始前，按钮外表面中心及
外法向在初始底盘 chassis 坐标系的值，单位米。不是夹爪相对目标误差，
也不是世界坐标或全场景地图。每次启动前由私有服务验证实际初始化与冻结
参考一致；数据只提供一次，不会随运动更新。仿真这里使用精确测量；将来
实机须单独记录测量方法和误差，仿真与实机结果分别分析。

每次独立会话、工作目录及 Codex home；无网络、外部技能、旧对话、额外代理。
原 sim_env、旧运行器、旧 subject_template、旧结果均不修改。运行名称独立。
PRIOR.md 只列分配到的文件，不告知预期排名。未给出的资料不在受试目录中。

## 任务、预算和指标

沿用 formal-001 初始场景、gpt-6-astra/xhigh、低层接口与保护机制；目标为
中间电梯 UP，须实际触发、没有误按/故障，并用新图像确认红灯后声明成功。
报告物理成功、受试声明和是否有按下后的新图像，视觉语义仍需查看原证据。
仿真环境预算 1800 秒，模型会话最多 1980 秒，额外 180 秒只能用于故障或
终止后的收尾，不能延长物理任务；不要求输出 skill。视频导出不占任务预算。

主结果同时报告成功率和全部尝试的任务时间。计时保留环境原点→接受 finish
及原生模型 turn/started→接受 finish 两种口径，读资料、编程、思考/服务等待、
观察、动作、探索、恢复都计入；环境比模型先启动的偏移另记。主分析使用
原生模型执行时间；报告原始失败终止时间，但不能将失败视为快速完成。
预定补充评分：物理成功、声明成功且按下后获得新图像时取模型执行时间
（上限 1800 秒），其余取 1800 秒；最终任务成功仍须视觉证据审阅。不能把该评分
称为真实平均耗时。展示单次值、成功数、均值和样本标准差，不仅展示均值。
次要指标为动作/观测/模型响应次数、首次底盘运动与首次按下时间、峰值接触。
请求响应计数为日志代理指标，不等同于内部推理次数。

普通物理失败或超时不阻止本轮剩余组。模型/账号不符、输入变动、污染、
休眠/调度异常、接口或录像错误停止批次并保留证据；不覆盖已有尝试。
模型服务可用性和剩余额度每次启动前检查，不自动兑换重置额度或切账号。

旧实验基线见仓库标签 legacy-experiments-2026-09-20；历史文件校验见
仓库 version-control/legacy-inventory.json。新代码和冻结输入单独提交。
''')
    print('Prepared:', STUDY, 'planned blocks:', blocks, flush=True)
    return manifest


def validate():
    manifest = json.loads((STUDY/'manifest.json').read_text())
    for name, expected in manifest['runtime_sha256'].items():
        if digest(ROOT/name) != expected:
            raise RuntimeError('Frozen runtime changed: '+name)
    for group, variant in manifest['variants'].items():
        if hashes(ROOT/variant['input_dir']) != variant['sha256']:
            raise RuntimeError('Frozen input changed: '+group)
    if digest(STUDY/'private-initial-reference.json') != manifest['reference_sha256']:
        raise RuntimeError('Frozen initial reference changed')
    binary = Path(os.environ.get('ASTRA_CODEX_BIN', DEFAULT_CODEX)).resolve()
    if str(binary) != manifest['codex_binary'] or digest(binary) != manifest['codex_binary_sha256']:
        raise RuntimeError('Frozen executable changed')
    return manifest


def summarize(run, variant):
    private = run/'private'
    read = lambda name: json.loads((private/name).read_text())
    agent, result, launch = read('agent-result.json'), read('simulation/result.json'), read('launch.json')
    if agent.get('status') not in ('completed', 'environment_ended') or agent.get('exit_code') != 0:
        raise RuntimeError('Model/runtime failure: '+run.name)
    if (agent.get('resolved_model'), agent.get('reasoning'), launch.get('task_budget_seconds'),
        launch.get('agent_session_budget_seconds')) != ('gpt-6-astra', 'xhigh', 1800., 1980.):
        raise RuntimeError('Actual model/effort/budget changed')
    if result.get('subject_outcome') == 'contamination' or result.get('fault') in (
            'realtime_overrun', 'recording_failure', 'operator_camera_failure', 'camera_failure', 'service_exception'):
        raise RuntimeError('Infrastructure/contamination fault: '+run.name)
    if result.get('recording_error') or (result.get('operator_monitor') or {}).get('error'):
        raise RuntimeError('Evidence recording failed')
    if read('prior-input-audit.json')['sha256'] != variant['sha256']:
        raise RuntimeError('Actual input differs from assigned prior')
    init = read('simulation/initial-prior-audit.json')
    if not init['passed'] or init['reference_sha256'] != digest(STUDY/'private-initial-reference.json'):
        raise RuntimeError('Initial pose verification failed')
    for name in ('dashboard.mp4', 'follow.mp4', 'follow-compact.mp4'):
        if not (private/name).is_file() or not (private/name).stat().st_size:
            raise RuntimeError('Missing video: '+name)
    if read('dashboard-recording.json')['status'] != 'saved':
        raise RuntimeError('Dashboard export incomplete')
    metrics = measure(run)
    events = [json.loads(s) for s in (private/'simulation/events.jsonl').read_text().splitlines() if s.strip()]
    press = metrics['first_target_press_seconds']
    fresh_after_press = bool(press is not None and any(e.get('event') == 'observation_delivered'
        and e.get('sim_time', -1) >= press and e.get('snapshot_after_request') for e in events))
    success = bool(result['physical_success'] and result['subject_outcome'] == 'success' and fresh_after_press)
    return {**metrics, 'agent_status': agent['status'], 'agent_wall_seconds': agent.get('elapsed_wall_s'),
            'success_and_correct_declaration': success,
            'post_press_fresh_observation': fresh_after_press,
            'visual_evidence_review_required': True,
            'failure_capped_score_seconds': min(1800., metrics['native_execution_wall_seconds']) if success else 1800.,
            'initial_pose_verified': True, 'output_used_by_other_trials': False}


def run():
    manifest = validate()
    from sim_env.dashboard_recording import check_available
    check_available()
    labels = manifest['planned_blocks'][0]
    if BATCH.exists() or any((ROOT/'experiments'/('prior-001-'+label)).exists() for label in labels):
        raise RuntimeError('Batch/attempt already exists; never overwrite or silently resume')
    BATCH.parent.mkdir(parents=True, exist_ok=True)
    with (ROOT/'experiments/.iterations.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        BATCH.mkdir()
        state = {'status': 'running', 'pid': os.getpid(), 'started_unix': time.time(),
                 'manifest_sha256': digest(STUDY/'manifest.json'), 'order': labels,
                 'completed': [], 'active': None, 'current_run': None,
                 'first_block_only': True, 'later_blocks_started': False,
                 'git_head': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()}
        write_json(BATCH/'status.json', state)
        process = None
        old_handlers = {}
        def interrupted(signum, frame):
            raise KeyboardInterrupt('signal '+str(signum))
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                old_handlers[sig] = signal.signal(sig, interrupted)
            for index, label in enumerate(labels, 1):
                validate()
                if digest(STUDY/'manifest.json') != state['manifest_sha256']:
                    raise RuntimeError('Manifest changed')
                quota = preflight()
                if quota['minimum_remaining_percent'] <= 0 or quota.get('spend_control_reached'):
                    raise RuntimeError('No available quota; completed evidence retained')
                if index == 1:
                    state['account_fingerprint'] = quota['account_fingerprint']
                if quota['account_fingerprint'] != state['account_fingerprint']:
                    raise RuntimeError('Account changed during the block')
                group = label[0]
                variant = manifest['variants'][group]
                name = 'prior-001-'+label
                command = [sys.executable, '-u', str(ROOT/'scripts/start_prior_experiment.py'), name,
                    '--input-dir', str(ROOT/variant['input_dir']),
                    '--reference', str(STUDY/'private-initial-reference.json'),
                    '--setup', str(ROOT/'setups/formal-001.json'), '--max-seconds', '1800', '--reasoning', 'xhigh']
                active = {'run': name, 'label': label, 'group': group, 'block': 1,
                    'started_unix': time.time(), 'quota_before': quota,
                    'log': str(BATCH/(name+'.log')), 'command': command}
                state.update(current_run=name, active=active)
                print(f'[{index}/4] Starting {name}; frozen inputs, fresh session', flush=True)
                with Path(active['log']).open('x') as log:
                    process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    active['pid'] = process.pid
                    write_json(BATCH/'status.json', state)
                    while process.poll() is None:
                        if time.time()-active['started_unix'] > manifest['launch_watchdog_seconds']:
                            raise TimeoutError('Launcher/export watchdog exceeded')
                        state['last_checked_unix'] = time.time()
                        write_json(BATCH/'status.json', state)
                        time.sleep(5)
                    code = process.returncode
                    process = None
                if code:
                    raise RuntimeError(f'{name}: launcher exit {code}; see retained log')
                outcome = summarize(ROOT/'experiments'/name, variant)
                state['completed'].append({**active, 'ended_unix': time.time(), 'result': outcome})
                state['active'] = None
                write_json(BATCH/'status.json', state)
                write_json(BATCH/'results.json', {'study': NAME, 'block': 1, 'trials': state['completed']})
                print(f'[{index}/4] Archived {name}: physical_success={outcome["physical_success"]}', flush=True)
            state.update(status='completed_awaiting_review', current_run=None, ended_unix=time.time())
            write_json(BATCH/'status.json', state)
            print('First four trials complete. Blocks 2 and 3 have NOT started.', flush=True)
        except BaseException as exc:
            if process is not None and process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
            state.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                         error=f'{type(exc).__name__}: {exc}', ended_unix=time.time())
            write_json(BATCH/'status.json', state)
            raise
        finally:
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--check-only', action='store_true')
    mode.add_argument('--run-first-block', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.check_only:
        validate()
        from sim_env.dashboard_recording import check_available
        check_available()
        print('Frozen inputs/runtime and recording dependencies verified; no inference started.')
    else:
        run()
