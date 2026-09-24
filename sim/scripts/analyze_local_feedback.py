import json,statistics
from pathlib import Path
from PIL import Image,ImageDraw
root=Path(__file__).resolve().parents[1];out=root/'studies/local-feedback-001/final-review';out.mkdir(exist_ok=True);rows=[];batches=[]
for name in ['local-feedback-001','local-feedback-001-repeats']:
 s=json.loads((root/'reports/batches'/name/'status.json').read_text());rows+=s['completed'];batches.append(s)
audit=[]
for t in rows:
 run=root/'experiments'/t['run'];r=t['result'];m=r['metrics'];v=r['simulation_result'];events=[json.loads(x) for x in (run/'private/simulation/events.jsonl').read_text().splitlines()]
 fresh=any(e['event']=='observation_delivered' and e.get('snapshot_after_request') and e['sim_time']>=m['first_target_press_seconds'] for e in events)
 assert v['physical_success'] and v['subject_outcome']=='success' and not v['wrong_button'] and not v['fault'] and fresh
 f=max((run/'subject/evidence').rglob('head.jpg'),key=lambda p:p.stat().st_mtime)
 audit.append(dict(run=t['run'],final_head=str(f),fresh_after_press=fresh))
for repeat in [1,2,3]:
 sheet=Image.new('RGB',(1440,1152),'white');d=ImageDraw.Draw(sheet)
 for t in [t for t in rows if t['repeat']==repeat]:
  col=['FREE','STEP','LOOP'].index(t['condition']);row=['S1','S2','S3'].index(t['state']);x=col*480;y=row*384
  a=next(a for a in audit if a['run']==t['run']);sheet.paste(Image.open(a['final_head']).resize((480,360)),(x,y+24));d.text((x+8,y+5),f"{t['run']} {t['state']} {t['condition']}",fill='black')
 sheet.save(out/f'round-{repeat}.jpg')
summary={}
for c in ['FREE','STEP','LOOP']:
 ts=[t for t in rows if t['condition']==c];summary[c]={}
 for st in ['S1','S2','S3','ALL']:
  ss=[t for t in ts if st=='ALL' or t['state']==st];vals=[t['result']['metrics']['native_execution_wall_seconds'] for t in ss]
  summary[c][st]={'mean_seconds':statistics.mean(vals),'sd_seconds':statistics.stdev(vals),'n':len(vals),'mean_total_tokens':statistics.mean(t['result']['tokens_whole_session']['totalTokens'] for t in ss),'mean_noncached_input_tokens':statistics.mean(t['result']['tokens_whole_session']['inputTokens']-t['result']['tokens_whole_session']['cachedInputTokens'] for t in ss),'mean_output_tokens':statistics.mean(t['result']['tokens_whole_session']['outputTokens'] for t in ss)}
pairs=[]
for repeat in [1,2,3]:
 for st in ['S1','S2','S3']:
  ts={t['condition']:t['result']['metrics']['native_execution_wall_seconds'] for t in rows if t['repeat']==repeat and t['state']==st};pairs.append(ts)
print(json.dumps(summary,indent=2));print('wins B<A',sum(p['STEP']<p['FREE'] for p in pairs),'C<A',sum(p['LOOP']<p['FREE'] for p in pairs),'C<B',sum(p['LOOP']<p['STEP'] for p in pairs))
(out/'RESULTS.json').write_text(json.dumps(dict(summary=summary,audit=audit,trials=rows,execution_minutes=sum((s['ended_unix']-s['created_unix'])/60 for s in batches)),indent=2)+'\n')
