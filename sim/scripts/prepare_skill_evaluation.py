"""Freeze inputs and an operator-only held-out 24-trial plan. Never launches Astra."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'studies/skill-evaluation-001'
IND=ROOT/'studies/skill-induction-001'
SOURCE=ROOT/'studies/body-experience-001/inputs/I0E3'

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def hashes(p):return {str(f.relative_to(p)):digest(f) for f in sorted(p.rglob('*')) if f.is_file() and '__pycache__' not in f.parts}
def write(p,x):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')

def build_trials():
    # Expose one pair per radius first; all first measurements precede repeats.
    order=[f'N{radius:03d}-P{point}' for point in [1,2] for radius in [10,50,100]]
    trials=[]
    for repeat in [1,2]:
        for i,point in enumerate(order):
            conditions=['E3','SKILL'] if (i+repeat)%2 else ['SKILL','E3']
            phase=('initial_comparisons' if i<3 else 'remaining_first_measurements') if repeat==1 else 'repeat_measurements'
            for c in conditions:
                trials.append({'run':f'se001-t{len(trials)+1:03d}',
                               'point':point,'repeat':repeat,'condition':c,'phase':phase})
    return trials

def validate():
    assert digest(OUT/'manifest.json')==json.loads((OUT/'SEAL.json').read_text())['manifest_sha256'],'manifest changed'
    m=json.loads((OUT/'manifest.json').read_text())
    for key in ['inputs','setups','references']:
        assert hashes(OUT/key)==m[key+'_sha256'],key
    for f,h in m['frozen_files'].items():assert digest(ROOT/f)==h,f
    assert hashes(SOURCE/'prior')==m['original_E3_sha256']
    for name in ['PROMPT.md','API.md','robot.py','MEDIA.md','media.py']:
        assert (OUT/'inputs/E3'/name).read_bytes()==(OUT/'inputs/SKILL'/name).read_bytes()
    assert len(m['trials'])==24
    assert m['trials']==build_trials(),'comparison-first schedule changed'
    print('PASS: frozen inputs, runtime, positions and 24-trial plan unchanged; no trial launched')
    return m

def prepare():
    import mujoco
    import numpy as np
    from PIL import Image, ImageDraw
    from sim_env.core import Core
    from sim_env.rendering import follow_camera
    from prior_materials import initial_target, prepare_subject
    from prior_service import verify_initial
    assert not (OUT/'manifest.json').exists(),'Do not overwrite a frozen study'
    assert json.loads((IND/'development/dev008-stop-recovery/recovery-check.json').read_text())['passed']
    guard=json.loads((IND/'development/dev009-guard-recovery/calls.json').read_text())[-1]['result']
    assert guard['code']=='pose_drift' and guard['recovery']['command_stop_confirmed'] and 'observation' in guard
    assert json.loads((IND/'development/dev009-guard-recovery/simulation/result.json').read_text())['stopped']
    for c in ['E3','SKILL']:
        folder=OUT/'inputs'/c;folder.mkdir(parents=True,exist_ok=False)
        for name in ['PROMPT.md','API.md','robot.py','MEDIA.md','media.py']:
            shutil.copyfile(SOURCE/name,folder/name)
        prompt=(folder/'PROMPT.md').read_text().replace('Only the historical material explicitly listed in PRIOR.md is authorized.',
            'Only the historical material and executable skill bundle explicitly listed in PRIOR.md are authorized. Supplied numeric action templates are permitted. Keep supplied input files unchanged; put your own code and evidence elsewhere in this workspace.')
        (folder/'PROMPT.md').write_text(prompt)
        api=(folder/'API.md').read_text().replace('Only the explicitly supplied body description and historical demonstration materials may be used in addition to current-run observations.',
            'Only the information, historical demonstrations and executable action skills explicitly listed in PRIOR.md may be used in addition to current-run observations. Numeric action templates in an authorized skill are permitted. Decide from current observations whether and how to use supplied material; a skill call completing does not establish task success. Keep supplied input files unchanged and write new code/evidence separately.')
        (folder/'API.md').write_text(api)
    shutil.copytree(SOURCE/'prior',OUT/'inputs/E3/prior')
    shutil.copyfile(SOURCE/'PRIOR.md',OUT/'inputs/E3/PRIOR.md')
    bundle=OUT/'inputs/SKILL/skill/xlerobot-action-primitives'
    shutil.copytree(IND/'prototype/xlerobot-action-primitives',bundle,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (OUT/'inputs/SKILL/PRIOR.md').write_text('''# Authorized information

Body information: no additional body description.

Action experience: skill/xlerobot-action-primitives/SKILL.md and its referenced
interface documentation and executable motion_skills.py. Read the skill entrypoint
to learn the available calls. You may choose these calls, the low-level API, or
your own code as appropriate. No historical images or raw action records are supplied.

No external environment position or normal measurements are supplied. The supplied
action templates are historical experience, not a measurement of current geometry.
Choose direction, clearance, observation, recovery and task completion from current
feedback. Do not modify the supplied bundle or transfer experience to another run.
''')
    ref=json.loads((ROOT/'studies/body-experience-001/private-initial-reference.json').read_text())
    model=ROOT/'models/elevator_four_mecanum.xml'
    m=mujoco.MjModel.from_xml_path(str(model));d=mujoco.MjData(m)
    q=int(m.joint('base_free').qposadr[0]);origin=np.array(ref['qpos'][q:q+2])
    robot=set()
    for b in range(m.nbody):
        a=b
        while a:
            if m.body(a).name=='chassis':robot.add(b);break
            a=int(m.body_parentid[a])
    def clear(offset):
        d.qpos[:]=ref['qpos'];d.qpos[q:q+2]+=offset;mujoco.mj_forward(m,d)
        for contact in d.contact:
            g1,g2=int(contact.geom1),int(contact.geom2)
            if (int(m.geom_bodyid[g1]) in robot)==(int(m.geom_bodyid[g2]) in robot):continue
            if 'floor' in [m.geom(g1).name,m.geom(g2).name]:continue
            if contact.dist<=0:return False
        return True
    rng=random.Random(2026092101);points=[];attempts=[];panels=[]
    old=json.loads((ROOT/'studies/position-perturbation-001/positions.json').read_text())['points']
    for radius in [.1,.5,1.]:
        for attempt in range(10000):
            angles=[rng.uniform(0,360) for _ in range(2)]
            sep=abs((angles[0]-angles[1]+180)%360-180)
            offsets=[radius*np.array([math.cos(math.radians(a)),math.sin(math.radians(a))]) for a in angles]
            reason=None
            if sep<60:reason='within-ring separation below 60 degrees'
            elif any(np.linalg.norm(origin+o-np.array(p['world_xy_m']))<1e-6 for o in offsets for p in old):reason='duplicate old point'
            elif not all(clear(o*f) for o in offsets for f in np.linspace(0,1,math.ceil(radius/.01)+1)):reason='initial/corridor collision'
            attempts.append({'radius_m':radius,'angles_deg':angles,'accepted':reason is None,'reason':reason})
            if reason is None:break
        else:raise RuntimeError('sampling exhausted')
        for i,(angle,o) in enumerate(zip(angles,offsets),1):
            ident=f'N{round(radius*100):03d}-P{i}'
            cfg={'standoff':2.4-float(o[1]),'lateral':.75+float(o[0]),'yaw':math.radians(8.)}
            setup={'name':ident,'description':'Operator-only held-out translated start; original yaw and arm posture.',
                   'initialization':{'standoff_m':cfg['standoff'],'lateral_m':cfg['lateral'],'yaw_deg':8.}}
            write(OUT/'setups'/f'{ident}.json',setup)
            core=Core(**cfg,max_seconds=1800.)
            rpath=OUT/'references'/ident/'private-initial-reference.json'
            write(rpath,{'public_measurement':initial_target(core.m,core.d),'qpos':core.d.qpos.tolist(),'qvel':core.d.qvel.tolist(),'ctrl':core.d.ctrl.tolist()})
            audit=verify_initial(Core(**cfg,max_seconds=1800.),rpath)
            points.append({'id':ident,'radius_m':radius,'angle_world_deg':angle,'world_xy_m':(origin+o).tolist(),'initial_reference_audit':audit})
            with mujoco.Renderer(core.m,height=480,width=640) as renderer:
                panel=Image.new('RGB',(640,265),'white')
                for j,cam in enumerate([follow_camera(core.m,core.d),'head']):
                    renderer.update_scene(core.d,camera=cam)
                    panel.paste(Image.fromarray(renderer.render()).resize((320,240)),(j*320,25))
                ImageDraw.Draw(panel).text((5,5),f'{ident} / {angle:.2f} deg / operator-only view + head',fill='black')
                panels.append(panel)
    write(OUT/'positions.json',{'seed':2026092101,'selection':'two uniform angles per ring; reject entire pair for separation <60deg, collision or duplicate; no performance-based selection','sampling_attempts':attempts,'points':points})
    sheet=Image.new('RGB',(640,265*6),'white')
    for i,p in enumerate(panels):sheet.paste(p,(0,i*265))
    sheet.save(OUT/'positions-review.jpg')
    trials=build_trials()
    # Verify ordinary subject packaging without launching a service or model.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='skill-freeze-') as temp:
        for c in ['E3','SKILL']:
            prepare_subject(Path(temp)/c,OUT/'inputs'/c,hashes(OUT/'inputs'/c))
    files=[OUT/'positions.json',OUT/'PROTOCOL.zh-CN.md',Path(__file__),ROOT/'scripts/start_skill_trial.py']
    for folder in ['models','assets','sim_env']:
        files += [f for f in (ROOT/folder).rglob('*') if f.is_file() and '__pycache__' not in f.parts]
    files += [ROOT/'scripts'/f for f in ['start_prior_experiment.py','prior_service.py','prior_materials.py','wheel_contact_model.py']]
    manifest={'study':'skill-evaluation-001','created_at_utc':datetime.now(timezone.utc).isoformat(),
              'status':'frozen_not_started','model':'gpt-6-astra','effort':'xhigh','task_seconds':1800,'session_seconds':1980,
              'skill_version':'0.2.0-sim','trials':trials,'independent_attempts':True,'source_E3':'be001-source-3',
              'schedule_revision':2,
              'schedule_policy':'10/50/100cm P1 paired first measurements; then P2 first measurements; all repeats last; reverse within-point order on repeat.',
              'pair_review_checkpoints':[{'after_run':trials[i]['run'],'point':trials[i]['point'],'review_before_next_pair':True} for i in [1,3,5,7,9,11]],
              'comparison_scope':'practical package comparison; skill induced from broader corpus, not isolated representation effect',
              'original_E3_sha256':hashes(SOURCE/'prior'),'frozen_files':{str(f.relative_to(ROOT)):digest(f) for f in files},
              **{k+'_sha256':hashes(OUT/k) for k in ['inputs','setups','references']}}
    write(OUT/'manifest.json',manifest)
    write(OUT/'SEAL.json',{'manifest_sha256':digest(OUT/'manifest.json')})
    validate()

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--validate',action='store_true');a=ap.parse_args()
    validate() if a.validate else prepare()
