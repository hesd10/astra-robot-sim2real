"""One explicitly selected frozen reflection trial. Second measurement only."""
import argparse
from pathlib import Path
import os
import tomllib
from prepare_reflection_round2 import ROOT, OUT, validate, digest
from start_prior_experiment import start

def main():
    p=argparse.ArgumentParser();p.add_argument('run');a=p.parse_args();m=validate()
    t=next((t for t in m['trials'] if t['run']==a.run),None)
    if t is None:raise ValueError('Not in frozen second-measurement plan')
    if os.environ.get('ASTRA_BASE_URL'):raise RuntimeError('External model endpoint is not authorized')
    config=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'config.toml'
    model=tomllib.loads(config.read_text()).get('model','gpt-6-astra') if config.exists() else 'gpt-6-astra'
    if model!=m['model']:raise RuntimeError('Model differs from frozen model')
    run=start(a.run,input_dir=OUT/'inputs'/t['condition'],reference=OUT/'references'/t['point']/'private-initial-reference.json',
              setup=OUT/'setups'/f'{t["point"]}.json',max_seconds=m['task_seconds'],reasoning=m['effort'])
    prefix=t['condition']+'/'
    for path,h in m['inputs_sha256'].items():
        if path.startswith(prefix):assert digest(run/'subject'/path[len(prefix):])==h,path
    validate()

if __name__=='__main__':main()
