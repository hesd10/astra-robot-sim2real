"""Detach the authorized first block, with a temporary sleep inhibitor."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_prior_comparison import NAME, BATCH, validate


if __name__ == '__main__':
    manifest = validate()
    if BATCH.exists():
        raise RuntimeError('First block already exists; no overwrite or automatic retry')
    inhibitor = shutil.which('systemd-inhibit')
    if inhibitor is None:
        raise RuntimeError('Sleep inhibitor unavailable; do not run an unprotected batch')
    launch = ROOT/'reports/studies'/NAME/'block-1-launch'
    launch.mkdir(parents=True, exist_ok=False)
    command = [inhibitor, '--what=sleep:idle', '--mode=block',
        '--why=Astra four-condition initial-prior experiment',
        str(ROOT.parent/'run-local.sh'), 'scripts/run_prior_comparison.py', '--run-first-block']
    with (launch/'background.log').open('x') as log:
        process = subprocess.Popen(command, cwd=ROOT.parent, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    receipt = {'pid': process.pid, 'started_unix': time.time(), 'command': command,
        'order': manifest['planned_blocks'][0], 'first_block_only': True,
        'log': str(launch/'background.log'), 'status_file': str(BATCH/'status.json')}
    (launch/'launch.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))
