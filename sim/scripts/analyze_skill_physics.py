"""Post-run developer measurements, never an input to the action skills."""
import argparse
import gzip
import json
from pathlib import Path
import sys
import numpy as np
import mujoco
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sim_env.model import OUTPUT, CHANNELS, restore
from sim_env.rendering import follow_camera


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('case')
    args=parser.parse_args()
    run=ROOT/'studies/skill-induction-001/development'/args.case
    calls=json.loads((run/'calls.json').read_text())
    logs=[json.loads(l) for l in (run/'evidence/calls.jsonl').read_text().splitlines()]
    m=mujoco.MjModel.from_xml_path(str(OUTPUT)); d=mujoco.MjData(m)
    rows=[]
    with gzip.open(run/'simulation/states.jsonl.gz','rt') as f:
        for l in f:
            r=json.loads(l); restore(m,d,r)
            rows.append({'t':r['sim_time'],'p':d.body('chassis').xpos[:2].copy(),
                         'R':d.body('chassis').xmat.reshape(3,3)[:2,:2].copy(),
                         'speed':float(np.linalg.norm(d.qvel[m.joint('base_free').dofadr[0]:m.joint('base_free').dofadr[0]+2])),
                         'raw':r})
    times=np.array([r['t'] for r in rows])
    metrics=[]; panels=[]
    with mujoco.Renderer(m,height=480,width=640) as renderer:
        for c in calls:
            inv=c['result']['invocation']
            states=[r['result'] for r in logs if r.get('invocation')==inv and r['event']=='response' and r.get('op')=='state']
            if not states: continue
            a,b=states[0],states[-1]
            ia=int(np.argmin(abs(times-a['sim_time']))); ib=int(np.argmin(abs(times-b['sim_time'])))
            delta=rows[ia]['R'].T@(rows[ib]['p']-rows[ia]['p'])
            hold_error=max(abs(s['joints'][j]['position']-s['joints'][j]['target']) for s in states for j in CHANNELS if not j.startswith('head'))
            out={'skill':c['skill'],'parameters':c['parameters'],'ok':c['result']['ok'],
                 'start_s':a['sim_time'],'end_s':b['sim_time'],
                 'body_displacement_m':delta.tolist(),'physical_base_speed_at_return_m_s':rows[ib]['speed'],
                 'max_sampled_arm_tracking_error_rad':hold_error,
                 'fresh_image_delay_after_state_s':c['result'].get('observation',{}).get('sim_time',b['sim_time'])-b['sim_time']}
            metrics.append(out)
            restore(m,d,rows[ib]['raw'])
            renderer.update_scene(d,camera=follow_camera(m,d))
            im=Image.fromarray(renderer.render()).resize((480,360))
            canvas=Image.new('RGB',(960,390),'white');canvas.paste(im,(0,30))
            obs=c['result'].get('observation',{}).get('files',{})
            if 'right_wrist' in obs:
                with Image.open(obs['right_wrist']) as wrist: canvas.paste(wrist.resize((480,360)),(480,30))
            ImageDraw.Draw(canvas).text((5,5),f"{len(metrics)} {c['skill']} {c['parameters']}",fill='black')
            panels.append(canvas)
    (run/'measurements.json').write_text(json.dumps(metrics,indent=2))
    for start in range(0,len(panels),4):
        page=Image.new('RGB',(960,390*len(panels[start:start+4])),'white')
        for n,p in enumerate(panels[start:start+4]):page.paste(p,(0,n*390))
        page.save(run/f'review-{start//4+1}.jpg')
    print(json.dumps(metrics,indent=2))


if __name__=='__main__':main()
