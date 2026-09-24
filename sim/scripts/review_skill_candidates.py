"""Reproduce candidate evidence and representative observed-image sheets."""
import collections
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'studies/skill-induction-001'
def read(p): return json.loads(p.read_text())
def save(name,value): (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def main():
    corpus=read(OUT/'CORPUS.json');deploy=[];families=collections.defaultdict(list);press_context=[]
    for row in corpus:
        d=read(OUT/'extracted'/f"{row['run']}.json")
        press=next((x for x in d['signals'] if x['event']=='target_pressed'),None)
        if press:
            q=[q for q in d['requests'] if q['accepted'] and q['request']['op'] in ['base','move'] and q['time']<=press['sim_time']][-1]
            press_context.append({'run':row['run'],'press_line':press['line'],
                'press_time':press['sim_time'],'preceding_motion':q,
                'seconds_since_request':press['sim_time']-q['time'],
                'note':'Temporal association only; overlapping or settling motions may contribute.'})
        t=row['press_command_targets']
        if t:
            arm='left' if row['counts']['left_arm_move'] and not row['counts']['right_arm_move'] else 'right'
            key=arm+':'+','.join(str(round(t.get(f'{arm}_{i}',999),3)) for i in [2,3,4])
            families[key].append(row['run'])
        if not str(row.get('condition')).endswith('E3'):continue
        a,b=d['arm_moves']['right'];assert len(d['arm_moves']['right'])==2
        between=[q for q in d['requests'] if a['line']<q['line']<b['line'] and q['accepted'] and q['request']['op']=='base']
        obs=[q for q in d['observations'] if a['line']<q['line']<b['line']]
        post=[q for q in d['public_states'] if q['time']>=b['time']+b['request']['duration']]
        deploy.append({'run':row['run'],'stage_lines':[a['line'],b['line']],
            'stage_targets':[a['request']['targets'],b['request']['targets']],
            'durations':[a['request']['duration'],b['request']['duration']],
            'stage_times':[a['time'],b['time']],
            'base_commands_between':len(between),'observations_between':len(obs),
            'stage_start_gap_s':b['time']-a['time'],'feedback':post[0] if post else None})
    save('DEPLOYMENT_EVIDENCE.json',deploy)
    save('PRESS_CONTEXT.json',press_context)
    summary={'command_posture_groups_rounded_3dp':dict(families),
             'e3_deployments':len(deploy),
             'deployments_with_intermediate_base':sum(x['base_commands_between']>0 for x in deploy),
             'deployments_with_intermediate_observation':sum(x['observations_between']>0 for x in deploy),
             'interpretation':'Command triples, not physical end-effector poses; correlated shared-source E3 runs.'}
    summary['tracking_error_after_stage2']={}
    for j in ['right_2','right_3','right_4']:
        v=[abs(x['feedback']['state']['joints'][j]['position']-x['feedback']['state']['joints'][j]['target']) for x in deploy if x['feedback']]
        summary['tracking_error_after_stage2'][j]={'min_rad':min(v),'max_rad':max(v),'note':'First returned state after nominal duration, not continuous settling proof or a validated tolerance.'}
    save('CANDIDATE_STATISTICS.json',summary)
    selected=['be001-r1-i0e3','be001-r1-i3e3','pp001-r010-p2-i0e3',
              'pp001-r100-p1-i0e3','pp001-r100-p2-i0e3','pp001-r100-p3-i0e3']
    index=[]
    for page in range(2):
        canvas=Image.new('RGB',(1280,3*270),'white');draw=ImageDraw.Draw(canvas)
        for ri,name in enumerate(selected[page*3:page*3+3]):
            row=next(x for x in deploy if x['run']==name)
            frames=[]
            for p in (ROOT/'experiments'/name/'subject/evidence').rglob('observation.json'):
                o=read(p)
                if 'sim_time' in o:frames.append((o['sim_time'],p))
            frames.sort()
            for stage in range(2):
                eligible=[v for v in frames if v[0]>=row['stage_times'][stage]+row['durations'][stage]]
                assert eligible,(name,stage)
                t,p=eligible[0]
                draw.text((stage*640+4,ri*270+3),f'{name} stage {stage+1} t={t:.2f}s',fill='black')
                for cam,ci in [('head',0),('right_wrist',1)]:
                    image=p.parent/f'{cam}.jpg'
                    with Image.open(image) as im:canvas.paste(im.resize((320,240)),(stage*640+ci*320,ri*270+26))
                    index.append({'run':name,'stage':stage+1,'camera':cam,'capture_time':t,
                        'after_nominal_end_s':t-row['stage_times'][stage]-row['durations'][stage],
                        'path':str(image.relative_to(ROOT)),
                        'sha256':hashlib.sha256(image.read_bytes()).hexdigest(),
                        'sheet':f'deployment-review-{page+1}.jpg'})
        canvas.save(OUT/f'deployment-review-{page+1}.jpg',quality=88)
    save('IMAGE_REVIEW_INDEX.json',index)
    print(json.dumps({k:v for k,v in summary.items() if k!='command_posture_groups_rounded_3dp'},indent=2))

if __name__=='__main__':main()
