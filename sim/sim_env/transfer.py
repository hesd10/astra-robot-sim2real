"""Conservative mechanical skill-transfer gate; not a semantic proof."""
import ast
import hashlib
from pathlib import Path
import re
import shutil


def audit(path):
    root=Path(path).resolve(strict=True)
    findings=[];hashes={}
    if not (root/'SKILL.md').is_file():findings.append('SKILL.md missing')
    for p in sorted(root.rglob('*')):
        name=str(p.relative_to(root))
        if p.is_symlink():findings.append(name+': symlink prohibited');continue
        if p.is_dir():continue
        if p.suffix not in ('.md','.py'):
            findings.append(name+': only plain Markdown/Python may transfer');continue
        raw=p.read_bytes()
        if len(raw)>100000:findings.append(name+': oversized file');continue
        try:text=raw.decode('utf-8')
        except UnicodeDecodeError:findings.append(name+': non-text content');continue
        hashes[name]=hashlib.sha256(raw).hexdigest()
        forbidden=r'(?i)(data:image|base64\s*\.|pickle\s*\.|marshal\s*\.|q_press|q_home|\.mjcf\b|\.urdf\b|elevator_four_mecanum|/reports/|/experiments/|runs/run-\d|\.npz\b|\.npy\b)'
        if re.search(forbidden,text):findings.append(name+': historical/asset/encoded-data signature')
        if p.suffix=='.py':
            try:tree=ast.parse(text)
            except SyntaxError:findings.append(name+': invalid Python');continue
            for node in ast.walk(tree):
                if isinstance(node,(ast.List,ast.Tuple)) and len(node.elts)>=4 and all(isinstance(v,ast.Constant) and isinstance(v.value,(int,float)) for v in node.elts):
                    findings.append(name+': numeric sequence requires removal or generic re-expression')
                if isinstance(node,ast.Dict):
                    for key,value in zip(node.keys,node.values):
                        if isinstance(key,ast.Constant) and isinstance(key.value,str) and re.fullmatch(r'(left|right|head)_\d+',key.value) and isinstance(value,ast.Constant) and isinstance(value.value,(int,float)):
                            findings.append(name+': hardcoded per-joint numeric mapping')
    return {'mechanical_pass':not findings,'findings':findings,'sha256':hashes,
            'scope':'Mechanical screening only. The preceding agent must also audit semantic content under PROMPT.md; arbitrary encoded historical knowledge cannot be ruled out by this scanner.'}


def copy_clean(source,destination):
    report=audit(source)
    if not report['mechanical_pass']:raise ValueError('skill transfer rejected: '+'; '.join(report['findings']))
    destination=Path(destination)
    destination.mkdir(exist_ok=False)
    for name,expected in report['sha256'].items():
        raw=(Path(source)/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('skill changed during transfer')
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    return report
