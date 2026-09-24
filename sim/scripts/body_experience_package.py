"""Build source-only media/telemetry, then freeze reviewed same-source experience."""
import argparse,json,shutil,subprocess
from pathlib import Path
from PIL import Image,ImageDraw
from body_experience_study import ROOT,STUDY,BATCH,read,save,validate,make_input
from prior_materials import hashes,write_json,digest

def build():
    s=read(BATCH/'status.json');assert s['status']=='awaiting_experience'
    source=s['selected_source'];run=ROOT/'experiments'/source;dest=STUDY/'experience'
    if dest.exists():raise RuntimeError('Package exists; review existing build instead of overwrite')
    dest.mkdir();(dest/'observations').mkdir();work=BATCH/'experience-media-work';work.mkdir()
    observations=[]
    for path in (run/'subject/evidence').glob('*/observation.json'):
        data=read(path)
        if all((path.parent/(role+'.jpg')).is_file() for role in ['head','left_wrist','right_wrist']):
            observations.append((float(data['sim_time']),path))
    observations.sort()
    assert observations,'No source camera observations'
    index=[];frames=[]
    for i,(stamp,path) in enumerate(observations):
        folder=dest/'observations'/f'{i:04d}';folder.mkdir()
        panel=Image.new('RGB',(1920,510),'black');draw=ImageDraw.Draw(panel);files={}
        for col,role in enumerate(['head','left_wrist','right_wrist']):
            source_image=path.parent/(role+'.jpg');shutil.copyfile(source_image,folder/(role+'.jpg'))
            with Image.open(source_image) as im:panel.paste(im.convert('RGB').resize((640,480)),(640*col,30))
            draw.text((640*col+10,8),f'{role} | source capture {stamp:.3f} s',fill='white')
            files[role]=str((folder/(role+'.jpg')).relative_to(STUDY))
        frame=work/f'{i:04d}.png';panel.save(frame);frames.append(frame)
        index.append({'index':i,'source_time_seconds':stamp,'files':{k:'prior/'+v for k,v in files.items()}})
    write_json(dest/'observations/index.json',index)
    finish=read(run/'private/simulation/result.json')['sim_seconds']
    lines=[]
    for i,frame in enumerate(frames):
        duration=max(.5,(observations[i+1][0] if i+1<len(frames) else finish)-observations[i][0])
        lines.extend(["file '"+str(frame)+"'",f'duration {duration:.6f}'])
    lines.append("file '"+str(frames[-1])+"'")
    playlist=work/'frames.txt';playlist.write_text('\n'.join(lines)+'\n')
    subprocess.run(['ffmpeg','-v','error','-f','concat','-safe','0','-i',str(playlist),'-vf','fps=2','-c:v','libx264','-crf','24','-pix_fmt','yuv420p','-movflags','+faststart',str(dest/'demonstration.mp4')],check=True)
    write_json(dest/'timeline.json',{'kind':'sample_and_hold_of_actual_source_observations','columns':['head','left_wrist','right_wrist'],'source_start_seconds':observations[0][0],'source_finish_seconds':finish,'observations':[{'index':i,'source_time_seconds':t,'video_time_seconds':t-observations[0][0]} for i,(t,_) in enumerate(observations)]})
    records=[]
    for line in (run/'private/simulation/events.jsonl').open():
        e=json.loads(line)
        if e.get('event')=='request' and e.get('request',{}).get('op') in ['schema','state','move','base','stop','finish']:
            # Only exact responses available through the public API. No private events/GT.
            records.append({'source_time_seconds':e['sim_time'],'request':{k:v for k,v in e['request'].items() if k!='id'},'reply':e.get('reply')})
        elif e.get('event')=='observation_delivered':
            records.append({'source_time_seconds':e['sim_time'],'op':'observe','observation_index':next((i for i,(t,_) in enumerate(observations) if abs(t-e['sim_time'])<.02),None)})
    (dest/'synchronized.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in records))
    write_json(BATCH/'experience-build.json',{'source':source,'source_input_sha256':read(run/'private/prior-input-audit.json')['sha256'],'source_events_sha256':digest(run/'private/simulation/events.jsonl'),'observations':len(observations),'public_records':len(records),'media_sha256':hashes(dest),'summary_pending':True})
    print('Media ready. Write source-grounded summary.md and private summary-review.json, inspect media, then freeze.')

def freeze():
    s=read(BATCH/'status.json');assert s['status']=='awaiting_experience';validate()
    dest=STUDY/'experience';summary=dest/'summary.md';text=summary.read_text();assert 30<len(text.split())<=800
    audit=read(BATCH/'summary-review.json');assert audit['source']==s['selected_source'] and audit['reviewed'] is True
    assert audit['summary_sha256']==digest(summary)
    build=read(BATCH/'experience-build.json');assert build['source']==s['selected_source']
    for f,h in build['media_sha256'].items():assert digest(dest/f)==h
    assert audit['media_visually_checked'] and audit['success_visually_checked']
    for level in [0,3]:
        for e in [1,2,3]:make_input(f'I{level}E{e}',dest)
    inputs={f'I{i}E{e}':hashes(STUDY/'inputs'/f'I{i}E{e}') for i in [0,3] for e in [1,2,3]}
    for e in [1,2,3]:
        assert digest(STUDY/'inputs'/f'I0E{e}'/'prior/experience/summary.md')==digest(summary)
    for i in [0,3]:
        assert hashes(STUDY/'inputs'/f'I{i}E2'/'prior/experience')=={k:v for k,v in hashes(STUDY/'inputs'/f'I{i}E3'/'prior/experience').items() if k!='synchronized.jsonl'}
    write_json(STUDY/'experience-manifest.json',{'source':s['selected_source'],'selection':'minimum valid successful sim_seconds','package_sha256':hashes(dest),'inputs':inputs,'builder_sha256':digest(__file__),'review_sha256':digest(BATCH/'summary-review.json')})
    s['status']='experience_frozen';save(s);validate();print('Experience and all ten conditions frozen; ready for evaluation.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['build','freeze']);a=p.parse_args();build() if a.mode=='build' else freeze()
