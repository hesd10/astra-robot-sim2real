"""Offline artifact checks; never opens hardware or a model connection."""
from pathlib import Path
import json,re,hashlib
R=Path(__file__).resolve().parents[1]
checks={};errors=[]
for n,count in [('fixed-start',30),('perturbation',18),('local-skills',27),('real',12)]:
 rows=json.loads((R/'results'/f'{n}.json').read_text());assert len(rows)==count and all(x['success'] for x in rows);checks[n]=count
real=json.loads((R/'results/real.json').read_text());assert all(x['start']=='shared' for x in real if x['condition'] in 'ABC');assert [x['start'] for x in real if x['condition']=='D']==['shared','new-1','new-2']
# Human-facing documentation links. Ignore original frozen materials and code fences.
for p in [R/'README.md',* (R/'docs').glob('*.md'),*(R/'report').glob('*.md')]:
 for u in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if not u.startswith(('https:','http:','#','mailto:')) and not (p.parent/u.split('#')[0]).exists():errors.append(f'Broken link {p.relative_to(R)} -> {u}')
blocked=[p for p in R.rglob('*') if p.is_file() and (p.name in ['auth.json','accounts.json','.env'] or 'codex-home' in p.parts or p.name.startswith('rollout-'))]
assert not blocked,[str(x) for x in blocked]
# Sensitive assignment values, not generic credential-handling source code.
for p in R.rglob('*'):
 if '.git' in p.parts or not p.is_file() or p.suffix not in ['.py','.json','.jsonl','.md','.sh','.tex']:continue
 text=p.read_text(errors='replace')
 if re.search(r'\b(?:sk-[A-Za-z0-9_-]{30,}|ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,})',text):errors.append(f'Credential-like token: {p.relative_to(R)}')
 if ('-----BEGIN '+ 'PRIVATE KEY-----') in text:errors.append(f'Private key: {p.relative_to(R)}')
# Cross-check displayed percentage claims against actual rows.
s=json.loads((R/'results/summary.json').read_text());f=s['fixed'];r=s['real'];sk=s['skills']
computed={'sim_body':100*(1-f['I3E0']['mean']/f['I0E0']['mean']),'sim_E3':100*(1-f['I0E3']['mean']/f['I0E0']['mean']),'real_body':100*(1-r['B']['mean']/r['A']['mean']),'real_E3':100*(1-r['C']['mean']/r['A']['mean']),'STEP':100*(1-sk['STEP']['mean']/sk['FREE']['mean']),'LOOP':100*(1-sk['LOOP']['mean']/sk['FREE']['mean'])}
for key,expected in [('sim_body',57.4),('sim_E3',68.6),('real_body',53.0),('real_E3',49.9),('STEP',29.0),('LOOP',30.6)]:assert round(computed[key],1)==expected,(key,computed[key])
checks.update(percentages=computed,broken_links=errors,private_account_files=len(blocked))
if errors:raise AssertionError(errors)
(R/'results/release-checks.json').write_text(json.dumps(checks,indent=2)+'\n');print(json.dumps(checks,indent=2))
