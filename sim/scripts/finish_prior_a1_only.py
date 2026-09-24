"""Run the newly authorized A1 after archived B1/D1/C1; stop after block one.

Scheduling-only continuation; frozen trial materials and launcher are unchanged.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from run_prior_comparison import ROOT, NAME, STUDY, BATCH, validate, summarize, preflight
from prior_materials import write_json, digest


def check():
    manifest = validate()
    state = json.loads((BATCH/'status.json').read_text())
    if state['status'] != 'completed_awaiting_review' or state.get('active'):
        raise RuntimeError('Expected completed B1/D1/C1 and no active trial')
    if [t['label'] for t in state['completed']] != ['B1', 'D1', 'C1']:
        raise RuntimeError('Expected archived B1, D1 and C1')
    if state['order'] != manifest['planned_blocks'][0]:
        raise RuntimeError('Original first-block order changed')
    if state['manifest_sha256'] != digest(STUDY/'manifest.json'):
        raise RuntimeError('Original frozen manifest changed')
    if state['pending_order'] != [] or state.get('skipped') != ['A1']:
        raise RuntimeError('Unexpected remaining conditions')
    for label in ['A1']:
        if (ROOT/'experiments'/('prior-001-'+label)).exists():
            raise RuntimeError('Remaining trial already exists: '+label)
    # Verify that B1 and all three videos remain intact, without rerunning it.
    for trial in state['completed']:
        verified = summarize(ROOT/'experiments'/trial['run'], manifest['variants'][trial['group']])
        if verified != trial['result']:
            raise RuntimeError('Archived metrics changed: '+trial['label'])
    if (ROOT/'experiments/prior-001-A1').exists():
        raise RuntimeError('A1 unexpectedly exists')
    return manifest, state


def resume():
    with (ROOT/'experiments/.iterations.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest, state = check()
        from sim_env.dashboard_recording import check_available
        check_available()
        state.setdefault('continuations', []).append({
            'requested_by_user': 'Run A1 after B1/D1/C1, then stop; no second block',
            'started_unix': time.time(), 'previous_scheduler_pid': state['pid'],
            'git_head': subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()})
        state.update(status='running', pid=os.getpid(), resume_automatically=True,
            pending_order=['A1'], skipped=[], actual_requested_order=['B1','D1','C1','A1'])
        state.pop('ended_unix', None)
        state.pop('error', None)
        write_json(BATCH/'status.json', state)
        process = None
        old_handlers = {}
        def interrupted(signum, frame):
            raise KeyboardInterrupt('signal '+str(signum))
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                old_handlers[sig] = signal.signal(sig, interrupted)
            for label in ['A1']:
                validate()
                if digest(STUDY/'manifest.json') != state['manifest_sha256']:
                    raise RuntimeError('Manifest changed')
                quota = preflight()
                if quota['minimum_remaining_percent'] <= 0 or quota.get('spend_control_reached'):
                    raise RuntimeError('No available quota; preserve completed trials')
                if quota['account_fingerprint'] != state['account_fingerprint']:
                    raise RuntimeError('Account changed since B1')
                group, name = label[0], 'prior-001-'+label
                variant = manifest['variants'][group]
                command = [sys.executable,'-u',str(ROOT/'scripts/start_prior_experiment.py'),name,
                    '--input-dir',str(ROOT/variant['input_dir']),
                    '--reference',str(STUDY/'private-initial-reference.json'),
                    '--setup',str(ROOT/'setups/formal-001.json'),'--max-seconds','1800','--reasoning','xhigh']
                active = {'run':name,'label':label,'group':group,'block':1,
                    'started_unix':time.time(),'quota_before':quota,
                    'log':str(BATCH/(name+'.log')),'command':command}
                state.update(current_run=name, active=active)
                print('Starting '+name+'; B1/D1/C1 retained, frozen inputs unchanged.', flush=True)
                with Path(active['log']).open('x') as log:
                    process = subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,
                        stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    active['pid'] = process.pid
                    write_json(BATCH/'status.json',state)
                    while process.poll() is None:
                        if time.time()-active['started_unix'] > manifest['launch_watchdog_seconds']:
                            raise TimeoutError('Launcher/export watchdog exceeded')
                        state['last_checked_unix'] = time.time()
                        write_json(BATCH/'status.json',state)
                        time.sleep(5)
                    code = process.returncode
                    process = None
                if code:
                    raise RuntimeError(f'{name}: launcher exit {code}; see retained log')
                outcome = summarize(ROOT/'experiments'/name,variant)
                state['completed'].append({**active,'ended_unix':time.time(),'result':outcome})
                state.update(active=None,current_run=None)
                state['pending_order'] = [x for x in ['A1'] if x not in {t['label'] for t in state['completed']}]
                write_json(BATCH/'status.json',state)
                write_json(BATCH/'results.json',{'study':NAME,'block':1,'trials':state['completed']})
                print('Archived '+name+'; physical_success='+str(outcome['physical_success']),flush=True)
            state.update(status='completed_awaiting_review',ended_unix=time.time(),resume_automatically=False)
            write_json(BATCH/'status.json',state)
            print('First block complete: B1, D1, C1, A1. Stop; no second block started.',flush=True)
        except BaseException as exc:
            if process is not None and process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGTERM)
            state.update(status='interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',
                error=f'{type(exc).__name__}: {exc}',ended_unix=time.time())
            write_json(BATCH/'status.json',state)
            raise
        finally:
            for sig, handler in old_handlers.items():
                signal.signal(sig,handler)


def detach():
    check()
    inhibitor = shutil.which('systemd-inhibit')
    if not inhibitor:
        raise RuntimeError('Sleep inhibitor unavailable')
    directory = ROOT/'reports/studies'/NAME/'block-1-a1-only'
    directory.mkdir(parents=True,exist_ok=False)
    command = [inhibitor,'--what=sleep:idle','--mode=block',
        '--why=Astra remaining first-block prior experiments',
        str(ROOT.parent/'run-local.sh'),'scripts/finish_prior_a1_only.py','--worker']
    with (directory/'background.log').open('x') as log:
        process = subprocess.Popen(command,cwd=ROOT.parent,stdin=subprocess.DEVNULL,
            stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    receipt = {'pid':process.pid,'started_unix':time.time(),'command':command,
        'retained_trials':['B1','D1','C1'],'remaining_order':['A1'],
        'log':str(directory/'background.log'),'status_file':str(BATCH/'status.json')}
    write_json(directory/'launch.json',receipt)
    print(json.dumps(receipt,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--worker',action='store_true')
    mode.add_argument('--check-only',action='store_true')
    args = parser.parse_args()
    if args.check_only:
        check()
        print('B1/D1/C1 archives and frozen inputs verified; only A1 ready. No inference started.')
    elif args.worker:
        resume()
    else:
        detach()
