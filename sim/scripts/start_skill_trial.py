"""Launch one explicitly selected frozen trial; never schedules the other trials."""
import argparse
import os
from pathlib import Path
import tomllib
from prepare_skill_evaluation import ROOT, OUT, validate, digest
from start_prior_experiment import start


def main():
    p=argparse.ArgumentParser();p.add_argument('run',nargs='?');p.add_argument('--check',action='store_true')
    args=p.parse_args();m=validate()
    if args.check:return
    if not args.run:p.error('Select a run from manifest.json; no automatic default')
    t=next((t for t in m['trials'] if t['run']==args.run),None)
    if t is None:raise ValueError('Run is not in the frozen plan')
    if os.environ.get('ASTRA_BASE_URL'):
        model=os.environ.get('ASTRA_MODEL')
    else:
        config=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'config.toml'
        model=tomllib.loads(config.read_text()).get('model','gpt-6-astra') if config.exists() else 'gpt-6-astra'
    if model!=m['model']:raise RuntimeError('Configured model differs from frozen Astra model; no trial launched')
    run=start(t['run'],input_dir=OUT/'inputs'/t['condition'],
              reference=OUT/'references'/t['point']/'private-initial-reference.json',
              setup=OUT/'setups'/f'{t["point"]}.json',max_seconds=m['task_seconds'],reasoning=m['effort'])
    # Own code/evidence is permitted, modifications of assigned inputs are not.
    prefix=t['condition']+'/'
    for file,h in m['inputs_sha256'].items():
        if file.startswith(prefix):
            assert digest(run/'subject'/file[len(prefix):])==h,'Assigned input modified: '+file
    validate()


if __name__=='__main__':main()
