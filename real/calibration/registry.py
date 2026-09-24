"""Named, versioned robot configurations; filesystem-only operations."""
from pathlib import Path
from datetime import datetime,timezone
import json,uuid,shutil,hashlib,re
ROOT=Path(__file__).resolve().parents[1]
FILES=('profile.json','calibration/calibration.json','camera-config.json','parameters.json','validation.json','task-pose.json')
def write(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2,ensure_ascii=False));tmp.replace(path)
def read(path,default=None):return json.loads(Path(path).read_text()) if Path(path).exists() else default
def digest(data):return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
class Registry:
 def __init__(self,root=None,demo=False):self.root=Path(root or ROOT/('robots-demo' if demo else 'robots'));self.root.mkdir(parents=True,exist_ok=True);self.demo=demo
 def path(self,name):
  if not isinstance(name,str) or not re.fullmatch(r'[\w-]{1,48}',name) or name.startswith('_'):raise ValueError('名称限1–48个文字、字母、数字、下划线或短横线')
  return self.root/name
 def names(self):return sorted(p.name for p in self.root.iterdir() if p.is_dir() and (p/'profile.json').exists())
 def create(self,name):
  p=self.path(name)
  if any(x.casefold()==name.casefold() for x in self.names()):raise ValueError('该名称已存在，请加载而非覆盖')
  p.mkdir();write(p/'profile.json',dict(name=name,robot_id=uuid.uuid4().hex,demo=self.demo,revision=0,created_utc=datetime.now(timezone.utc).isoformat(),initial_backup=None))
  write(p/'calibration/calibration.json',dict(version=1,mounting='reverse',joints={},wheels={},base={},camera={'status':'not_imported'}));write(p/'camera-config.json',dict(roles_confirmed=False,devices={}));write(p/'validation.json',{})
  return p
 def checkpoint(self,name,reason):
  p=self.path(name);meta=read(p/'profile.json');n=meta['revision']+1;dest=p/'revisions'/f'{n:05d}-{uuid.uuid4().hex[:8]}';dest.mkdir(parents=True)
  for f in FILES:
   if (p/f).exists():out=dest/f;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p/f,out)
  write(dest/'revision.json',dict(reason=reason,utc=datetime.now(timezone.utc).isoformat(),snapshot='before change'))
  meta['revision']=n;write(p/'profile.json',meta);return n
 def fingerprint(self,name,section):
  p=self.path(name);cal=read(p/'calibration/calibration.json',{})
  if section=='camera':value=read(p/'camera-config.json')
  elif section=='joints':value=dict(joints=cal.get('joints'),parameters={k:v for k,v in read(p/'parameters.json',{}).get('motors',{}).items() if v['role'].startswith(('left_','right_','head_'))})
  elif section=='base':value=dict(wheels=cal.get('wheels'),base=cal.get('base'),parameters={k:v for k,v in read(p/'parameters.json',{}).get('motors',{}).items() if v['role'] in ('front_left','front_right','rear_left','rear_right')})
  else:raise ValueError('Unknown section')
  return digest(value)
 def accept(self,name,section,note):
  self.checkpoint(name,'accept '+section);p=self.path(name);data=read(p/'validation.json',{});data[section]=dict(fingerprint=self.fingerprint(name,section),operator_confirmed=True,note=note,utc=datetime.now(timezone.utc).isoformat());write(p/'validation.json',data)
 def status(self,name):
  p=self.path(name);meta=read(p/'profile.json');v=read(p/'validation.json',{})
  return {**meta,'path':str(p),'validation':{s:{'valid':v.get(s,{}).get('fingerprint')==self.fingerprint(name,s),'record':v.get(s)} for s in ('joints','base','camera')},'camera':read(p/'camera-config.json'),'parameters':read(p/'parameters.json'),'revisions':sorted(x.name for x in (p/'revisions').glob('*'))}
 def import_beijing(self):
  if self.demo or 'Beijing' in self.names():return
  p=self.create('Beijing')
  source=ROOT/'calibration/sessions/real-001'
  for f in source.glob('capture-*.json'):shutil.copy2(f,p/'calibration'/f.name)
  if (source/'events.jsonl').exists():shutil.copy2(source/'events.jsonl',p/'calibration/events.jsonl')
  if (source/'camera-import').exists():shutil.copytree(source/'camera-import',p/'calibration/camera-import')
  shutil.copy2(ROOT/'calibration/sessions/real-001/calibration.json',p/'calibration/calibration.json');shutil.copy2(ROOT/'control_api/camera-config.json',p/'camera-config.json');shutil.copy2(ROOT/'control/elevator-task-initial-pose.json',p/'task-pose.json')
  meta=read(p/'profile.json');meta.update(initial_backup=str(ROOT/'register-backups/20260922-094516-before-calibration'),backup_index=str(ROOT/'register-backups/Beijing/INDEX.json'),source='Imported existing Beijing calibration; initial profile was restored by operator request');write(p/'profile.json',meta)
  for s in ('joints','base','camera'):self.accept('Beijing',s,'Historical Beijing verification confirmed by operator; parameters currently restored, reapply before testing.')

def control_digest(cal):return digest({k:cal.get(k) for k in ('joints','wheels','base')})
