"""Formal study controller: manual starts, reviewed outcomes, frozen materials."""
import copy,json,time,hashlib,shutil
from pathlib import Path
from controller import Controller,initialize_subject,REAL
from machine import paths as machine_paths
import campaign as study

class FormalController(Controller):
 def __init__(self,root,mode='demo',**kw):
  existing=Path(root)/'campaign.json'
  if existing.exists() and study.read(existing).get('purpose')!='formal' and bool(study.read(existing).get('attempts')):raise ValueError('正式实验必须使用独立记录目录')
  super().__init__(root,mode,**kw)
  self.live_machine=self.machine if mode=='demo' or __import__('os').environ.get('ASTRA_ROBOT_PROFILE') else machine_paths(REAL/'robots/Beijing')
  if 'queue' not in self.data:
   bundle=self.root/'bundles'/('setup-'+str(time.time_ns()));manifest=study.freeze(bundle,self.live_machine)
   self.data.update(purpose='formal',queue=study.queue(),bundle=str(bundle),manifest_sha256=hashlib.sha256((bundle/'manifest.json').read_bytes()).hexdigest(),d_status='not_decided',reviews=[])
  self.bundle=Path(self.data['bundle']);self._check_manifest();self.profile_dir=self.bundle/'robot-profile';self.machine=machine_paths(self.profile_dir)
  for row in self.data['attempts']:
   if row.get('status')!='interrupted':continue
   log=Path(row['path'])/'private/operator-events.jsonl'
   if not log.exists():continue
   events=[]
   for line in log.read_text().splitlines():
    try:events.append(json.loads(line))
    except ValueError:pass
   t0=next((e['t0'] for e in events if e.get('kind')=='task_started'),None)
   terminal=next((e for e in reversed(events) if e.get('kind')=='terminal'),None)
   if t0 is not None:row['result']=dict(t0=t0,terminal=terminal or dict(outcome='failure',source='infrastructure_error',unix=events[-1]['unix']),events=[e for e in events if e.get('kind')=='operator_event'])
  for slot in self.data['queue']:
   if slot['status']=='running':slot['status']='review'
  self.persist()
 def _check_manifest(self):
  if hashlib.sha256((Path(self.data['bundle'])/'manifest.json').read_bytes()).hexdigest()!=self.data['manifest_sha256']:raise ValueError('正式材料清单被修改')
 def next_slot(self):return next((s for s in self.data['queue'] if s['status']!='done'),None)
 def attempt_spec(self,index):
  self._check_manifest();slot=self.next_slot()
  if slot is None:raise ValueError('本批次已完成；可评估是否追加 D 组')
  if slot['status']!='pending':raise ValueError('先核实上一轮结果，再继续队列')
  study.verify_bundle(self.bundle,slot['group'])
  for key in ('calibration','cameras','pose'):
   if self.live_machine[key].read_bytes()!=self.machine[key].read_bytes():raise ValueError('机器标定/相机已变化，请核对冻结配置，不能在同一正式批次中静默切换')
  return dict(id=f'formal-{slot["id"]}-try{len(slot["attempts"])+1:02d}',slot_id=slot['id'],group=slot['group'],replicate=slot['replicate'],condition=slot['condition'],purpose='formal',setup_manifest_sha256=self.data['manifest_sha256'])
 def prepare_inputs(self,destination):
  study.prepare(destination,self.bundle,self.next_slot()['group']);return initialize_subject(destination)
 def start(self,prepare_only=True):
  with self.lock:
   if not prepare_only:raise ValueError('正式实验必须先准备姿态，再由操作者点击开始')
   slot=self.next_slot();name=super().start(prepare_only=True)
   slot['status']='running';slot['attempts'].append(name);self.persist();return name
 def attempt_finished(self):
  with self.lock:
   row=self.data['attempts'][-1];slot=next(s for s in self.data['queue'] if s['id']==row['slot_id']);slot['status']='review';self.persist()
 def review(self,attempt_id,outcome,eligible=False,note=''):
  with self.lock:
   if self.thread and self.thread.is_alive():raise ValueError('等本轮收尾完成后再核实')
   slot=self.next_slot()
   if slot is None or slot['status']!='review' or slot['attempts'][-1]!=attempt_id:raise ValueError('不是当前待核实试验')
   if outcome not in ('success','failure','retry'):raise ValueError('Invalid reviewed result')
   row=next(a for a in self.data['attempts'] if a['id']==attempt_id);result=row.get('result') or {};terminal=result.get('terminal') or {};started=result.get('t0') is not None
   if outcome=='success' and (not started or terminal.get('outcome')!='success'):raise ValueError('成功需要任务内的操作者成功事件；不能把事后判断补成在线成功')
   if outcome=='retry' and (not isinstance(note,str) or not note.strip()):raise ValueError('重试/补测须说明原因，原记录保留')
   if started and outcome=='retry' and terminal.get('source') not in ('infrastructure_error','runner_error','operator:stop'):raise ValueError('任务失败不可重试择优；仅独立故障或现场中止可注明原因补测')
   if not started and outcome!='retry':raise ValueError('尚未开始正式计时，应保留准备记录并重试本项')
   record=dict(attempt_id=attempt_id,outcome=outcome,eligible=bool(eligible and outcome=='success'),note=str(note)[:2000],unix=time.time(),started=started)
   row['review']=record;self.data['reviews'].append(record);slot['status']='pending' if outcome=='retry' else 'done';self.persist();return record
 def d_candidates(self):
  candidates=[]
  for row in self.data['attempts']:
   review=row.get('review',{});result=row.get('result') or {};terminal=result.get('terminal') or {}
   if row.get('group')!='A' or review.get('outcome')!='success' or not review.get('eligible') or row.get('status')!='completed':continue
   private=Path(row['path'])/'private'
   if not (private/'operator-events.jsonl').exists() or not list((private/'observations').glob('*/metadata.json')):continue
   if self.mode=='real':
    status=study.read(private/'recording-result.json') if (private/'recording-result.json').exists() else {}
    if status.get('error') or not all(status.get('frames',{}).get(r,0)>0 for r in ('head','left_wrist','right_wrist')):continue
   if terminal.get('outcome')=='success' and result.get('t0') is not None:candidates.append(row)
  return sorted(candidates,key=lambda a:((a['result']['terminal']['unix']-a['result']['t0']),a['slot_id']))
 def append_d(self):
  with self.lock:
   if self.thread and self.thread.is_alive():raise ValueError('试验进行中')
   if self.data['d_status']!='not_decided':raise ValueError('D 组已决定，不重复追加')
   if any(s['status']!='done' for s in self.data['queue']):raise ValueError('先完成并核实九次 A/B/C')
   self._check_manifest()
   for g in 'ABC':study.verify_bundle(self.bundle,g)
   candidates=self.d_candidates()
   if not candidates:raise ValueError('正式 A 组没有记录完整且经你确认合格的成功案例，不追加 D')
   source=candidates[0];package=self.bundle/'packages/D'
   if package.exists():raise ValueError('存在未完成的 D 材料生成记录，请检查，不能覆盖')
   package.mkdir();evidence=study.build_real_experience(package/'prior/experience',source)
   (package/'PRIOR.md').write_text('# Authorized information\n\nCondition I0E3(real). No robot model assets. All files under prior/experience/ are ordinary E3 from one prior formal real A success. Historical observations and commands are not current state; current PROMPT.md and API.md take precedence. No other material is authorized.\n')
   m=study.read(self.bundle/'manifest.json');study.write(self.bundle/'manifest-before-D.json',m);m['packages']['D']=study.hashes(package);m['real_experience']=evidence;study.write(self.bundle/'manifest.json',m)
   self.data['manifest_sha256']=hashlib.sha256((self.bundle/'manifest.json').read_bytes()).hexdigest();self.data['d_status']='appended';self.data['d_source']=source['id'];self.data['queue'] += [dict(id=f'{10+i:02d}-D',group='D',condition=study.CONDITIONS['D'],replicate=i+1,status='pending',attempts=[]) for i in range(3)];self.persist();return evidence
 def skip_d(self):
  with self.lock:
   if self.next_slot() is not None or self.data['d_status']!='not_decided':raise ValueError('先完成九次，且 D 尚未决定')
   self.data['d_status']='skipped';self.persist()
 def refresh_setup(self):
  with self.lock:
   if self.data['attempts'] or self.service:raise ValueError('已有准备/试验记录，须创建新批次，不覆盖本批次')
   folder=self.root/'bundles'/('setup-'+str(time.time_ns()));study.freeze(folder,self.live_machine);self.data['bundle']=str(folder);self.data['manifest_sha256']=hashlib.sha256((folder/'manifest.json').read_bytes()).hexdigest();self.bundle=folder;self.profile_dir=folder/'robot-profile';self.machine=machine_paths(self.profile_dir);self.persist()
 def snapshot(self):
  result=super().snapshot();result['next_slot']=copy.deepcopy(self.next_slot());result['completed_slots']=sum(s['status']=='done' for s in self.data['queue']);result['d_candidate']=next((a['id'] for a in self.d_candidates()),None)
  summaries={}
  for g in 'ABCD':
   trials=[a for a in self.data['attempts'] if a.get('group')==g and a.get('review',{}).get('outcome') in ('success','failure')];durations=[a['result']['terminal']['unix']-a['result']['t0'] for a in trials if a['review']['outcome']=='success'];summaries[g]=dict(reviewed=len(trials),successes=len(durations),success_seconds=durations,score_seconds=[a['result']['terminal']['unix']-a['result']['t0'] if a['review']['outcome']=='success' else 1800 for a in trials])
  result['summary']=summaries;return result
