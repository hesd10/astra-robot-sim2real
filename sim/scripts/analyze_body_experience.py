"""Read-only final statistics and media audit of frozen formal trials."""
import concurrent.futures,json,re,statistics,subprocess,time
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from body_experience_study import ROOT,STUDY,BATCH,read,validate
from prior_materials import write_json
validate();s=read(BATCH/'status.json');trials=[t for t in s['completed'] if t['phase']=='evaluation'];assert len(trials)==30
out=STUDY/'final-analysis';out.mkdir(exist_ok=True)
keys=['sim_seconds','native_execution_wall_seconds','failure_capped_score_seconds','motion_commands','observation_groups','tool_seconds','outside_tool_seconds','first_target_press_seconds','peak_non_support_contact_N']
groups={}
for c in ['I0E0','I1E0','I2E0','I3E0','I0E1','I0E2','I0E3','I3E1','I3E2','I3E3']:
 ts=sorted([t for t in trials if t['condition']==c],key=lambda t:t['replicate']);assert len(ts)==3
 groups[c]={'n':3,'successes':sum(t['result']['success_and_correct_declaration'] for t in ts),'runs':[t['run'] for t in ts]}
 for k in keys:
  v=[t['result'][k] for t in ts];groups[c][k]={'values':v,'mean':statistics.mean(v),'sample_sd':statistics.stdev(v),'min':min(v),'max':max(v)}
write_json(out/'statistics.json',{'created_unix':time.time(),'groups':groups,'source_trials':[t for t in s['completed'] if t['phase']=='source'],'excluded_operator_interruptions':s.get('excluded_operator_interruptions',[]),'clock_note':'sim_seconds is service origin to finish; failure_capped_score_seconds is existing native execution endpoint metric capped at1800 on failure; all success, clocks differ ~1sec'})
font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',17);evidence=[]
for page in range(5):
 board=Image.new('RGB',(1280,810),'#f4f6f8');draw=ImageDraw.Draw(board)
 for j,t in enumerate(trials[page*6:page*6+6]):
  p=ROOT/'experiments'/t['run']/'subject/evidence';report=(p/'report.md').read_text();links=re.findall(r'\]\(([^)]+\.(?:jpg|png))\)',report)
  selected=[]
  for role in ['head.jpg','wrist.jpg']:
   selected.append(next(x for x in links if x.endswith(role)))
  evidence.append({'run':t['run'],'report':str(p/'report.md'),'images':[str(p/x) for x in selected]})
  x=(j%2)*640;y=(j//2)*270;draw.text((x+6,y+4),t['run'],font=font,fill='black')
  for k,path in enumerate(selected):board.paste(Image.open(p/path).convert('RGB').resize((320,240)),(x+k*320,y+28))
 board.save(out/f'success-sheet-{page+1}.jpg',quality=94)
write_json(out/'success-image-index.json',evidence)
def check(item):
 import imageio_ffmpeg
 name,path=item
 decode=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-threads','1','-i',str(path),'-map','0:v:0','-progress','pipe:1','-f','null','-'],capture_output=True,text=True,timeout=1200)
 progress={}
 for line in decode.stdout.splitlines():
  if '=' in line:
   k,v=line.split('=',1);progress[k]=v
 return {'run':name,'path':str(path),'bytes':path.stat().st_size,'decoded_progress':progress,'full_decode_exit':decode.returncode,'errors':decode.stderr[-3000:]}

items=[(t['run'],ROOT/'experiments'/t['run']/'private'/file) for t in trials for file in ['dashboard.mp4','follow.mp4','follow-compact.mp4']]
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
 for r in pool.map(check,items):
  results.append(r)
  if len(results)%10==0:print('media checked',len(results),'/90',flush=True)
write_json(out/'video-integrity.json',results)
assert all(x['full_decode_exit']==0 and x['decoded_progress'].get('progress')=='end' and not x['errors'] and x['bytes']>0 for x in results),'Media audit issue'
print('all90 videos fully decoded; frozen inputs verified',flush=True)
