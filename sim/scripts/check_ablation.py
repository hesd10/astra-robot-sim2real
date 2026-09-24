"""Offline batch integration checks with synthetic children; no model or robot."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile

from check_iterations import FAKE_LAUNCHER
from run_ablation import ROOT, run_batch
from run_iterations import git, read_json, write_json
from sim_env.transfer import audit


def quota(remaining=86, identity='synthetic'):
    return {'plan': 'fixture', 'minimum_remaining_percent': remaining,
            'account_fingerprint': identity, 'model': 'gpt-6-astra', 'effort': 'xhigh'}


def fixture(root, mode='normal'):
    root.mkdir()
    (root/'scripts').mkdir()
    launcher = FAKE_LAUNCHER.replace("for src in Path(a.skill).iterdir():", "for src in Path(a.skill).rglob('*'):\n    if not src.is_file(): continue")
    launcher = launcher.replace("raw=src.read_bytes(); (subject/'skill'/src.name).write_bytes(raw)\n    hashes[src.name]=hashlib.sha256(raw).hexdigest()",
        "rel=src.relative_to(a.skill); dst=subject/'skill'/rel; dst.parent.mkdir(parents=True,exist_ok=True)\n    raw=src.read_bytes(); dst.write_bytes(raw)\n    hashes[str(rel)]=hashlib.sha256(raw).hexdigest()")
    launcher = launcher.replace("a.name=='run-003'", "a.name=='run-007-2'").replace("a.name!='run-003'", "a.name!='run-007-2'")
    launcher += "\nagent=json.loads((private/'agent-result.json').read_text())\nagent.update(model='gpt-6-astra',resolved_model='gpt-6-astra',reasoning='xhigh')\nsave('agent-result.json',agent)\nsave('launch.json',{**vars(a),'max_seconds':float(a.max_seconds)})\n"
    (root/'scripts/start_experiment.py').write_text(launcher)
    (root/'mode').write_text(mode)
    (root/'setups').mkdir()
    (root/'setups/formal-001.json').write_bytes((ROOT/'setups/formal-001.json').read_bytes())
    (root/'experiments').mkdir()
    repo = root/'frozen'; repo.mkdir()
    git(repo, 'init', '-q'); git(repo, 'config', 'user.name', 'fixture'); git(repo, 'config', 'user.email', 'fixture@localhost')
    variants=[]
    for i in range(1,5):
        name=f'run-007-{i}'; skill=repo/name/'skill'; skill.mkdir(parents=True)
        (skill/'SKILL.md').write_text('# Generic method\nObserve the outcome.\n'+('Inspect alignment.\n' if i in (2,4) else '')+('Reassess the explanation.\n' if i in (3,4) else ''))
        if i in (2,4):
            (skill/'scripts').mkdir(); (skill/'scripts/helper.py').write_text('def identity(x): return x\n')
        variants.append({'run':name,'G':i in (2,4),'R':i in (3,4),'skill':str(skill),'sha256':audit(skill)['sha256']})
    git(repo,'add','.'); git(repo,'commit','-qm','Freeze fixture')
    report=root/'reports/retrospectives/run-007-ablation'; report.mkdir(parents=True)
    manifest={'repository':str(repo),'commit':git(repo,'rev-parse','HEAD').decode().strip(),
              'fixed_inputs_sha256':{'setups/formal-001.json':hashlib.sha256((root/'setups/formal-001.json').read_bytes()).hexdigest()},
              'runtime_files_sha256':{'scripts/start_experiment.py':hashlib.sha256((root/'scripts/start_experiment.py').read_bytes()).hexdigest()},
              'configuration':{'model':'gpt-6-astra','reasoning':'xhigh','max_seconds':1800,'setup':'setups/formal-001.json'},'variants':variants}
    write_json(report/'READY.json',manifest)
    return manifest


def main():
    checks=[]
    with tempfile.TemporaryDirectory(prefix='astra-ablation-check-') as folder:
        parent=Path(folder)
        normal=parent/'normal'; manifest=fixture(normal)
        with contextlib.redirect_stdout(io.StringIO()):
            run_batch(normal,check_only=True,quota_reader=quota)
            assert not (normal/'reports/batches').exists()
            result=run_batch(normal,quota_reader=quota)
        assert result['status']=='completed' and len(result['completed'])==4
        for row in result['completed']:
            v=next(v for v in manifest['variants'] if v['run']==row['run'])
            assert row['input_sha256']==v['sha256']
            assert read_json(normal/'experiments'/row['run']/'private/launch.json')['skill']==v['skill']
            assert 'complementary' not in Path(v['skill']).joinpath('SKILL.md').read_text()
        assert next(r for r in result['completed'] if r['run']=='run-007-2')['result']['physical_success'] is False
        assert [x['run'] for x in result['completed']]==result['runs']
        checks.append('four sequential children, frozen independent inputs, nested helper, physical failure continues, all exports')
        try: run_batch(normal,quota_reader=quota)
        except RuntimeError: pass
        else: raise AssertionError('existing batch was overwritten')
        checks.append('preflight creates no trial; duplicate batch is rejected')
        timeout=parent/'timeout'; fixture(timeout,'timeout')
        with contextlib.redirect_stdout(io.StringIO()): timed=run_batch(timeout,quota_reader=quota)
        assert len(timed['completed'])==4 and all(not r['result']['closeout_completed'] for r in timed['completed'])
        checks.append('time budget closeout recorded without coupling independent conditions')
        for label,mode,reader in [('bad_import','wrong_import',quota),('quota','normal',iter([quota(),quota(14)]).__next__),
                                  ('identity','normal',iter([quota(),quota(identity='other')]).__next__)]:
            root=parent/label; fixture(root,mode)
            with contextlib.redirect_stdout(io.StringIO()):
                try: run_batch(root,quota_reader=reader)
                except RuntimeError: pass
                else: raise AssertionError(label+' did not halt')
            status=read_json(root/'reports/batches/run-007-ablation/status.json')
            assert status['status']=='failed' and len(list((root/'experiments').glob('run-*')))==1
            checks.append(label+' stops before creating another trial')
        modified=parent/'modified'; m=fixture(modified)
        Path(m['variants'][0]['skill']).joinpath('SKILL.md').write_text('modified')
        try: run_batch(modified,quota_reader=quota)
        except RuntimeError: pass
        else: raise AssertionError('modified frozen input accepted')
        assert not list((modified/'experiments').glob('run-*'))
        checks.append('frozen input mutation rejected before launch')

        resumed=parent/'sleep_retry'; fixture(resumed)
        with contextlib.redirect_stdout(io.StringIO()): prior=run_batch(resumed,quota_reader=quota)
        # Synthetic interrupted batch: completed conditions retained, one fault, one not started.
        shutil.rmtree(resumed/'experiments/run-007-1')
        prior.update(status='failed',current_run='run-007-2',error='RuntimeError: run-007-2: simulator scheduling failure')
        prior['completed']=[r for r in prior['completed'] if r['run'] in ('run-007-3','run-007-4')]
        write_json(resumed/'reports/batches/run-007-ablation/status.json',prior)
        failed=resumed/'experiments/run-007-2/private/simulation/result.json'
        write_json(failed,{**read_json(failed),'fault':'realtime_overrun'})
        original={str(p.relative_to(resumed)):hashlib.sha256(p.read_bytes()).hexdigest()
                  for name in ('run-007-2','run-007-3','run-007-4')
                  for p in (resumed/'experiments'/name).rglob('*') if p.is_file()}
        with contextlib.redirect_stdout(io.StringIO()):
            run_batch(resumed,check_only=True,retry_after_sleep=True,quota_reader=quota)
            repeated=run_batch(resumed,retry_after_sleep=True,quota_reader=quota)
        assert repeated['runs']==['run-007-2-retry-001','run-007-1']
        assert repeated['condition_for_attempt']['run-007-2-retry-001']=='run-007-2'
        assert repeated['completed'][0]['G'] and not repeated['completed'][0]['R']
        assert '/frozen/run-007-2/skill' in repeated['completed'][0]['input_skill']
        assert all(hashlib.sha256((resumed/p).read_bytes()).hexdigest()==h for p,h in original.items())
        checks.append('sleep retry repeats only interrupted condition then remaining condition, retains original evidence, frozen input unchanged')
        # Explicit replacement uses the original condition ID, only with an operator receipt.
        shutil.rmtree(resumed/'experiments/run-007-2')
        shutil.rmtree(resumed/'experiments/run-007-1')
        try: run_batch(resumed,replace_after_sleep=True,check_only=True,quota_reader=quota)
        except FileNotFoundError: pass
        else: raise AssertionError('replacement without authorization record was accepted')
        write_json(resumed/'reports/batches/run-007-ablation/replacement-authorization.json',{
            'condition':'run-007-2','user_authorized_overwrite':True,
            'original_result':{'fault':'realtime_overrun'}})
        with contextlib.redirect_stdout(io.StringIO()):
            replaced=run_batch(resumed,replace_after_sleep=True,quota_reader=quota)
        assert replaced['runs']==['run-007-2','run-007-1']
        assert replaced['completed'][0]['input_skill'].endswith('/frozen/run-007-2/skill')
        retained={p:h for p,h in original.items() if '/run-007-3/' in p or '/run-007-4/' in p}
        assert all(hashlib.sha256((resumed/p).read_bytes()).hexdigest()==h for p,h in retained.items())
        checks.append('explicit replacement requires receipt, reuses condition ID and frozen input, preserves completed conditions')
    for check in checks: print('PASS:',check)


if __name__=='__main__': main()
