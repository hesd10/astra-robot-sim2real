"""Build auditable single-source materials; never executes a robot/model trial."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT/'studies/experience-reflection-001'
OLD = ROOT/'studies/skill-evaluation-001'
SOURCE = ROOT/'studies/body-experience-001/inputs/I0E3/prior/experience'
SELECTED = [0, 1, 2, 8, 10, 11, 12, 13, 15, 16, 17, 20, 21]
COMMON = ['PROMPT.md', 'API.md', 'robot.py', 'MEDIA.md', 'media.py']
BASELINES = {'N010-P1':'se001-t001','N050-P1':'se001-t004','N100-P1':'se001-t005',
             'N010-P2':'se001-t008','N050-P2':'se001-t009','N100-P2':'se001-t012'}

def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def hashes(p): return {str(f.relative_to(p)):digest(f) for f in sorted(p.rglob('*')) if f.is_file() and '__pycache__' not in f.parts}
def read(p): return json.loads(p.read_text())
def write(p, x):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(x, indent=2, ensure_ascii=False)+'\n')
def words(t): return len(re.findall(r"\b[\w]+(?:[-'][\w]+)*\b",t))
def build_trials():
    trials=[]
    for i,point in enumerate(BASELINES):
        for c in (['C','R'] if i%2==0 else ['R','C']):
            trials.append(dict(run=f'er001-t{len(trials)+1:03d}', point=point, repeat=1,
                               condition=c, phase='first_measurements'))
    return trials

# Analyst judgments refer only to source onboard images and public requests.
# These are retrospective availability checks, not blinded original reasoning.
ANNOTATIONS = [
 ('门序未确认；初始窄视野','转头获取邻门参照','头图出现走廊端部/邻门；腕图近似未变','无法判断','场景身份信息'),
 ('已有一侧邻门参照','查看另一侧门序','头图转向另一侧的门与面板；腕图近似未变','无法判断','场景身份信息'),
 ('两侧头图已获得','重新朝向面板并前进','头部俯仰及底盘都改变，画面含较多地面','无法判断','前进与视角效果不可拆分'),
 ('目标面板较小，腕视野朝地面','部署手臂并前进','头图面板变大，腕视野朝向发生变化','改善','混合变化不能标定单关节效果'),
 ('面板变大，手臂尚在调整','调整关节及继续前进','腕视角旋转，头图面板仍可见','无法判断','混合底盘和关节变化'),
 ('腕图旋转，头图可见面板','调整手臂并横移','腕图重新较直立，面板落入腕视野','改善','混合变化；不可推出通用侧向符号'),
 ('双视图含目标但尚未接触','继续前进并转头/改关节','面板尺度增大，腕图面板在左上区域','改善','多个量同变'),
 ('目标可见但未接触','对角前进并调整俯仰','腕图面板接近指尖画面区域，头图尺度增大','改善','头图变化含相机俯仰'),
 ('目标近，姿态仍需检查','更改right_2和right_3','图像相对关系变化，未出现红灯','无法判断','无底盘命令，关节联合作用'),
 ('面板在头图中可见','更改头俯仰及腕关节','头图朝地面失去面板，腕图仍含面板','恶化','仅指头图目标可见性恶化；机械进展无法判断'),
 ('头图失去面板，腕图可见','恢复有用视角并调整臂','头图重见面板，腕图面板位于指尖之间较低处','改善','视角信息改善；不能分离多个关节作用'),
 ('双视图含目标，姿态可比较','更换工作姿态','头图出现向前伸出的手臂/夹爪，腕图清楚显示双按钮','改善','终点构型有用，不证明从初态直达路径'),
 ('固定工作姿态，双按钮白框','保持臂目标并对角移动','腕图面板变大/靠近指尖；头图相对关系改变','改善','此段无move，较清楚的底盘效果案例'),
 ('面板更近，按钮未亮','小改right_4并前进','指尖相对面板位置变化，仍未亮','无法判断','腕关节与底盘同时变化'),
 ('按钮未亮且接近','回调right_4并短前进','到达后续保持的工作目标，图像更靠近','改善','不能只归因于底盘或腕关节之一'),
 ('臂目标固定，按钮白框','两次短前进','面板尺度增大/相对指尖更近，仍白框','改善','无move；不等于测得位移'),
 ('更近但未亮，臂目标固定','降低速度两次前进','相邻头/腕图变化较小，按钮仍白框','无明显变化','未标定像素或力，不推断死区成因'),
 ('低速段视觉变化小','提高速度但缩短时长','面板相对夹爪略变，仍未亮','改善','定性轻微变化，不量化距离'),
 ('按钮白框，仍需接触','同速度更长前进','头图指尖覆盖上按钮区域，边框仍白','改善','接触外观不等于激活'),
 ('指尖重叠但白框','再短前进','仍重叠白框，外观变化小','无明显变化','未验证能否与邻步合并'),
 ('上按钮重叠白框，臂目标保持','一次0.8秒前进','头/腕上按钮出现红边框，下框可见部分白','改善','物理激活外观证据；只验证此前状态下该步'),
]

FACTS = '''# Source facts and image index

All evidence comes from be001-source-3. The source ends with finish(success) at 638.352 s. Historical images are not current observations. Numeric targets below are recorded endpoints, not a tested shortcut from the current posture. Durations are requested time, not measured displacement. No environment geometry or current target location is supplied.

| Stage | Original observation IDs | Evidence |
|---|---|---|
| Elevator row | 0000, 0001, 0002 | Initial view; two head-only scans |
| Arm and viewing changes | 0008, 0010, 0011, 0012 | Panel visibility and arm configuration changes |
| Approach | 0012, 0013, 0015 | Held-arm base segment; subsequent wrist adjustments |
| Short motion | 0015, 0016, 0017 | Visible approach followed by little visible change |
| Activation | 0020, 0021 | White overlap before the final request; red afterward |

The original full-resolution HEAD and RIGHT_WRIST JPEGs for each retained ID are under observations/ID/. The index retains all original IDs and timestamps; omitted image sets have empty files dictionaries. python3 media.py ID returns the original ID's retained paths, if any. No demonstration.mp4 or timeline.json is included in this package. The shared MEDIA.md describes the original optional movie format; this package supplies JPEGs only.

actions.json records ALL source move/base/stop/finish requests, including exploration, exact timestamps, source line numbers and acknowledgements. Gaps between requests include observation/interaction time and are not instructions to wait. snapshots.json separates the commanded targets accumulated from accepted requests before each image from older measured joint feedback. Commanded targets are not measured positions. Feedback has its own timestamp and age; some feedback is tens of seconds older than the image. Do not treat those measurements as simultaneous image poses. Both fields are historical public records, not calibrated geometry.

Recorded working right-arm target vector at 0015 and 0021, ordered right_1..right_6:
[-1.5707963267948966, 1.0, 1.2, -0.84, 1.5707963267948966, -0.374533].
At 0012, right_4 is -0.72 instead. The preceding move from 0011 commanded right_2=1.0, right_3=1.2, right_4=-0.72 for 7.4 s. It followed the earlier source exploration; it was not a direct move from the source initial pose. Current API speed/acceleration limits and current state still govern a new movement.

The source used right-arm motions and zero base yaw. In the final retained interval, source time 619.046 s, the request was base(vx=0.05, vy=0.01, wz=0, duration=0.8). Observation 0021 at 620.054 s then shows red. Stop and finish follow at 638.341 and 638.352 s. This is one observed sequence, not a general displacement calibration or a command to replay the full path.
'''

def prepare():
    assert not (OUT/'manifest.json').exists(), 'Frozen study already exists'
    from prepare_skill_evaluation import validate as old_validate
    old_m=old_validate()
    ds=[json.loads(l) for l in (SOURCE/'synchronized.jsonl').read_text().splitlines()]
    idx=read(SOURCE/'observations/index.json')
    assert len(idx)==22 and len(ANNOTATIONS)==21
    actions=[dict(source_line=i+1, source_time_seconds=d['source_time_seconds'], request=d['request'],
                  accepted=d['reply']['ok'], action_number=d['reply'].get('result',{}).get('action_number'))
             for i,d in enumerate(ds) if d.get('request',{}).get('op') in ['move','base','stop','finish']]
    snapshots=[];ledger=[]
    initial=next(d['reply']['result'] for d in ds if d.get('request',{}).get('op')=='state')
    for i,o in enumerate(idx):
        states=[(n+1,d) for n,d in enumerate(ds) if d.get('request',{}).get('op')=='state' and d['source_time_seconds']<=o['source_time_seconds']]
        line,st=states[-1];state=st['reply']['result']
        if i in SELECTED:
            commanded={k:v['target'] for k,v in initial['joints'].items() if k.startswith(('right_','head_'))}
            target_lines=[]
            for a in actions:
                if a['source_time_seconds']<=o['source_time_seconds'] and a['request']['op']=='move' and a['accepted']:
                    commanded.update({k:v for k,v in a['request']['targets'].items() if k in commanded})
                    target_lines.append(a['source_line'])
            snapshots.append(dict(observation_index=i,image_time=o['source_time_seconds'],state_source_line=line,
                commanded_targets_at_capture_not_measured=commanded,target_update_source_lines=target_lines,
                older_measured_feedback=dict(state_time=st['source_time_seconds'],age_at_image_seconds=o['source_time_seconds']-st['source_time_seconds'],
                    health_at_state_time=state['health'],positions={k:v['position'] for k,v in state['joints'].items() if k.startswith(('right_','head_'))})))
        if i==21:continue
        end=idx[i+1]['source_time_seconds'];a=[a for a in actions if o['source_time_seconds']<a['source_time_seconds']<=end]
        before,purpose,after,progress,limitation=ANNOTATIONS[i]
        ledger.append(dict(segment=f'{i:04d}->{i+1:04d}',before_available=before,candidate_purpose_not_private_reasoning=purpose,
             after_observed=after,progress=progress,information_or_attribution_limit=limitation,
             observed_interval_seconds=end-o['source_time_seconds'],motion_count=len(a),
             nominal_duration_sum_seconds=sum(x['request'].get('duration',0) for x in a),
             duration_warning='May overlap; not execution wall time or measured displacement',action_source_lines=[x['source_line'] for x in a],
             images=[f'observations/{j:04d}/{cam}.jpg' for j in [i,i+1] for cam in ['head','right_wrist']]))
    write(OUT/'SOURCE_LEDGER.json',ledger)
    write(OUT/'SELECTION.json',dict(source='be001-source-3',selected=SELECTED,cameras=['head','right_wrist'],
        reasons={str(i):('retain identity / visibility / pose / base effect / low progress / activation evidence' if i in SELECTED else
                        'omit image only: intermediate detail; preserve all motion requests in actions.json') for i in range(22)},
        operator_contact_sheets='development/source-review-*.jpg; not subject input',image_transform='none; original JPEG bytes'))
    prior='''# Authorized information

Body information: no additional body description.

Historical task experience: prior/experience/guide.md, FACTS.md, actions.json,
snapshots.json and observations/index.json with its listed original JPEGs.
Start with guide.md; it links the stage facts and selected image references.
Only one source attempt is represented. No executable skill, movie, raw full
state stream, external target location or normal measurement is supplied.
Recorded numeric actions are historical examples, not a current motion plan.
You may use the low-level API and your own code. Choose and verify from current
feedback; do not modify supplied inputs or transfer experience to another run.
'''
    newidx=[dict(index=i,source_time_seconds=o['source_time_seconds'],files={cam:f'prior/experience/observations/{i:04d}/{cam}.jpg' for cam in ['head','right_wrist']} if i in SELECTED else {},
                 images_retained=i in SELECTED) for i,o in enumerate(idx)]
    for c in ['C','R']:
        dest=OUT/'inputs'/c;dest.mkdir(parents=True)
        for name in COMMON:shutil.copyfile(OLD/'inputs/E3'/name,dest/name)
        (dest/'PRIOR.md').write_text(prior)
        e=dest/'prior/experience';e.mkdir(parents=True)
        shutil.copyfile(OUT/f'guide-{c}.md',e/'guide.md');(e/'FACTS.md').write_text(FACTS)
        write(e/'actions.json',actions);write(e/'snapshots.json',snapshots);write(e/'observations/index.json',newidx)
        for i in SELECTED:
            for cam in ['head','right_wrist']:
                target=e/f'observations/{i:04d}/{cam}.jpg';target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(SOURCE/f'observations/{i:04d}/{cam}.jpg',target)
    for k in ['setups','references']:shutil.copytree(OLD/k,OUT/k)
    source_metrics=read(ROOT/'reports/batches/skill-evaluation-001/summary.json')['trials']
    baselines=[];baseline_hash={}
    import run_prior_comparison as legacy
    for point,name in BASELINES.items():
        trial=next(t for t in source_metrics if t['run']==name)
        assert trial['point']==point and trial['condition']=='E3' and trial['repeat']==1
        legacy.STUDY=OUT/'references'/point
        result=legacy.summarize(ROOT/'experiments'/name,{'sha256':hashes(OLD/'inputs/E3')})
        assert abs(result['native_execution_wall_seconds']-trial['result']['native_execution_wall_seconds'])<1e-6
        baselines.append({**{k:trial[k] for k in ['run','point','condition','repeat']},'historical':True,'result':trial['result']})
        for path in ['private/agent-result.json','private/simulation/result.json','private/prior-input-audit.json','private/simulation/initial-prior-audit.json','private/agent-workflow.jsonl','private/simulation/events.jsonl']:
            f=ROOT/'experiments'/name/path;baseline_hash[str(f.relative_to(ROOT))]=digest(f)
    write(OUT/'baselines.json',baselines)
    sizes={}
    for c,path in [('E3',OLD/'inputs/E3/prior/experience'),('C',OUT/'inputs/C/prior/experience'),('R',OUT/'inputs/R/prior/experience')]:
        fs=[f for f in path.rglob('*') if f.is_file()];textfiles=[f for f in fs if f.suffix in ['.md','.json','.jsonl']]
        sizes[c]=dict(files=len(fs),jpeg_count=sum(f.suffix=='.jpg' for f in fs),
                      text_utf8_bytes=sum(f.stat().st_size for f in textfiles),total_bytes=sum(f.stat().st_size for f in fs),
                      narrative_words=words((path/('summary.md' if c=='E3' else 'guide.md')).read_text()))
    write(OUT/'PACKAGE_COMPARISON.json',sizes)
    files={**old_m['frozen_files']}
    for p in [Path(__file__),ROOT/'scripts/start_reflection_trial.py',ROOT/'scripts/reflection_batch.py',
              OUT/'PROTOCOL.zh-CN.md',OUT/'SOURCE_LEDGER.json',OUT/'SELECTION.json',OUT/'baselines.json',OUT/'guide-C.md',OUT/'guide-R.md']:
        files[str(p.relative_to(ROOT))]=digest(p)
    from sim_env.agent import DEFAULT_CODEX
    binary=Path(DEFAULT_CODEX).resolve()
    m=dict(study='experience-reflection-001',model='gpt-6-astra',effort='xhigh',task_seconds=1800,session_seconds=1980,
           created_at_utc=datetime.now(timezone.utc).isoformat(),trials=build_trials(),second_measurement_enabled=False,
           source='be001-source-3',source_sha256=hashes(SOURCE),baseline_sha256=baseline_hash,
           historical_baseline=True,known_test_points=True,frozen_files=files,
           codex_binary=str(binary),codex_binary_sha256=digest(binary),
           **{k+'_sha256':hashes(OUT/k) for k in ['inputs','setups','references']})
    write(OUT/'manifest.json',m);write(OUT/'SEAL.json',{'manifest_sha256':digest(OUT/'manifest.json')})
    validate()

def validate():
    m=read(OUT/'manifest.json');assert digest(OUT/'manifest.json')==read(OUT/'SEAL.json')['manifest_sha256']
    assert m['trials']==build_trials() and len(m['trials'])==12 and not m['second_measurement_enabled']
    for k in ['inputs','setups','references']:assert hashes(OUT/k)==m[k+'_sha256'],k
    for k in ['frozen_files','baseline_sha256']:
        for p,h in m[k].items():assert digest(ROOT/p)==h,p
    assert hashes(SOURCE)==m['source_sha256']
    assert digest(m['codex_binary'])==m['codex_binary_sha256']
    for name in COMMON:
        assert (OUT/'inputs/C'/name).read_bytes()==(OUT/'inputs/R'/name).read_bytes()==(OLD/'inputs/E3'/name).read_bytes()
    c=hashes(OUT/'inputs/C');r=hashes(OUT/'inputs/R')
    assert c.keys()==r.keys();assert [f for f in c if c[f]!=r[f]]==['prior/experience/guide.md']
    wc=[words((OUT/f'inputs/{x}/prior/experience/guide.md').read_text()) for x in ['C','R']]
    assert max(wc)/min(wc)<=1.10,wc
    ds=(SOURCE/'synchronized.jsonl').read_text().splitlines()
    for a in read(OUT/'inputs/C/prior/experience/actions.json'):
        d=json.loads(ds[a['source_line']-1]);assert a['request']==d['request'] and a['source_time_seconds']==d['source_time_seconds']
    for i in SELECTED:
        for cam in ['head','right_wrist']:
            p=f'observations/{i:04d}/{cam}.jpg';assert digest(OUT/'inputs/C/prior/experience'/p)==digest(SOURCE/p)
    from sim_env.setup import load_setup
    for point in BASELINES:
        load_setup(OUT/'setups'/f'{point}.json')
        assert digest(OUT/'setups'/f'{point}.json')==digest(OLD/'setups'/f'{point}.json')
        assert digest(OUT/'references'/point/'private-initial-reference.json')==digest(OLD/'references'/point/'private-initial-reference.json')
    print('PASS: 12 first-measurement trials, source provenance, paired inputs, historical baselines and runtime frozen',flush=True)
    return m

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--validate',action='store_true');a=p.parse_args()
    validate() if a.validate else prepare()
