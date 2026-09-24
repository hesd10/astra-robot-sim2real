"""Sequential frozen-input ablation; outputs never become another trial's input."""
import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import random
import secrets
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from account_preflight import preflight
from run_iterations import command_for, git, read_json, write_json
from sim_env.setup import load_setup
from sim_env.transfer import audit

BATCH_NAME = 'run-007-ablation'


def validate_inputs(root, manifest_path):
    manifest = read_json(manifest_path)
    repo = Path(manifest['repository'])
    if git(repo, 'rev-parse', 'HEAD').decode().strip() != manifest['commit']:
        raise RuntimeError('Frozen input commit changed')
    if git(repo, 'status', '--porcelain', '--untracked-files=all').strip():
        raise RuntimeError('Frozen input repository is not clean')
    for name, expected in {**manifest['fixed_inputs_sha256'], **manifest['runtime_files_sha256']}.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Fixed input/runtime changed: '+name)
    names = [v['run'] for v in manifest['variants']]
    if len(names) != 4 or set(names) != {f'run-007-{i}' for i in range(1, 5)}:
        raise RuntimeError('Expected the four named ablation conditions')
    for variant in manifest['variants']:
        screened = audit(variant['skill'])
        if not screened['mechanical_pass'] or screened['sha256'] != variant['sha256']:
            raise RuntimeError('Frozen skill does not match manifest: '+variant['run'])
    config = manifest['configuration']
    if (config['model'], config['reasoning'], config['max_seconds']) != ('gpt-6-astra', 'xhigh', 1800):
        raise RuntimeError('Frozen experiment configuration changed')
    load_setup(root/config['setup'])
    return manifest


def validate_quota(snapshot, minimum, expected_fingerprint=None):
    if snapshot['minimum_remaining_percent'] < minimum or snapshot.get('spend_control_reached'):
        raise RuntimeError(f'Quota preflight: less than {minimum:g}% remains or spending is blocked')
    if expected_fingerprint and snapshot['account_fingerprint'] != expected_fingerprint:
        raise RuntimeError('Account changed during the batch; preserve the batch configuration')
    if (snapshot['model'], snapshot['effort']) != ('gpt-6-astra', 'xhigh'):
        raise RuntimeError('Account model/effort differs from frozen configuration')


def summarize(run, variant):
    private, subject = run/'private', run/'subject'
    agent = read_json(private/'agent-result.json')
    result = read_json(private/'simulation'/'result.json')
    if agent.get('status') not in ('completed', 'environment_ended') or agent.get('exit_code') != 0:
        raise RuntimeError(run.name+': inference/runtime failure; inspect agent-result.json')
    if result.get('subject_outcome') == 'contamination':
        raise RuntimeError(run.name+': contamination reported')
    if result.get('recording_error') or (result.get('operator_monitor') or {}).get('error'):
        raise RuntimeError(run.name+': recording/monitor failure')
    if result.get('fault') == 'realtime_overrun':
        raise RuntimeError(run.name+': simulator scheduling failure')
    if read_json(private/'transfer-audit.json')['sha256'] != variant['sha256']:
        raise RuntimeError(run.name+': actual imported skill differs from frozen input')
    history = git(subject, 'rev-list', '--reverse', 'HEAD').decode().splitlines()
    if len(history) < 2:
        raise RuntimeError(run.name+': initial skill import commit is missing')
    imported_files = git(subject, 'ls-tree', '-r', '--name-only', history[1], '--', 'skill').decode().splitlines()
    imported = {p.removeprefix('skill/'): hashlib.sha256(git(subject, 'show', history[1]+':'+p)).hexdigest()
                for p in imported_files}
    if imported != variant['sha256']:
        raise RuntimeError(run.name+': committed initial skill differs from frozen input')
    launch = read_json(private/'launch.json')
    if (agent.get('resolved_model'), agent.get('reasoning'), launch.get('max_seconds')) != ('gpt-6-astra', 'xhigh', 1800):
        raise RuntimeError(run.name+': actual model/effort/budget changed')
    for name in ('dashboard.mp4', 'follow.mp4', 'follow-compact.mp4'):
        if not (private/name).is_file() or not (private/name).stat().st_size:
            raise RuntimeError(run.name+': video not saved: '+name)
    if read_json(private/'dashboard-recording.json').get('status') != 'saved':
        raise RuntimeError(run.name+': dashboard video is not saved')
    output_skill = audit(subject/'skill') if (subject/'skill').exists() else None
    return {'physical_success': result.get('physical_success'), 'subject_outcome': result.get('subject_outcome'),
            'fault': result.get('fault'), 'sim_seconds': result.get('sim_seconds'),
            'motion_commands': result.get('actions'), 'agent_status': agent['status'],
            'agent_wall_seconds': agent.get('elapsed_wall_s'),
            'closeout_completed': agent['status'] == 'completed',
            'final_commit': history[-1], 'final_skill_audit': output_skill,
            'final_skill_dirty': bool(git(subject, 'status', '--porcelain', '--', 'skill').strip()),
            'output_skill_used_by_other_trials': False,
            'videos': [str(private/n) for n in ('dashboard.mp4', 'follow.mp4', 'follow-compact.mp4')]}


def sleep_retry_plan(root, manifest, *, replace=False):
    """Preserve the interrupted attempt; give its fresh repetition a distinct ID."""
    previous_path = root/'reports/batches'/BATCH_NAME/'status.json'
    previous = read_json(previous_path)
    if previous.get('status') not in (('failed', 'interrupted') if replace else ('failed',)) or previous.get('current_run') != 'run-007-2':
        raise RuntimeError('Original batch must have finished exports and stopped on run-007-2')
    if not replace and 'simulator scheduling failure' not in previous.get('error', ''):
        raise RuntimeError('Original batch did not stop for the expected scheduling failure')
    if {x['run'] for x in previous['completed']} != {'run-007-3', 'run-007-4'}:
        raise RuntimeError('Expected the first two conditions to be archived')
    variants = {v['run']: v for v in manifest['variants']}
    for name in ('run-007-3', 'run-007-4'):
        summarize(root/'experiments'/name, variants[name])
    failed = root/'experiments/run-007-2/private'
    if replace:
        receipt_path = root/'reports/batches'/BATCH_NAME/'replacement-authorization.json'
        receipt = read_json(receipt_path)
        if (receipt.get('condition') != 'run-007-2' or receipt.get('user_authorized_overwrite') is not True
                or receipt.get('original_result', {}).get('fault') != 'realtime_overrun'
                or failed.parent.exists()):
            raise RuntimeError('Explicit overwrite record or fresh destination is missing')
        return {'run-007-2': 'run-007-2', 'run-007-1': 'run-007-1'}, {
            'previous_batch': str(previous_path), 'replacement_receipt': str(receipt_path),
            'reason': 'User authorized replacing sleep-interrupted run-007-2; original data removed.',
            'completed_conditions_retained': ['run-007-3', 'run-007-4'],
            'prior_account_fingerprint': previous['initial_quota']['account_fingerprint']}
    if read_json(failed/'simulation/result.json').get('fault') != 'realtime_overrun':
        raise RuntimeError('Interrupted attempt has a different fault')
    if read_json(failed/'dashboard-recording.json').get('status') != 'saved':
        raise RuntimeError('Interrupted attempt video has not finished saving')
    for name in ('dashboard.mp4', 'follow.mp4', 'follow-compact.mp4'):
        if not (failed/name).is_file() or not (failed/name).stat().st_size:
            raise RuntimeError('Interrupted attempt export is missing: '+name)
    return {
        'run-007-2-retry-001': 'run-007-2',
        'run-007-1': 'run-007-1',
    }, {'previous_batch': str(previous_path),
        'interrupted_attempt': str(failed.parent),
        'reason': 'User-confirmed host sleep caused realtime_overrun; fresh repetition authorized.',
        'excluded_from_skill_success_comparison': ['run-007-2'],
        'completed_conditions_retained': ['run-007-3', 'run-007-4'],
        'prior_account_fingerprint': previous['initial_quota']['account_fingerprint']}


def run_batch(root=ROOT, *, check_only=False, minimum_remaining=15., quota_reader=preflight,
              retry_after_sleep=False, replace_after_sleep=False):
    root = Path(root).resolve()
    manifest_path = root/'reports/retrospectives/run-007-ablation/READY.json'
    manifest = validate_inputs(root, manifest_path)
    continuation = None
    if retry_after_sleep and replace_after_sleep:
        raise ValueError('Choose either preserved retry or authorized replacement')
    is_continuation = retry_after_sleep or replace_after_sleep
    if is_continuation:
        conditions, continuation = sleep_retry_plan(root, manifest, replace=replace_after_sleep)
    else:
        conditions = {v['run']: v['run'] for v in manifest['variants']}
    suffix = '-replacement-001' if replace_after_sleep else '-sleep-retry-001' if retry_after_sleep else ''
    batch = root/'reports/batches'/(BATCH_NAME+suffix)
    names = list(conditions)
    if batch.exists() or any((root/'experiments'/n).exists() for n in names):
        raise RuntimeError('Batch/attempt already exists; never overwrite, resume or silently skip')
    initial_quota = quota_reader()
    validate_quota(initial_quota, minimum_remaining,
                   continuation['prior_account_fingerprint'] if continuation else None)
    print(f'Preflight: {initial_quota["plan"]}; remaining={initial_quota["minimum_remaining_percent"]:g}%; '
          f'{initial_quota["model"]}/{initial_quota["effort"]}; frozen skills verified', flush=True)
    if check_only:
        print('Read-only preflight passed; no attempts or model turns created.', flush=True)
        return initial_quota
    (root/'experiments').mkdir(exist_ok=True)
    batch.parent.mkdir(parents=True, exist_ok=True)
    with (root/'experiments/.iterations.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if batch.exists() or any((root/'experiments'/n).exists() for n in names):
            raise RuntimeError('A batch or attempt appeared during preflight')
        batch.mkdir()
        seed = None if is_continuation else secrets.randbits(64)
        if seed is not None:
            random.Random(seed).shuffle(names)
        variants = {v['run']: v for v in manifest['variants']}
        config = manifest['configuration']
        state = {'status': 'running', 'pid': os.getpid(), 'started_unix': time.time(),
                 'runs': names, 'condition_for_attempt': conditions, 'continuation': continuation,
                 'order_seed': seed, 'order_method': 'repeat interrupted condition, then remaining original order' if is_continuation else 'one prelaunch shuffle, no result-dependent reordering',
                 'configuration': config, 'input_commit': manifest['commit'],
                 'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                 'initial_quota': initial_quota, 'minimum_remaining_to_start_percent': minimum_remaining,
                 'quota_threshold_is_completion_guarantee': False,
                 'skill_inheritance_between_conditions': False, 'completed': [], 'active': None}
        write_json(batch/'frozen-inputs.json', manifest)
        write_json(batch/'status.json', state)
        print('Frozen order: '+' → '.join(names), flush=True)
        process = None; old_handlers = {}
        def interrupt(signum, frame):
            raise KeyboardInterrupt(f'received signal {signum}')
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                old_handlers[sig] = signal.signal(sig, interrupt)
            for index, name in enumerate(names):
                if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != state['manifest_sha256']:
                    raise RuntimeError('Ready manifest changed during batch')
                validate_inputs(root, manifest_path)
                quota = initial_quota if index == 0 else quota_reader()
                state['latest_quota'] = quota
                write_json(batch/'status.json', state)
                validate_quota(quota, minimum_remaining, initial_quota['account_fingerprint'])
                variant = variants[conditions[name]]
                command = command_for(root, name, variant['skill'], root/config['setup'],
                                      config['max_seconds'], config['reasoning'])
                active = {'run': name, 'condition': conditions[name], 'G': variant['G'], 'R': variant['R'],
                          'input_skill': variant['skill'], 'input_sha256': variant['sha256'],
                          'command': command, 'log': str(batch/(name+'.log')), 'quota_before': quota,
                          'started_unix': time.time()}
                state.update(current_run=name, active=active)
                write_json(batch/'status.json', state)
                print(f'[{index+1}/{len(names)}] Starting {name}; condition={conditions[name]}; input from frozen variant only', flush=True)
                with Path(active['log']).open('x') as log:
                    process = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                        start_new_session=True)
                    active['pid'] = process.pid
                    write_json(batch/'status.json', state)
                    for line in process.stdout:
                        log.write(line); log.flush()
                        print(f'[{name}] {line}', end='', flush=True)
                    code = process.wait(); process.stdout.close(); process = None
                if code:
                    raise RuntimeError(f'{name}: launcher exited with {code}; see its log')
                outcome = summarize(root/'experiments'/name, variant)
                state['completed'].append({**active, 'result': outcome, 'ended_unix': time.time()})
                state['active'] = None
                write_json(batch/'status.json', state)
                print(f'[{name}] Archived; success={outcome["physical_success"]}; '
                      f'agent={outcome["agent_status"]}; all three videos saved', flush=True)
            state.update(status='completed', current_run=None, ended_unix=time.time())
            write_json(batch/'status.json', state)
            print(f'All {len(names)} batch trials archived: '+str(batch/'status.json'), flush=True)
            return state
        except BaseException as exc:
            if process is not None and process.poll() is None:
                process.send_signal(signal.SIGINT)
                try: remaining, _ = process.communicate(timeout=180)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    remaining, _ = process.communicate(timeout=15)
                if remaining:
                    with Path(state['active']['log']).open('a') as log: log.write(remaining)
            state.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                         error=f'{type(exc).__name__}: {exc}', ended_unix=time.time())
            write_json(batch/'status.json', state)
            print('Batch stopped; preserved existing outputs: '+state['error'], flush=True)
            raise
        finally:
            for sig, handler in old_handlers.items(): signal.signal(sig, handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--retry-after-sleep', action='store_true',
                        help='Fresh run-007-2-retry-001 then run-007-1; preserve all earlier attempts.')
    parser.add_argument('--replace-after-sleep', action='store_true',
                        help='Run authorized replacement run-007-2 then run-007-1 after operator cleanup.')
    args = parser.parse_args()
    from sim_env.dashboard_recording import check_available
    check_available()
    run_batch(check_only=args.check_only, retry_after_sleep=args.retry_after_sleep,
              replace_after_sleep=args.replace_after_sleep)
