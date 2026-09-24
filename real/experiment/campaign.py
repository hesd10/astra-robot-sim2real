"""Operator-only formal queues and immutable input packages. Never drives hardware."""
import json,hashlib,shutil,time,uuid,math
from pathlib import Path
HERE=Path(__file__).resolve().parent
REAL=HERE.parent
SIM=REAL.parent/'sim/studies/body-experience-001'
CONDITIONS={'A':'I0E0','B':'I3E0','C':'I0E3(sim)','D':'I0E3(real)'}
def read(p):return json.loads(Path(p).read_text())
def write(p,data):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.replace(p)
def hashes(root):return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(root).rglob('*')) if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts}
def verify(root,expected):
 actual=hashes(root)
 if actual!=expected:raise ValueError('Frozen material changed: '+str(root))
def source_hashes():
 files=[*HERE.glob('*.py'),*HERE.glob('*.html'),*(HERE/'runtime').glob('*.py'),*(REAL/'control_api').glob('*.py')]
 return {str(p.relative_to(REAL)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
def queue():return [dict(id=f'{i+1:02d}-{g}',group=g,condition=CONDITIONS[g],replicate=(i//3)+1,status='pending',attempts=[]) for i,g in enumerate('ABCBCACAB')]
def freeze(folder,machine):
 folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
 # Only the authorized simulation assets/experience are copied, never old real pilots.
 common=folder/'common';shutil.copytree(HERE/'subject_template',common,ignore=shutil.ignore_patterns('__pycache__'))
 packages=folder/'packages';packages.mkdir()
 for g in 'ABC':(packages/g).mkdir()
 body=packages/'B/prior/body';shutil.copytree(SIM/'body/I3',body)
 (body/'robot/README.md').write_text('''# Simulation robot reference
robot.xml and meshes describe the simulation robot in its chassis frame, not the real lobby. interface_mapping.json maps public physical-side channels to XML joints. Real API joint angles are calibrated XML-reference radians; use the current API schema for actual finite limits. The geometry and camera parameters are simulation references, not newly measured real geometry. No target coordinates, real successful actions or task scene are supplied. Only the public low-level API controls the real robot.
''')
 camera=read(REAL/'calibration/review/simulation-camera-reference.json');camera.pop('source_xml',None);camera['physical_role_mapping']='Confirmed by the operator before experiments; raw camera frames use the public role names.';write(body/'simulation-camera-reference.json',camera)
 exp=SIM/'experience';expected=read(SIM/'experience-manifest.json')['package_sha256']
 verify(exp,expected);shutil.copytree(exp,packages/'C/prior/experience')
 for g in 'ABC':
  bodytext='All files under prior/body/ (simulation reference assets).' if g=='B' else 'No robot model assets.'
  experience='All files under prior/experience/ (ordinary E3 from simulation run be001-source-3; original history is preserved).' if g=='C' else 'No historical experience.'
  (packages/g/'PRIOR.md').write_text(f'# Authorized information\n\nCondition: {CONDITIONS[g]}.\n\nBody information: {bodytext}\n\nHistorical experience: {experience}\n\nHistorical targets, indicator rules and action values describe the source scene. The current PROMPT.md and API.md take precedence. No other material is authorized.\n')
 profile=folder/'robot-profile';(profile/'calibration').mkdir(parents=True)
 original=machine['calibration'].parent.parent/'profile.json'
 meta=read(original) if original.exists() else dict(name=machine['name'],initial_backup=str(machine['backup']))
 write(profile/'profile.json',meta)
 for source,dest in [(machine['calibration'],profile/'calibration/calibration.json'),(machine['cameras'],profile/'camera-config.json'),(machine['pose'],profile/'task-pose.json')]:shutil.copy2(source,dest)
 runtime=source_hashes()
 for rel in runtime:
  dest=folder/'runtime-source'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(REAL/rel,dest)
 manifest=dict(version=1,created_unix=time.time(),robot=machine['name'],target='initial-opposite-down',model='gpt-6-astra',reasoning='xhigh',task_seconds=1800,feedback_policy='silent_retry',common=hashes(common),packages={g:hashes(packages/g) for g in 'ABC'},robot_profile=hashes(profile),runtime=runtime,simulation_experience_source='be001-source-3',simulation_experience_hashes=expected,queue=queue())
 write(folder/'manifest.json',manifest);return manifest

def verify_bundle(folder,group,check_runtime=True):
 folder=Path(folder);m=read(folder/'manifest.json');verify(folder/'common',m['common']);verify(folder/'packages'/group,m['packages'][group]);verify(folder/'robot-profile',m['robot_profile'])
 verify(folder/'runtime-source',m['runtime'])
 if check_runtime and source_hashes()!=m['runtime']:raise ValueError('代码已变化，正式试验已冻结；请创建新批次，或在尚未开始时更新冻结材料。')
 return m

def prepare(destination,folder,group):
 folder=Path(folder);verify_bundle(folder,group);shutil.copytree(folder/'common',destination);shutil.copytree(folder/'packages'/group,destination,dirs_exist_ok=True)
 (destination/'evidence').mkdir();return hashes(destination)

def build_real_experience(folder,attempt):
 """Export public observations/actions only. No private reasoning, recorder or controller code."""
 import cv2,numpy as np
 folder=Path(folder);private=Path(attempt['path'])/'private';result=read(private/'result.json');t0=result['t0'];end=result['terminal']['unix']
 rows=[json.loads(line) for line in (private/'operator-events.jsonl').read_text().splitlines()]
 observations=[r for r in rows if r['kind']=='observation' and t0<=r['unix']<=end]
 if not observations:raise ValueError('Source has no recorded observations')
 folder.mkdir(parents=True,exist_ok=False);timeline=[];synced=[]
 for index,row in enumerate(observations):
  source=Path(row['folder']).resolve()
  if not source.is_relative_to((private/'observations').resolve()):raise ValueError('Unexpected observation source')
  dest=folder/'observations'/f'{index:04d}';dest.mkdir(parents=True)
  for role in ('head','left_wrist','right_wrist'):shutil.copy2(source/(role+'.jpg'),dest/(role+'.jpg'))
  timeline.append(dict(index=index,source_time_seconds=row['unix']-t0,video_time_seconds=row['unix']-observations[0]['unix']))
 for row in rows:
  if not t0<=row['unix']<=end:continue
  if row['kind']=='request':
   request={k:v for k,v in row['request'].items() if k!='id'};reply=row.get('result',{})
   synced.append(dict(source_time_seconds=row['unix']-t0,request=request,reply={'ok':True,'result':reply}))
  elif row['kind']=='operator_event':synced.append(dict(source_time_seconds=row['unix']-t0,operator_event={k:row.get(k) for k in ('outcome','action_id','accepted_unix')}))
 (folder/'synchronized.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in synced))
 write(folder/'timeline.json',dict(kind='sample_and_hold_of_actual_source_observations',columns=['head','left_wrist','right_wrist'],source_start_seconds=timeline[0]['source_time_seconds'],source_finish_seconds=end-t0,observations=timeline))
 writer=cv2.VideoWriter(str(folder/'demonstration.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),2,(960,240))
 if not writer.isOpened():raise RuntimeError('Could not encode E3 observation replay')
 try:
  index=0
  for tick in range(max(1,math.ceil((end-observations[0]['unix'])*2))):
   while index+1<len(timeline) and timeline[index+1]['video_time_seconds']<=tick/2:index+=1
   frame=np.concatenate([cv2.resize(cv2.imread(str(folder/'observations'/f'{index:04d}'/(role+'.jpg'))),(320,240)) for role in ('head','left_wrist','right_wrist')],axis=1);writer.write(frame)
 finally:writer.release()
 (folder/'summary.md').write_text(f'''# One prior real attempt
This is ordinary E3 evidence from formal A attempt {attempt['id']}, not the current state or a reusable controller. The operator reviewed it as a genuine physical press with no strategy hints, manual operation or wrong-button activation. Time to accepted success was {end-t0:.3f} seconds. The task was the DOWN call button on the side opposite the starting position. Success came from the operator, not lamp color. Read synchronized.jsonl and the timestamped onboard observations for the actual actions and states. demonstration.mp4 holds each actual observation until the next; it is not continuous video. No private reasoning, external video, skill or source control program is provided.\n''')
 return dict(source=attempt['id'],selection='fastest reviewed eligible formal A success; ties by queue order',duration_seconds=end-t0,observations=len(observations),sha256=hashes(folder))
