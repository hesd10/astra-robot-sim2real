"""Compact numeric summary; no full report or private model reasoning."""
import concurrent.futures,json,re,statistics,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];STUDY=ROOT/'studies/position-perturbation-001';BATCH=ROOT/'reports/batches/position-perturbation-001'
def read(p):return json.loads(Path(p).read_text())
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def fmt(x):
 if x is None:return '—'
 v=round(x);return f'{v//60}:{v%60:02d}'
def summarize(final=False):
 s=read(BATCH/'status.json');m=read(STUDY/'manifest.json');ts=s['completed'];pairs=[];groups={}
 for pair in m['pairs']:
  z={t['condition']:t['result'] for t in ts if t['point']==pair['point']}
  delta=z['I0E0']['sim_seconds']-z['I0E3']['sim_seconds'] if len(z)==2 and all(v['success_and_correct_declaration'] for v in z.values()) else None
  pairs.append({'point':pair['point'],'radius_m':pair['radius_m'],'results':z,'paired_success_time_saving_seconds':delta,'paired_capped_score_saving_seconds':z['I0E0']['failure_capped_score_seconds']-z['I0E3']['failure_capped_score_seconds'] if len(z)==2 else None})
 for radius in [.1,.5,1.]:
  for c in ['I0E0','I0E3']:
   z=[t['result'] for t in ts if t['radius_m']==radius and t['condition']==c]
   if not z:continue
   good=[x for x in z if x['success_and_correct_declaration']];seconds=[x['sim_seconds'] for x in good]
   groups[f'{radius}:{c}']={'n':len(z),'successes':len(good),'wrong_button_count':sum(x['wrong_button'] for x in z),'success_seconds_mean':statistics.mean(seconds) if seconds else None,'success_seconds_sample_sd':statistics.stdev(seconds) if len(seconds)>1 else None,'failure_capped_seconds_mean':statistics.mean(x['failure_capped_score_seconds'] for x in z),'mean_motion_commands':statistics.mean(x['motion_commands'] for x in z),'mean_observation_groups':statistics.mean(x['observation_groups'] for x in z)}
 write(BATCH/'summary.json',{'completed':len(ts),'pairs':pairs,'groups':groups,'updated_unix':time.time(),'baseline_reference':'body-experience-001/final-analysis/statistics.json','notes':['Each radius has three DIFFERENT positions, one E0/E3 run each; not three repeats per position.','Different radii independently sampled angles; difficulty and direction can confound radius comparison.','E3 source fixed at original station; no history update.','No success-rate or generalization significance claim from n=3.']})
 lines=['# 扰动实验简表','',f'已归档 {len(ts)}/18。每档三个不同站位，E0/E3同点配对；不是同站位重复三次。E3资料保持原站位单一源案例。时间不含录像导出。','', '|距离|E0成功/已完成|E0成功平均|E3成功/已完成|E3成功平均|','|---|---:|---:|---:|---:|']
 for r in [.1,.5,1.]:
  row=[f'{r*100:.0f} cm']
  for c in ['I0E0','I0E3']:
   z=groups.get(f'{r}:{c}');row+= [f"{z['successes']}/{z['n']}" if z else '0/0',fmt(z['success_seconds_mean']) if z else '—']
  lines.append('|'+ '|'.join(row)+'|')
 lines+=['','|点位|E0结果/用时|E3结果/用时|E3节省秒数（双方成功时）|','|---|---|---|---:|']
 for p in pairs:
  row=[p['point']]
  for c in ['I0E0','I0E3']:
   z=p['results'].get(c);row.append(('成功' if z['success_and_correct_declaration'] else '失败')+' / '+fmt(z['sim_seconds']) if z else '待完成')
  row.append(f"{p['paired_success_time_saving_seconds']:+.1f}" if p['paired_success_time_saving_seconds'] is not None else '—');lines.append('|'+ '|'.join(row)+'|')
 lines+=['','失败保留、失败封顶1800秒；封顶均值/动作数/观测数/误按次数见summary.json。不同半径的方向不配对，不将均值变化单独解释为半径因果效应。暂不写完整分析报告；全部结束后由研究者侧代理补充简短观察并检查成功图像。']
 (BATCH/'SUMMARY.zh-CN.md').write_text('\n'.join(lines)+'\n')
 if final:media_audit(ts)
def media_audit(ts):
 from PIL import Image,ImageDraw,ImageFont
 import imageio_ffmpeg
 out=BATCH/'review';out.mkdir(exist_ok=True);items=[];image_index=[]
 for t in ts:
  p=ROOT/'experiments'/t['run'];report=p/'subject/evidence/report.md';links=re.findall(r'\]\(([^)]+\.(?:jpg|png))\)',report.read_text()) if report.exists() else []
  images=[]
  for suffix in ['head.jpg','wrist.jpg']:
   v=next((x for x in links if x.endswith(suffix)),None)
   if v and (report.parent/v).exists():images.append(str(report.parent/v))
  image_index.append({'run':t['run'],'success':t['result']['success_and_correct_declaration'],'images':images})
  items.extend((t['run'],p/'private'/f) for f in ['dashboard.mp4','follow.mp4','follow-compact.mp4'])
 write(out/'image-index.json',image_index)
 font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',15)
 for page in range((len(ts)+5)//6):
  board=Image.new('RGB',(1280,810),'#f5f6f8');draw=ImageDraw.Draw(board)
  for j,row in enumerate(image_index[page*6:page*6+6]):
   x=(j%2)*640;y=(j//2)*270;draw.text((x+5,y+4),row['run']+(' SUCCESS' if row['success'] else ' FAILURE'),font=font,fill='black')
   for k,path in enumerate(row['images']):board.paste(Image.open(path).convert('RGB').resize((320,240)),(x+k*320,y+28))
  board.save(out/f'outcomes-{page+1}.jpg',quality=94)
 def decode(item):
  name,path=item;r=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-threads','1','-i',str(path),'-map','0:v:0','-progress','pipe:1','-f','null','-'],capture_output=True,text=True,timeout=1200)
  progress=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
  return {'run':name,'path':str(path),'bytes':path.stat().st_size,'exit_code':r.returncode,'errors':r.stderr[-3000:],'progress':progress}
 results=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  for row in pool.map(decode,items):results.append(row);write(out/'video-audit.json',results);print('video audit',len(results),'/',len(items),flush=True)
 assert all(x['exit_code']==0 and not x['errors'] and x['progress'].get('progress')=='end' and int(x['progress'].get('frame',0))>0 for x in results)
 write(out/'automated-checks.json',{'completed_unix':time.time(),'videos_decoded':len(results),'video_errors':0,'visual_review_pending':True})
if __name__=='__main__':summarize()
