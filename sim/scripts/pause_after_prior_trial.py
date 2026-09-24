"""Finish archiving an active trial while its original batch scheduler is stopped.

Operator-only scheduling change: never changes frozen trial inputs or signals
the live trial. The user explicitly requested a review before the next condition.
"""
import json
import os
from pathlib import Path
import signal
import time

from run_prior_comparison import ROOT, BATCH, STUDY, validate, summarize
from prior_materials import write_json


def process_info(pid):
    try:
        stat = (Path('/proc')/str(pid)/'stat').read_text()
    except FileNotFoundError:
        return None
    parts = stat.rsplit(')', 1)[1].split()
    return {'state': parts[0], 'started_ticks': parts[19],
            'exit_status': int(parts[49]) if len(parts) > 49 else None}


def finish_paused_trial():
    request = json.loads((BATCH/'pause-after-B1.json').read_text())
    state = json.loads((BATCH/'status.json').read_text())
    assert state['current_run'] == request['active_run'] == 'prior-001-B1'
    assert not state['completed'] and state['status'] == 'running'
    scheduler_pid, trial_pid = request['scheduler_pid'], request['active_launcher_pid']
    assert scheduler_pid == state['pid'] and trial_pid == state['active']['pid']
    scheduler = process_info(scheduler_pid)
    trial = process_info(trial_pid)
    assert scheduler and scheduler['state'] == 'T', 'Scheduler must already be suspended'
    assert b'run_prior_comparison.py' in (Path('/proc')/str(scheduler_pid)/'cmdline').read_bytes()
    assert trial, 'Active launcher missing; inspect before changing status'
    if trial['state'] != 'Z':
        assert b'start_prior_experiment.py' in (Path('/proc')/str(trial_pid)/'cmdline').read_bytes()
    control = {'status': 'waiting_for_trial_and_exports', 'pid': os.getpid(),
               'started_unix': time.time(), 'scheduler_pid': scheduler_pid,
               'trial_pid': trial_pid, 'frozen_inputs_unchanged': True}
    write_json(BATCH/'pause-controller.json', control)
    print('Waiting for B1 and its exports; scheduler is suspended, no next group can start.', flush=True)
    while True:
        current = process_info(trial_pid)
        if current is None or current['started_ticks'] != trial['started_ticks']:
            raise RuntimeError('Trial disappeared unexpectedly; no next trial has been started')
        if current['state'] == 'Z':
            break
        time.sleep(5)
    # Only the independent launcher has finished. A stopped parent cannot reap it.
    # Releasing that parent after archiving also releases the sleep inhibitor.
    active = state['active']
    try:
        if current['exit_status'] != 0:
            raise RuntimeError('Trial launcher exited abnormally: '+str(current['exit_status']))
        manifest = validate()
        outcome = summarize(ROOT/'experiments'/active['run'], manifest['variants']['B'])
        state['completed'].append({**active, 'ended_unix': time.time(), 'result': outcome})
        write_json(BATCH/'results.json', {'study': manifest['study'], 'block': 1,
                                       'trials': state['completed']})
        state.update(status='paused_after_B1', current_run=None, active=None,
            paused_unix=time.time(), pause_reason=request['reason'],
            pending_order=['D1','A1','C1'], resume_automatically=False)
        control.update(status='paused_after_B1', completed_unix=time.time())
    except Exception as exc:
        state.update(status='paused_after_B1_error', error=f'{type(exc).__name__}: {exc}',
            paused_unix=time.time(), resume_automatically=False)
        control.update(status='paused_after_B1_error', error=state['error'], completed_unix=time.time())
    finally:
        parent_now = process_info(scheduler_pid)
        assert parent_now and parent_now['started_ticks'] == scheduler['started_ticks'] and parent_now['state'] == 'T'
        assert process_info(trial_pid)['state'] == 'Z'
        # The trial is already over; terminate only the stopped scheduler, not a
        # process group. SIGCONT would allow it to dispatch the next condition.
        os.kill(scheduler_pid, signal.SIGKILL)
        state['scheduler_retired_after_trial_exit'] = True
        write_json(BATCH/'status.json', state)
        write_json(BATCH/'pause-controller.json', control)
    print(control['status']+'; remaining conditions have not started.', flush=True)


if __name__ == '__main__':
    finish_paused_trial()
