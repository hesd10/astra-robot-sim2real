"""Validate independent second measurement without changing first-round inputs."""
from pathlib import Path
import json
from prepare_experience_reflection import ROOT, OUT as FIRST, OLD, validate as validate_first, digest, hashes
OUT=ROOT/'studies/experience-reflection-001-round2'
def validate():
    original=validate_first()
    m=json.loads((OUT/'manifest.json').read_text())
    assert digest(OUT/'manifest.json')==json.loads((OUT/'SEAL.json').read_text())['manifest_sha256']
    assert len(m['trials'])==18 and all(t['repeat']==2 for t in m['trials'])
    for k in ['inputs','setups','references']:assert hashes(OUT/k)==m[k+'_sha256'],k
    for c in ['C','R','E3']:
        source=(OLD if c=='E3' else FIRST)/'inputs'/c
        assert hashes(OUT/'inputs'/c)==hashes(source),c
    for k in ['setups','references']:assert hashes(OUT/k)==hashes(FIRST/k)
    for f,h in m['frozen_files'].items():assert digest(ROOT/f)==h,f
    assert digest(FIRST/'manifest.json')==m['first_manifest_sha256']
    assert m['model']==original['model'] and m['effort']==original['effort']
    return m
if __name__=='__main__':
    print('Validated second measurement:',len(validate()['trials']))
