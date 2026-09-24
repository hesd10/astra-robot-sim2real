"""Six fresh trials comparing the exact inputs to historical attempts 004 and 005."""
import argparse
import difflib
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from account_preflight import preflight
from run_iterations import command_for, git, read_json, write_json
from sim_env.transfer import audit
from sim_env.setup import load_setup
from sim_env.agent import DEFAULT_CODEX

NAME = 'skill-v4-v5-repeat-001'
STUDY = ROOT/'reports/studies'/NAME
BATCH = ROOT/'reports/batches'/NAME
ORDER = ['A1', 'B1', 'B2', 'A2', 'A3', 'B3']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lines(path):
    return [json.loads(s) for s in path.read_text().splitlines() if s.strip()]


def prepare():
    if STUDY.exists() or BATCH.exists():
        raise RuntimeError('Study already exists; never replace frozen inputs')
    variants = {}
    payloads = {}
    historical = {}
    for group, number in [('A', 4), ('B', 5)]:
        run = ROOT/'experiments'/f'run-{number:03}'
        subject = run/'subject'
        history = git(subject, 'rev-list', '--reverse', 'HEAD').decode().splitlines()
        commit = history[1]
        names = git(subject, 'ls-tree', '-r', '--name-only', commit, '--', 'skill').decode().splitlines()
        payload = {p.removeprefix('skill/'): git(subject, 'show', commit+':'+p) for p in names}
        hashes = {p: hashlib.sha256(raw).hexdigest() for p, raw in payload.items()}
        if hashes != read_json(run/'private/transfer-audit.json')['sha256']:
            raise RuntimeError('Historical skill import mismatch: '+group)
        for name in ('PROMPT.md', 'API.md', 'robot.py'):
            if (subject/name).read_bytes() != (ROOT/'subject_template'/name).read_bytes():
                raise RuntimeError('Historical task interface changed: '+name)
        manifest = read_json(run/'private/simulation/manifest.json')
        if load_setup(ROOT/'setups/formal-001.json')['parameters'] != manifest['initialization']:
            raise RuntimeError('Historical initial pose changed')
        for name, expected in manifest['runtime_sha256'].items():
            if digest(ROOT/'sim_env'/name) != expected:
                raise RuntimeError('Historical runtime changed: '+name)
        historical[group] = manifest
        variants[group] = {'historical_attempt': run.name, 'input_commit': commit,
                           'skill': str(STUDY/'inputs'/group/'skill'), 'sha256': hashes}
        payloads[group] = payload
    STUDY.mkdir(parents=True)
    for group, payload in payloads.items():
        for name, raw in payload.items():
            target = STUDY/'inputs'/group/'skill'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        if not audit(variants[group]['skill'])['mechanical_pass']:
            raise RuntimeError('Historical skill screening failed')
    files = []
    for directory in ('sim_env', 'subject_template', 'assets', 'models'):
        files.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    files += [ROOT/'scripts'/n for n in ('start_experiment.py', 'prepare_subject.py',
              'account_preflight.py', 'run_iterations.py', 'run_skill_comparison.py')]
    files.append(ROOT/'setups/formal-001.json')
    binary = Path(os.environ.get('ASTRA_CODEX_BIN', DEFAULT_CODEX)).resolve()
    manifest = {'study': NAME, 'created_unix': time.time(), 'variants': variants,
                'codex_binary': str(binary), 'codex_binary_sha256': digest(binary),
                'codex_version': subprocess.check_output([str(binary), '--version'], text=True).strip(),
                'order': ORDER, 'order_method': 'Three fixed paired blocks: AB, BA, AB; set before outcomes',
                'configuration': {'model': 'gpt-6-astra', 'reasoning': 'xhigh', 'max_seconds': 1800.,
                                  'setup': 'setups/formal-001.json', 'monitor_fps': 10},
                'runtime_sha256': {str(p.relative_to(ROOT)): digest(p) for p in sorted(files)},
                'historical_runtime_verified': True, 'skill_transfer_between_trials': False,
                'launch_watchdog_seconds': 4500, 'automatic_retries': False,
                'historical_manifests': historical}
    write_json(STUDY/'manifest.json', manifest)
    diff = difflib.unified_diff(payloads['A']['SKILL.md'].decode().splitlines(True),
                               payloads['B']['SKILL.md'].decode().splitlines(True),
                               fromfile='A/SKILL.md', tofile='B/SKILL.md')
    (STUDY/'input-diff.patch').write_text(''.join(diff))
    (STUDY/'PROTOCOL.md').write_text('''# Frozen skill version comparison

Compare the exact skill input to historical run-004 (A) against the input to
historical run-005 (B), with three fresh trials per group. Fixed order: A1, B1,
B2, A2, A3, B3. This is a paired, interleaved exploratory comparison, not a
randomized large-sample estimate. No outcome-dependent reordering or retries.

The task prompt, robot API, starting pose, physics/runtime, model identifier,
reasoning effort and 1800-second native-session budget are fixed. The budget
includes agent closeout. Video export follows outside the task timer. Each new
workspace gets only its group's original skill; outputs never transfer onward.
Historical runtime hashes and every actual import are checked. No operator
task advice is supplied. The subject cannot read this private protocol.

Primary outcomes: physical success, wrong-button/fault events, and elapsed time
to accepted finish (or environment termination), including preparation, coding,
observations, actions, model latency and waiting. Report both original simulation
clock and native-turn-to-finish wall time. Failure time is time to termination,
not successful completion time; budget termination is identified separately.

Secondary measures: accepted arm/base commands, observation groups, deduplicated
cumulative-token-increasing response notifications before the endpoint, first
base motion time, first physical target press, union of tool intervals and time
outside tools, and peak non-support contact. Outside-tool time is not a direct
measurement of reasoning. Stage/recovery interpretation requires original logs
and videos, rather than automatically classifying every pause as hesitation.

Store all three videos (dashboard, full follow, compact follow), state history,
camera frames, visible agent events, timing, output skill and Git history. Output
skills are evidence only. Report all six outcomes; do not omit failed tasks.

Ordinary physical failures and 30-minute budget endings do not stop the sequence.
Authentication, model mismatch, contaminated input, missing evidence, scheduler
overrun or runtime failure stops the batch with existing evidence preserved.
No automatic rerun replaces an infrastructure failure. A 75-minute launcher
watchdog protects against hung postprocessing; it does not extend the model budget.
Sleep is inhibited while the batch runs. Account identity and availability are
checked before each trial without inference calls or usage-reset redemption.

Do not infer that the skill caused a difference from one favorable repetition.
Inspect success counts, all individual times/counts and paired differences; three
trials per version provide only an exploratory check. No clause-level ablation
is authorized by this first-stage protocol.
''')
    print('Prepared frozen study:', STUDY, flush=True)
    return manifest


def validate():
    manifest = read_json(STUDY/'manifest.json')
    binary = Path(os.environ.get('ASTRA_CODEX_BIN', DEFAULT_CODEX)).resolve()
    if str(binary) != manifest['codex_binary'] or digest(binary) != manifest['codex_binary_sha256']:
        raise RuntimeError('Frozen Codex executable changed')
    if manifest['order'] != ORDER or manifest['configuration'] != {
            'model': 'gpt-6-astra', 'reasoning': 'xhigh', 'max_seconds': 1800.,
            'setup': 'setups/formal-001.json', 'monitor_fps': 10}:
        raise RuntimeError('Frozen protocol changed')
    for name, expected in manifest['runtime_sha256'].items():
        if digest(ROOT/name) != expected:
            raise RuntimeError('Frozen runtime changed: '+name)
    for group, variant in manifest['variants'].items():
        current = audit(variant['skill'])
        if not current['mechanical_pass'] or current['sha256'] != variant['sha256']:
            raise RuntimeError('Frozen skill changed: '+group)
    return manifest


def measure(run):
    private = run/'private'
    result = read_json(private/'simulation/result.json')
    events = lines(private/'simulation/events.jsonl')
    timing = lines(private/'agent-timing.jsonl')
    raw = lines(private/'agent-events.jsonl')
    finish = next((e for e in events if e.get('accepted') and e.get('request', {}).get('op') == 'finish'), None)
    native_start = next(e['monotonic'] for e in timing if e['event'] == 'turn/started')
    # The full state stream starts with the environment-clock origin.
    with gzip.open(private/'simulation/states.jsonl.gz', 'rt') as stream:
        origin = json.loads(next(stream))['sample_monotonic']
    endpoint = finish['monotonic'] if finish else origin+result['wall_seconds']
    start_by_item = {}
    intervals = []
    for e in timing:
        if e['event'] == 'item/started' and e.get('item_type') in ('commandExecution', 'imageView'):
            start_by_item[e['item_id']] = e['monotonic']
        elif e['event'] == 'item/completed' and e.get('item_id') in start_by_item:
            left = max(native_start, start_by_item.pop(e['item_id']))
            right = min(endpoint, e['monotonic'])
            if right > left: intervals.append((left, right))
    for value in start_by_item.values():
        if endpoint > value: intervals.append((max(native_start, value), endpoint))
    merged = []
    for left, right in sorted(intervals):
        if merged and left <= merged[-1][1]: merged[-1][1] = max(merged[-1][1], right)
        else: merged.append([left, right])
    tool_seconds = sum(right-left for left, right in merged)
    item_times = {(e['event'], e.get('item_id')): e['monotonic'] for e in timing if e.get('item_id')}
    offsets = [e['emittedAtMs']/1000-item_times[(e.get('method'), e.get('params', {}).get('item', {}).get('id'))]
               for e in raw if e.get('emittedAtMs') and
               (e.get('method'), e.get('params', {}).get('item', {}).get('id')) in item_times]
    offset = statistics.median(offsets) if offsets else None
    previous = responses = 0
    for e in raw:
        if e.get('method') != 'thread/tokenUsage/updated': continue
        current = e['params']['tokenUsage']['total']['totalTokens']
        if offset is not None and e.get('emittedAtMs') and current > previous and e['emittedAtMs']/1000 <= endpoint+offset:
            responses += 1
        previous = current
    accepted = [e for e in events if e.get('accepted') and e['monotonic'] <= endpoint]
    return {'physical_success': result['physical_success'], 'subject_outcome': result['subject_outcome'],
            'fault': result['fault'], 'endpoint': 'accepted_finish' if finish else 'environment_termination',
            'sim_seconds': result['sim_seconds'], 'native_execution_wall_seconds': endpoint-native_start,
            'motion_commands': sum(e.get('request', {}).get('op') in ('move', 'base') for e in accepted),
            'observation_groups': sum(e.get('event') == 'observation_delivered' and e['monotonic'] <= endpoint for e in events),
            'response_proxy': responses if offset is not None else None,
            'usage_clock_offset_samples': len(offsets),
            'first_base_seconds': next((e['sim_time'] for e in accepted if e.get('request', {}).get('op') == 'base'), None),
            'first_target_press_seconds': next((e['sim_time'] for e in events if e.get('event') == 'target_pressed'), None),
            'peak_non_support_contact_N': result['peak_non_support_contact_N'],
            'tool_seconds': tool_seconds, 'outside_tool_seconds': endpoint-native_start-tool_seconds}


def summarize(run, variant):
    private, subject = run/'private', run/'subject'
    agent = read_json(private/'agent-result.json')
    result = read_json(private/'simulation/result.json')
    if agent.get('status') not in ('completed', 'environment_ended') or agent.get('exit_code') != 0:
        raise RuntimeError('Model/runtime failure: '+run.name)
    if result.get('subject_outcome') == 'contamination' or result.get('fault') == 'realtime_overrun':
        raise RuntimeError('Contamination or simulator scheduling failure: '+run.name)
    if result.get('recording_error') or (result.get('operator_monitor') or {}).get('error'):
        raise RuntimeError('Evidence recording failed: '+run.name)
    if read_json(private/'transfer-audit.json')['sha256'] != variant['sha256']:
        raise RuntimeError('Actual skill transfer differs from frozen input')
    history = git(subject, 'rev-list', '--reverse', 'HEAD').decode().splitlines()
    names = git(subject, 'ls-tree', '-r', '--name-only', history[1], '--', 'skill').decode().splitlines()
    imported = {p.removeprefix('skill/'): hashlib.sha256(git(subject, 'show', history[1]+':'+p)).hexdigest() for p in names}
    if imported != variant['sha256']:
        raise RuntimeError('Initial import commit differs from frozen input')
    launch = read_json(private/'launch.json')
    if (agent.get('resolved_model'), agent.get('reasoning'), launch.get('max_seconds')) != ('gpt-6-astra', 'xhigh', 1800):
        raise RuntimeError('Model/effort/budget changed')
    for name in ('dashboard.mp4', 'follow.mp4', 'follow-compact.mp4'):
        if not (private/name).is_file() or not (private/name).stat().st_size:
            raise RuntimeError('Missing video: '+name)
    if read_json(private/'dashboard-recording.json')['status'] != 'saved':
        raise RuntimeError('Dashboard recording incomplete')
    return {**measure(run), 'agent_status': agent['status'], 'agent_wall_seconds': agent.get('elapsed_wall_s'),
            'output_skill_used_by_other_trials': False, 'final_commit': history[-1]}


def run():
    manifest = validate()
    if BATCH.exists(): raise RuntimeError('Batch already exists; never silently restart')
    from sim_env.dashboard_recording import check_available
    check_available()
    BATCH.parent.mkdir(parents=True, exist_ok=True)
    with (ROOT/'experiments/.iterations.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        names = ['repeat-v4-v5-'+label for label in ORDER]
        if any((ROOT/'experiments'/name).exists() for name in names):
            raise RuntimeError('A destination trial already exists')
        BATCH.mkdir()
        state = {'status': 'running', 'pid': os.getpid(), 'started_unix': time.time(),
                 'manifest_sha256': digest(STUDY/'manifest.json'), 'order': ORDER,
                 'completed': [], 'active': None, 'current_run': None}
        write_json(BATCH/'status.json', state)
        process = None
        old_handlers = {}
        def interrupted(signum, frame): raise KeyboardInterrupt('signal '+str(signum))
        try:
            for sig in (signal.SIGINT, signal.SIGTERM): old_handlers[sig] = signal.signal(sig, interrupted)
            for index, (label, name) in enumerate(zip(ORDER, names), 1):
                validate()
                if digest(STUDY/'manifest.json') != state['manifest_sha256']:
                    raise RuntimeError('Manifest changed')
                quota = preflight()
                if quota['minimum_remaining_percent'] <= 0 or quota.get('spend_control_reached'):
                    raise RuntimeError('Account quota unavailable; preserving completed trials')
                if index == 1: state['account_fingerprint'] = quota['account_fingerprint']
                if quota['account_fingerprint'] != state['account_fingerprint']:
                    raise RuntimeError('Account changed during the fixed comparison')
                variant = manifest['variants'][label[0]]
                command = command_for(ROOT, name, variant['skill'], ROOT/'setups/formal-001.json', 1800., 'xhigh')
                active = {'run': name, 'label': label, 'group': label[0], 'pair': (index+1)//2,
                          'started_unix': time.time(), 'quota_before': quota, 'input_sha256': variant['sha256'],
                          'log': str(BATCH/(name+'.log')), 'command': command}
                state.update(current_run=name, active=active)
                print(f'[{index}/6] Starting {name}; frozen group {label[0]}', flush=True)
                with Path(active['log']).open('x') as log:
                    process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    active['pid'] = process.pid
                    write_json(BATCH/'status.json', state)
                    while process.poll() is None:
                        if time.time()-active['started_unix'] > manifest['launch_watchdog_seconds']:
                            raise TimeoutError('Launcher exceeded the postprocessing watchdog')
                        state['last_checked_unix'] = time.time()
                        write_json(BATCH/'status.json', state)
                        time.sleep(5)
                    code = process.returncode
                    process = None
                if code: raise RuntimeError(f'{name}: launcher exit {code}; see retained log')
                outcome = summarize(ROOT/'experiments'/name, variant)
                state['completed'].append({**active, 'ended_unix': time.time(), 'result': outcome})
                state['active'] = None
                write_json(BATCH/'status.json', state)
                write_json(BATCH/'results.json', {'study': NAME, 'trials': state['completed']})
                print(f'[{index}/6] Archived {name}: success={outcome["physical_success"]}; seconds={outcome["sim_seconds"]:.2f}', flush=True)
            state.update(status='completed', current_run=None, ended_unix=time.time())
            write_json(BATCH/'status.json', state)
            print('All six trials completed and all videos saved.', flush=True)
        except BaseException as exc:
            if process is not None and process.poll() is None:
                process.send_signal(signal.SIGINT)
                try: process.wait(timeout=180)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try: process.wait(timeout=15)
                    except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL)
            state.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                         error=f'{type(exc).__name__}: {exc}', ended_unix=time.time())
            write_json(BATCH/'status.json', state)
            print('Batch stopped with evidence preserved: '+state['error'], flush=True)
            raise
        finally:
            for sig, handler in old_handlers.items(): signal.signal(sig, handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    if args.prepare: prepare()
    elif args.check_only:
        validate()
        from sim_env.dashboard_recording import check_available
        check_available()
        print('Frozen protocol, skills and recording dependencies verified; no inference started.')
    else: run()
