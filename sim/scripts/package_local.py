"""Assemble relocatable operator bundle without credentials/history/controllers."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def assemble(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    for directory in ('sim_env', 'subject_template'):
        shutil.copytree(ROOT/directory, destination/directory,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'codex_diagnostic.py'))
    scripts = ('wheel_contact_model.py', 'prepare_subject.py', 'start_experiment.py',
               'check_provider.py', 'check_protection.py', 'check_isolation.py',
               'check_agent_boundary.py', 'check_runtime.py', 'preview_initial.py', 'package_local.py')
    (destination/'scripts').mkdir()
    for name in scripts:
        shutil.copy2(ROOT/'scripts'/name, destination/'scripts'/name)
    shutil.copytree(ROOT/'packaging', destination/'packaging')
    for source, target in [('LOCAL_RUN.md', 'LOCAL_RUN.md'), ('LOCAL_RUN.md', 'README.md'),
                           ('requirements.txt', 'requirements.txt')]:
        shutil.copy2(ROOT/'packaging'/source, destination/target)
    (destination/'docs').mkdir()
    for source in ('reports/runtime/PROTOCOL.md', 'reports/runtime/prompt_archive/PROMPT.long.2026-09-17.md'):
        if (ROOT/source).exists():
            shutil.copy2(ROOT/source, destination/'docs'/Path(source).name)
    local_source = ROOT/'assets'/'source'
    source = local_source if local_source.exists() else ROOT.parent/'mujoco_sim_elevator_button'/'elevators'
    assets = destination/'assets'
    (assets/'source').mkdir(parents=True)
    (assets/'files').mkdir()
    for name in ('home_pose.py', 'button_panel.py'):
        shutil.copy2(source/name, assets/'source'/name)
    manifest = []

    def rewrite(input_path, output_path, relative_dir):
        # Source project has malformed XML comments; MuJoCo tolerates them.
        import re
        root = ET.fromstring(re.sub(r'<!--.*?-->', '', input_path.read_text(), flags=re.S))
        compiler = root.find('compiler')
        original_dirs = {tag: compiler.get(attr, '') for tag, attr in [('mesh', 'meshdir'), ('texture', 'texturedir')]}
        for element in root.iter():
            if 'file' not in element.attrib:
                continue
            if element.tag not in original_dirs:
                raise RuntimeError('unhandled external dependency: '+element.tag)
            original = element.get('file')
            file = (input_path.parent/original_dirs[element.tag]/original).resolve(strict=True)
            digest = hashlib.sha256(file.read_bytes()).hexdigest()
            name = digest[:16]+'_'+file.name
            shutil.copy2(file, assets/'files'/name)
            element.set('file', name)
            manifest.append({'model': output_path.relative_to(destination).as_posix(),
                             'original_reference': original, 'bundled': 'assets/files/'+name,
                             'sha256': digest, 'bytes': file.stat().st_size})
        compiler.set('meshdir', relative_dir)
        compiler.set('texturedir', relative_dir)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ET.indent(root, space='  ')
        ET.ElementTree(root).write(output_path, encoding='unicode')
    rewrite(ROOT/'models/elevator_four_mecanum.xml', destination/'models/elevator_four_mecanum.xml', '../assets/files')
    rewrite(source/'elevator_scene_robot.xml', assets/'source/elevator_scene_robot.xml', '../files')
    (destination/'ASSET_MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n')
    (destination/'SHA256SUMS').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(destination).as_posix()+'\n'
        for p in sorted(destination.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'))
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination')
    args = parser.parse_args()
    destination = assemble(args.destination)
    archive = destination.with_suffix('.tar.gz')
    with tarfile.open(archive, 'w:gz') as out:
        out.add(destination, arcname=destination.name)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name+'.sha256').write_text(checksum+'  '+archive.name+'\n')
    print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size, 'sha256': checksum}))
