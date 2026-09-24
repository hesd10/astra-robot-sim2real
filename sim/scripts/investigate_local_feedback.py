import json
from pathlib import Path
from PIL import Image,ImageDraw
root=Path(__file__).resolve().parents[1];out=root/'studies/local-feedback-001/final-review';rows=json.loads((out/'RESULTS.json').read_text())['trials'];details=[]
for t in rows:
 if t['condition']!='LOOP':continue
 run=root/'experiments'/t['run'];es=[json.loads(x) for x in (run/'private/simulation/events.jsonl').read_text().splitlines()];bs=[e for e in es if e['event']=='request' and e.get('accepted') and e['request']['op']=='base'];prev=-1;calls=[]
 for idx,c in enumerate(t['result']['skill_calls']):
  end=c['result']['observation']['sim_time'];cmds=[b for b in bs if prev<b['sim_time']<=end];start=cmds[0]['sim_time'];calls.append(dict(index=idx+1,start=start,end=end,execution_span=end-start,steps=len(cmds),parameters=c['parameters'],reason=c['result']['reason']));prev=end
 press=t['result']['metrics']['first_target_press_seconds'];det=[c for c in calls if c['reason']=='red_detected_verify'];lag=det[-1]['end']-press
 details.append(dict(run=t['run'],state=t['state'],repeat=t['repeat'],calls=calls,base_to_observation_seconds=sum(c['execution_span'] for c in calls),press_to_red_return_seconds=lag,post_press_steps=sum(b['sim_time']>press for b in bs)))
 print(t['run'],'calls',len(calls),'span',round(details[-1]['base_to_observation_seconds'],2),'detectlag',round(lag,3),'postpresssteps',details[-1]['post_press_steps'])
 if t['run']=='lf001-t018':
  sheet=Image.new('RGB',(1440,1152),'white');d=ImageDraw.Draw(sheet)
  for i,c in enumerate(t['result']['skill_calls']):
   im=Image.open(run/'subject'/c['result']['observation']['files']['head']).convert('RGB');di=ImageDraw.Draw(im);di.rectangle(c['parameters']['regions']['head'],outline='cyan',width=2);im=im.resize((480,360));x=i%3*480;y=i//3*384;sheet.paste(im,(x,y+24));d.text((x+5,y+5),f"Call {i+1} vx={c['parameters']['vx']} vy={c['parameters']['vy']} end={c['result']['observation']['sim_time']:.1f}s",fill='black')
  sheet.save(out/'S3-C-round2-sequence.jpg')
(out/'MECHANISM_AUDIT.json').write_text(json.dumps(details,indent=2)+'\n')
