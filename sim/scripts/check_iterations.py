"""Exercise batch sequencing and transfer failures without a model or physics process."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_iterations import run_batch, read_json, write_json, git
from sim_env.transfer import audit


FAKE_LAUNCHER = r'''
import argparse, hashlib, json, subprocess
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('name')
for name in ('setup','skill','max-seconds','reasoning'): p.add_argument('--'+name)
a=p.parse_args()
root=Path(__file__).resolve().parents[1]
mode=(root/'mode').read_text()
run=root/'experiments'/a.name
subject=run/'subject'; private=run/'private'
subject.mkdir(parents=True); (private/'simulation').mkdir(parents=True)
def git(*args):
    return subprocess.check_output(['git','-C',str(subject),*args],stderr=subprocess.PIPE)
def save(name,value):
    (private/name).write_text(json.dumps(value))
git('init','-q'); git('config','user.name','fixture'); git('config','user.email','fixture@localhost')
(subject/'API.md').write_text('Synthetic interface\n')
git('add','.'); git('commit','-qm','Initialize interface')
(subject/'skill').mkdir()
hashes={}
for src in Path(a.skill).iterdir():
    raw=src.read_bytes(); (subject/'skill'/src.name).write_bytes(raw)
    hashes[src.name]=hashlib.sha256(raw).hexdigest()
save('transfer-audit.json',{'sha256':hashes})
git('add','skill'); git('commit','-qm','Import audited generic skill only')
if mode != 'no_commit':
    with (subject/'skill'/'SKILL.md').open('a') as f: f.write('\nInspect a fresh complementary view before contact.\n')
    git('add','skill'); git('commit','-qm','Refine generic procedure')
if mode == 'dirty':
    with (subject/'skill'/'SKILL.md').open('a') as f: f.write('Uncommitted edit\n')
if mode == 'wrong_import': save('transfer-audit.json',{'sha256':{'SKILL.md':'wrong'}})
save('agent-result.json',{'status':'environment_ended' if mode=='timeout' else 'completed',
     'exit_code':0,'elapsed_wall_s':2})
save('simulation/result.json',{'subject_outcome':'contamination' if mode=='contamination' else 'failure' if a.name=='run-003' else 'success',
     'physical_success':a.name!='run-003','sim_seconds':1,'actions':1})
save('dashboard-recording.json',{'status':'saved'})
for name in ('dashboard.mp4','follow.mp4','follow-compact.mp4'): (private/name).write_bytes(b'fixture')
save('launch.json',vars(a))
print('Synthetic attempt and exports completed',flush=True)
'''


def fixture(root, mode='normal'):
    (root/'scripts').mkdir()
    (root/'scripts'/'start_experiment.py').write_text(FAKE_LAUNCHER)
    (root/'mode').write_text(mode)
    (root/'setups').mkdir()
    (root/'setups'/'formal-001.json').write_bytes((ROOT/'setups'/'formal-001.json').read_bytes())
    run = root/'experiments'/'run-002'
    subject, private = run/'subject', run/'private'
    subject.mkdir(parents=True)
    (private/'simulation').mkdir(parents=True)
    git(subject, 'init', '-q')
    git(subject, 'config', 'user.name', 'fixture')
    git(subject, 'config', 'user.email', 'fixture@localhost')
    (subject/'API.md').write_text('Synthetic interface\n')
    git(subject, 'add', '.')
    git(subject, 'commit', '-qm', 'Initialize interface')
    (subject/'skill').mkdir()
    (subject/'skill'/'SKILL.md').write_text('# Generic procedure\nObserve before moving.\n')
    write_json(private/'transfer-audit.json', {'sha256': audit(subject/'skill')['sha256']})
    git(subject, 'add', 'skill')
    git(subject, 'commit', '-qm', 'Import audited generic skill only')
    with (subject/'skill'/'SKILL.md').open('a') as output:
        output.write('Verify the visible result.\n')
    git(subject, 'add', 'skill')
    git(subject, 'commit', '-qm', 'Refine generic procedure')
    write_json(private/'agent-result.json', {'status':'completed', 'exit_code':0, 'elapsed_wall_s':2})
    write_json(private/'simulation'/'result.json', {'subject_outcome':'success', 'physical_success':True,
                                                  'sim_seconds':1, 'actions':1})
    write_json(private/'dashboard-recording.json', {'status':'saved'})
    for name in ('dashboard.mp4', 'follow.mp4', 'follow-compact.mp4'):
        (private/name).write_bytes(b'fixture')


def check():
    checks = []
    with tempfile.TemporaryDirectory(prefix='astra-batch-check-') as directory:
        parent = Path(directory)
        normal = parent/'normal'
        normal.mkdir(); fixture(normal)
        with contextlib.redirect_stdout(io.StringIO()):
            run_batch(normal, check_only=True)
        assert not (normal/'reports').exists()
        with contextlib.redirect_stdout(io.StringIO()):
            state = run_batch(normal)
        assert state['status'] == 'completed'
        assert [r['run'] for r in state['completed']] == ['run-003', 'run-004', 'run-005']
        assert state['completed'][0]['result']['physical_success'] is False
        for number, row in enumerate(state['completed'], 3):
            run = normal/'experiments'/f'run-{number:03d}'
            config = read_json(run/'private'/'launch.json')
            assert config['max_seconds'] == '1800.0' and config['reasoning'] == 'xhigh'
            assert config['setup'] == str(normal/'setups'/'formal-001.json')
            assert config['skill'] == str(normal/'experiments'/f'run-{number-1:03d}'/'subject'/'skill')
            assert read_json(run/'private'/'transfer-audit.json')['sha256'] == row['source']['skill_sha256']
            assert Path(row['log']).read_text().strip()
        assert (normal/'experiments'/'run-005'/'subject'/'skill'/'SKILL.md').read_text().count('complementary') == 3
        checks.append('three sequential processes, cumulative exact skill inheritance, physical failure continues, videos/logs/status')

        before = (normal/'reports'/'batches'/'run-003-to-run-005'/'status.json').read_bytes()
        try: run_batch(normal)
        except RuntimeError as exc: assert '已存在' in str(exc)
        else: raise AssertionError('existing attempts were not rejected')
        assert (normal/'reports'/'batches'/'run-003-to-run-005'/'status.json').read_bytes() == before
        checks.append('read-only preflight and existing attempts never overwritten')

        for mode in ('timeout', 'no_commit', 'dirty', 'contamination', 'wrong_import'):
            root = parent/mode
            root.mkdir(); fixture(root, mode)
            with contextlib.redirect_stdout(io.StringIO()):
                try: run_batch(root)
                except RuntimeError: pass
                else: raise AssertionError('unsafe continuation: '+mode)
            status = read_json(root/'reports'/'batches'/'run-003-to-run-005'/'status.json')
            assert status['status'] == 'failed' and status['current_run'] == 'run-003'
            assert not (root/'experiments'/'run-004').exists()
            checks.append(mode+' halts before next attempt')
    for result in checks: print('PASS:', result)


if __name__ == '__main__':
    check()
