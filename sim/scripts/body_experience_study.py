"""Frozen XLeRobot body/experience study; operator-only autonomous scheduler."""
import argparse, copy, fcntl, json, os, random, shutil, signal, subprocess, sys, time
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from prior_materials import hashes,digest,write_json
import run_prior_comparison as legacy
from account_preflight import preflight
NAME='body-experience-001'
STUDY=ROOT/'studies'/NAME
BATCH=ROOT/'reports/batches'/NAME
OLD=ROOT/'studies/prior-information-001'
CONDITIONS=['I0E0','I1E0','I2E0','I3E0','I0E1','I0E2','I0E3','I3E1','I3E2','I3E3']

def read(p):return json.loads(Path(p).read_text())
def save(s):write_json(BATCH/'status.json',s)
def prepare():
    legacy.validate()
    if STUDY.exists():raise RuntimeError('Study already exists')
    STUDY.mkdir(parents=True)
    shutil.copyfile(OLD/'private-initial-reference.json',STUDY/'private-initial-reference.json')
    shutil.copytree(OLD/'common',STUDY/'common')
    c=STUDY/'common'
    prompt='''Physically control XLeRobot to approach the middle elevator and press only its UP call button. Verify from fresh observations that the target button has turned red before declaring success. Work alone without questions; minimize time and online decisions without damage.

Read API.md and PRIOR.md. Use the shared low-level interface, explicitly supplied information, installed dependencies and code you write. Choose your observation and action strategy freely; no exploration or model-building phase is required. Keep head pan within ±90 degrees of its fresh initial orientation and use the permitted tilt range.

Only the historical material explicitly listed in PRIOR.md is authorized. No other conversations, workspaces, skills, prior Git history, external controllers/information, unprovided simulation internals/assets, datasets, demonstrations, pretrained policies or hidden evaluation. Historical observations are not current observations; verify action results through current feedback. Stop on contamination or unavailable essential capabilities. Never bypass protections or reset; the whole session is one attempt.

On termination, stop safely and call finish. Then save a brief report in evidence/ describing outcome, fresh visual verification, final state, elapsed time, motion commands, decision points and which supplied information was used. Do not produce a skill for another attempt.
'''
    (c/'PROMPT.md').write_text(prompt)
    api=(c/'API.md').read_text();start=api.index('Use a fresh workspace/conversation.');end=api.index('Task completion requires',start)
    api=api[:start]+'''Use a fresh workspace/conversation. Read PRIOR.md for the authorized inputs.
Only the explicitly supplied body description and historical demonstration materials may be used in addition to current-run observations. All other model assets, scene internals, previous workspaces/conversations, external controllers and hidden evaluation remain unavailable. You may infer relationships and write controllers from authorized inputs and current observations. Stop safely on contamination.

There is no required exploration phase. All reading, programming, demonstration viewing, exploration and observations use the same task budget. Do not update or transfer experience onward. After finish, write a brief evidence report; closeout and video export are outside task time. The chassis frame is +X forward, +Y left, +Z up. No environmental geometry measurements are supplied. Historical observations are not current observations.

If historical media are supplied, MEDIA.md describes the common read-only viewing helper and timestamp convention. Every condition has the same helper. No live perception or control is performed by it.

'''+api[end:]
    (c/'API.md').write_text(api)
    (c/'MEDIA.md').write_text('''# Historical media access
If PRIOR.md lists historical media, `python3 media.py` lists observation IDs, task-clock timestamps and file paths in prior/experience/observations/index.json. `python3 media.py INDEX` prints paths for that observation. Open the returned JPEGs using the ordinary image viewer. demonstration.mp4 is a three-camera, sample-and-hold visualization of the same source observations, not a continuous recording; it does not add frames between actual captures. Columns are head, left wrist, right wrist. Its adjacent timeline.json records video seconds and original observation timestamps. Full-resolution original JPEGs are available. No automatic target detection is provided. Historical data describe a previous trial, not this trial's current state.
''')
    (c/'media.py').write_text('''import json,sys
from pathlib import Path
p=Path('prior/experience/observations/index.json')
if not p.exists():
 print('No historical media supplied.')
else:
 rows=json.loads(p.read_text())
 for row in ([rows[int(sys.argv[1])]] if len(sys.argv)>1 else rows):
  print(json.dumps(row))
''')
    for level in range(1,4):
        dest=STUDY/'body'/f'I{level}';dest.mkdir(parents=True)
        (dest/'STRUCTURE.md').write_text('''# XLeRobot structure
Two serial arms mounted on a mobile chassis. Each public arm chain is ordered 1 through 6: shoulder rotation, shoulder pitch, elbow pitch, wrist pitch, wrist roll, jaw actuation. Shoulder rotation provides a swivel; shoulder/elbow/wrist pitch provide bending; wrist roll rotates the distal assembly about its longitudinal direction; the last channel opens/closes the moving jaw relative to the fixed jaw. Encoder sign and physical zero must not be inferred from everyday joint names. The head is chassis-mounted with pan followed by tilt. Camera roles head, left_wrist and right_wrist refer to their physical mounting assembly. Wrist cameras follow the distal arm assemblies. This qualitative description supplies no lengths, calibrated camera parameters or task geometry.
''')
        if level>=2:
            shutil.copytree(OLD/'robot-description',dest/'robot')
            tree=ET.parse(dest/'robot/robot.xml')
            # Mechanical geometry is identical; all calibrated camera nodes are absent in I2.
            if level==2:
                for parent in tree.getroot().iter():
                    for child in list(parent):
                        if child.tag=='camera':parent.remove(child)
                ET.indent(tree,space='  ');tree.write(dest/'robot/robot.xml',encoding='unicode')
                mp=read(dest/'robot/interface_mapping.json');mp.pop('camera_roles_to_xml_camera_names',None);write_json(dest/'robot/interface_mapping.json',mp)
                with (dest/'robot/README.md').open('a') as f:f.write('\nCamera calibration and precise mounting transforms are not supplied; camera nodes have been removed.\n')
    for i in range(4):make_input(f'I{i}E0')
    rng=random.Random(20260920)
    groups=[CONDITIONS[:4],CONDITIONS[4:7],CONDITIONS[7:]]
    shuffled=[]
    for g in groups:
        a=g.copy();rng.shuffle(a);shuffled.append(a)
    batches=[]
    for rep in range(1,4):
        for label,g in zip(['body','experience-I0','experience-I3'],shuffled):
            order=g[rep-1:]+g[:rep-1]
            batches.append({'id':f'r{rep}-{label}','trials':[{'condition':x,'run':f'be001-r{rep}-{x.lower()}','replicate':rep} for x in order]})
    m={'study':NAME,'created_unix':time.time(),'effort':'xhigh','model':'gpt-6-astra','task_seconds':1800,
       'source_runs':[f'be001-source-{i}' for i in range(1,4)],'source_condition':'I0E0',
       'selection':'fastest valid success by sim_seconds to accepted finish; tie by source ID',
       'batches':batches,'common_sha256':hashes(c),'body_sha256':hashes(STUDY/'body'),
       'reference_sha256':digest(STUDY/'private-initial-reference.json'),
       'inputs':{f'I{i}E0':hashes(STUDY/'inputs'/f'I{i}E0') for i in range(4)},
       'legacy_manifest_sha256':digest(OLD/'manifest.json'),'runtime_sha256':read(OLD/'manifest.json')['runtime_sha256'],
       'codex_binary':read(OLD/'manifest.json')['codex_binary'],'codex_binary_sha256':read(OLD/'manifest.json')['codex_binary_sha256'],
       'worker_sha256':digest(__file__),'no_automatic_retries':True,'station':'formal-001 fixed',
       'phase_two':'Not dispatched: station-variation ranges and conditions require separate freeze',
       'autonomous_authorization':'User authorizes sources, frozen same-source E1/E2/E3, all 30 fixed-station tests, analysis without routine reports.'}
    write_json(STUDY/'manifest.json',m)
    (STUDY/'PROTOCOL.zh-CN.md').write_text('''# XLeRobot 身体资料与同源经验实验
新版本 body-experience-001。用户已授权自动完成源采集、经验冻结、30 次正式试验和分析，不逐批询问或汇报。模型 gpt-6-astra，xhigh，任务 1800 秒，收尾另 180 秒。真实结构保持原样。

源试验三次 I0E0；合法成功中按 accepted finish 环境任务时钟选最快，失败不丢弃，不追加直到成功。三次都失败则保留并标记 source_unavailable。源试验不计入正式样本。

I0 接口；I1 定性结构；I2 完整机械模型无相机节点/标定；I3 加相机标定。
E0 无经验；E1 精选同一源试验的文字总结；E2 加机载观测序列视频与原始图像；E3 再加同步 API 请求、状态和反馈。E4 不做。总结不提供数值轨迹/环境坐标，视频只来自受试已观察的机载画面。无私有评估信息、外部录像、模型推理或控制器代码进入经验。E1 总结由操作者代理只根据所选源的可见记录撰写，最多约 800 英文单词，记录出处，所有下游共用同一版本。

每遍先四个 E0 身体条件，再三个 I0 经验条件，再三个 I3 经验条件；共三遍。批内初始顺序用固定种子随机，随后循环换序（四条件仅三遍，不能完全平衡）。每小批次保存分析检查点后自动继续，无成绩筛选或经验迭代。独立新会话。参数冻结前后哈希检查。

失败计入成功率与 1800 秒封顶分数；成功用时另列。三次为探索性样本，报告全部值和离散性。不得把单次初始位置误差当全程精度。固定站位结果是同场景经验复用，含轨迹重用可能；站位波动阶段待单独冻结，当前不混入。
''')
    BATCH.mkdir(parents=True,exist_ok=False)
    save({'status':'prepared','completed':[],'batches_done':[],'active':None,'created_unix':time.time()})
    validate()

def make_input(condition,experience=None):
    dest=STUDY/'inputs'/condition
    if dest.exists():raise RuntimeError('Input exists '+condition)
    shutil.copytree(STUDY/'common',dest)
    i,e=int(condition[1]),int(condition[3]);(dest/'prior').mkdir()
    lines=['# Authorized information','', 'Body information:']
    if i:
        shutil.copytree(STUDY/'body'/f'I{i}',dest/'prior/body');lines+=['- All files under prior/body/']
    else:lines+=['- No additional body description.']
    lines+=['','Historical task experience:']
    if e:
        ex=dest/'prior/experience';ex.mkdir()
        shutil.copyfile(experience/'summary.md',ex/'summary.md');lines+=['- prior/experience/summary.md']
        if e>=2:
            for f in ['demonstration.mp4','timeline.json']:shutil.copyfile(experience/f,ex/f)
            shutil.copytree(experience/'observations',ex/'observations');lines+=['- prior/experience/demonstration.mp4, timeline.json and observations/']
        if e>=3:
            shutil.copyfile(experience/'synchronized.jsonl',ex/'synchronized.jsonl');lines+=['- prior/experience/synchronized.jsonl']
    else:lines+=['- No historical task experience.']
    lines+=['','No external environment position or normal measurements are supplied. Historical observations are not current observations; verify outcomes through current feedback.']
    (dest/'PRIOR.md').write_text('\n'.join(lines)+'\n')

def validate():
    m=read(STUDY/'manifest.json')
    assert digest(__file__)==m['worker_sha256']
    assert hashes(STUDY/'common')==m['common_sha256']
    assert hashes(STUDY/'body')==m['body_sha256']
    assert digest(STUDY/'private-initial-reference.json')==m['reference_sha256']
    assert digest(OLD/'manifest.json')==m['legacy_manifest_sha256']
    for name,h in m['runtime_sha256'].items():assert digest(ROOT/name)==h,name
    assert digest(m['codex_binary'])==m['codex_binary_sha256']
    inputs=dict(m['inputs'])
    if (STUDY/'experience-manifest.json').exists():inputs.update(read(STUDY/'experience-manifest.json')['inputs'])
    for condition,hs in inputs.items():
        dest=STUDY/'inputs'/condition
        assert hashes(dest)==hs,condition
        for f,h in m['common_sha256'].items():assert digest(dest/f)==h
        assert not any(x.is_symlink() for x in dest.rglob('*'))
        if condition[1]=='2':assert not ET.parse(dest/'prior/body/robot/robot.xml').findall('.//camera')
    return m,inputs

def summary(run,condition):
    _,inputs=validate()
    return legacy.summarize(ROOT/'experiments'/run,{'sha256':inputs[condition]})

def analysis(state):
    rows=[]
    for t in state['completed']:
        if t['phase']=='source':continue
        z=t['result'];rows.append(f"| {t['run']} | {t['condition']} | {z['physical_success']} | {z['sim_seconds']:.3f} | {z['motion_commands']} | {z['observation_groups']} |")
    (BATCH/'RESULTS.md').write_text('# Fixed-station results\n\nExploratory independent trials; no causal significance claim from three samples. Source runs excluded.\n\n| Run | Condition | Physical success | Finish seconds | Motions | Observations |\n|---|---|---|---:|---:|---:|\n'+'\n'.join(rows)+'\n')
    write_json(BATCH/'results.json',{'study':NAME,'trials':state['completed']})

def run_phase(phase):
    with (ROOT/'experiments/.iterations.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        m,inputs=validate();s=read(BATCH/'status.json')
        if s.get('active'):raise RuntimeError('Active or interrupted trial requires audit; never rerun silently')
        if phase=='source':
            if s['status']!='prepared':raise RuntimeError('Source phase already dispatched')
            batches=[{'id':'source','trials':[{'run':x,'condition':'I0E0','replicate':i+1} for i,x in enumerate(m['source_runs'])]}]
        else:
            if s['status']!='experience_frozen':raise RuntimeError('Experience not frozen or evaluation already dispatched')
            batches=m['batches']
        process=None
        try:
            for batch in batches:
                for trial in batch['trials']:
                    validate()
                    if shutil.disk_usage(ROOT).free < 15*1024**3:raise RuntimeError('Insufficient free disk')
                    quota=preflight()
                    if quota['minimum_remaining_percent']<=0 or quota.get('spend_control_reached'):raise RuntimeError('Quota unavailable; no reset credits authorized')
                    if s.get('account_fingerprint',quota['account_fingerprint'])!=quota['account_fingerprint']:raise RuntimeError('Account changed')
                    s['account_fingerprint']=quota['account_fingerprint']
                    name=trial['run'];condition=trial['condition']
                    if (ROOT/'experiments'/name).exists():raise RuntimeError('Trial exists: '+name)
                    cmd=[sys.executable,'-u',str(ROOT/'scripts/start_prior_experiment.py'),name,'--input-dir',str(STUDY/'inputs'/condition),'--reference',str(STUDY/'private-initial-reference.json'),'--setup',str(ROOT/'setups/formal-001.json'),'--max-seconds','1800','--reasoning','xhigh']
                    active={**trial,'phase':phase,'batch':batch['id'],'started_unix':time.time(),'quota_before':quota,'command':cmd}
                    s.update(status='running_'+phase,pid=os.getpid(),active=active);save(s)
                    with (BATCH/(name+'.log')).open('x') as log:
                        process=subprocess.Popen(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
                        active['pid']=process.pid;save(s)
                        while process.poll() is None:
                            if time.time()-active['started_unix']>4500:raise TimeoutError('Launcher/export watchdog')
                            s['last_checked_unix']=time.time();save(s);time.sleep(5)
                        if process.returncode:raise RuntimeError('Launcher failure '+name)
                        process=None
                    result=summary(name,condition)
                    s['completed'].append({**active,'ended_unix':time.time(),'result':result});s['active']=None;save(s);analysis(s)
                s['batches_done'].append(batch['id']);save(s)
                write_json(BATCH/(batch['id']+'-checkpoint.json'),{'completed_unix':time.time(),'input_integrity_passed':True,'completed_trials':len(s['completed']),'continue_authorized':True})
            if phase=='source':
                valid=[t for t in s['completed'] if t['phase']=='source' and t['result']['success_and_correct_declaration']]
                if valid:
                    chosen=min(valid,key=lambda t:(t['result']['sim_seconds'],t['run']))
                    s.update(status='awaiting_experience',selected_source=chosen['run'])
                else:s['status']='source_unavailable'
            else:s['status']='completed_awaiting_analysis'
            s['ended_unix']=time.time();save(s)
        except BaseException as exc:
            if process and process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:process.wait(timeout=45)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGTERM)
            s.update(status='needs_audit',error=repr(exc));save(s);raise

def detach(phase):
    validate();s=read(BATCH/'status.json')
    expected='prepared' if phase=='source' else 'experience_frozen'
    if s['status']!=expected:raise RuntimeError('Wrong state '+s['status'])
    directory=BATCH/(phase+'-launch');directory.mkdir(exist_ok=False)
    cmd=['systemd-inhibit','--what=sleep:idle','--mode=block','--why=XLeRobot autonomous body experience study',str(ROOT.parent/'run-local.sh'),'scripts/body_experience_study.py','worker',phase]
    with (directory/'background.log').open('x') as log:p=subprocess.Popen(cmd,cwd=ROOT.parent,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    receipt={'pid':p.pid,'command':cmd,'started_unix':time.time()};write_json(directory/'launch.json',receipt);print(json.dumps(receipt))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','validate','start','worker']);p.add_argument('phase',nargs='?',choices=['source','evaluation']);a=p.parse_args()
    if a.mode=='prepare':prepare()
    elif a.mode=='validate':validate();print('Frozen materials and runtime verified')
    elif a.mode=='start':detach(a.phase)
    else:run_phase(a.phase)
