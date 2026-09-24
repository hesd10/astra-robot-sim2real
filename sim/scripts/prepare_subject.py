"""Prepare a clean first-run workspace. No historical skill is copied implicitly."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def prepare(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {}
    for name in ('robot.py', 'API.md', 'PROMPT.md'):
        source = ROOT/'subject_template'/name
        shutil.copyfile(source, destination/name)
        manifest[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    (destination/'infrastructure.json').write_text(json.dumps(manifest, indent=2)+'\n')
    subprocess.run(['git', 'init', '-q', str(destination)], check=True)
    # This host's Git 2.34 backport accepts safe.directory only from a file.
    (destination/'.gitconfig').write_text('[safe]\n\tdirectory = '+str(destination)+'\n')
    git = ['git', '--git-dir='+str(destination/'.git'), '--work-tree='+str(destination)]
    for key, value in [('user.name', 'Astra experiment'), ('user.email', 'experiment@localhost')]:
        subprocess.run(git+['config', key, value], check=True)
    subprocess.run(git+['add', '.'], check=True)
    subprocess.run(git+['commit', '-qm', 'Initialize generic interface and experiment prompt'], check=True)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination')
    args = parser.parse_args()
    print(prepare(args.destination))
