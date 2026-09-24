"""Synthetic end-to-end launch verification. Never calls a real model."""
import sys,json,threading,uuid,os,time,urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
root=Path(__file__).resolve().parents[1];sys.path[:0]=[str(root),str(root/'scripts')]
from start_experiment import start

def main():
 calls=[]
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def do_POST(self):
   data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(data);i=len(calls)
   if i==1:
    time.sleep(3)  # Synthetic stationary inference wait.
    command="python3 - <<'PY'\nfrom robot import call,observe\na=call('state')\ntry: call('base',vx=.2,duration=1.)\nexcept RuntimeError: print('REJECTED_FIXTURE')\nb=observe();call('base',vx=.01,duration=1.);print('LIVE_THREE_CAMERA_FIXTURE',len(b['files']))\nPY"
    item={'id':'tool_fixture','type':'custom_tool_call','call_id':'fixture_call','name':'exec','namespace':'functions','input':'text(await tools.exec_command('+json.dumps({'cmd':command,'yield_time_ms':10000,'max_output_tokens':1500})+'))'}
   elif i==2:
    time.sleep(3)  # The base keeps moving during part of this wait.
    command="python3 - <<'PY'\nfrom robot import call\ncall('stop',request_id='idempotency-check');call('stop',request_id='idempotency-check');call('finish',outcome='failure')\nPY"
    item={'id':'tool_finish','type':'custom_tool_call','call_id':'finish_call','name':'exec','namespace':'functions','input':'text(await tools.exec_command('+json.dumps({'cmd':command,'yield_time_ms':10000,'max_output_tokens':1500})+'))'}
   else:
    time.sleep(3) # Native closeout continues after physics and its camera server stop.
    item={'id':'msg_fixture','type':'message','role':'assistant','content':[{'type':'output_text','text':'Synthetic launch verification complete.'}]}
   rid='resp_'+str(i);ev=[{'type':'response.created','response':{'id':rid}},{'type':'response.output_item.done','output_index':0,'item':item},{'type':'response.completed','response':{'id':rid,'status':'completed','output':[item],'usage':{'input_tokens':10,'output_tokens':10,'total_tokens':20}}}]
   self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
   def emit(e):
    self.wfile.write(('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n').encode());self.wfile.flush()
   emit(ev[0])
   if i==1:
    message={'id':'fixture_progress','type':'message','role':'assistant','phase':'commentary','content':[]}
    emit({'type':'response.output_item.added','output_index':0,'item':message})
    content='验收演示：正在读取机器人状态。'
    for delta in ('验收演示：','正在读取机器人状态。'):
     emit({'type':'response.output_text.delta','item_id':message['id'],'output_index':0,'content_index':0,'delta':delta});time.sleep(.6)
    message['content']=[{'type':'output_text','text':content}]
    emit({'type':'response.output_item.done','output_index':0,'item':message})
    ev[1]['output_index']=1;ev[2]['response']['output'].insert(0,message)
   for e in ev[1:]:emit(e)
 s=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=s.serve_forever,daemon=True).start()
 os.environ.update(ASTRA_BASE_URL=f'http://127.0.0.1:{s.server_port}/v1',ASTRA_API_KEY='SYNTHETIC_ONLY',ASTRA_MODEL='gpt-6-astra')
 name='verification-native-'+uuid.uuid4().hex[:8]
 run=root/'experiments'/name
 samples=[];monitor_errors=[];stop=threading.Event()
 def inspect_live():
  client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
  while not stop.wait(.1):
   path=run/'private/dashboard.json'
   if not path.exists():continue
   try:
    url=json.loads(path.read_text())['url']
    with client.open(url+'workflow',timeout=2) as response: feed=json.load(response)
    with client.open(url+'status',timeout=2) as response: frame=json.load(response)
    samples.append({'workflow':feed,'frame':frame})
   except (OSError,ValueError) as exc:monitor_errors.append(type(exc).__name__)
 watcher=threading.Thread(target=inspect_live,daemon=True);watcher.start()
 try:
  out=start(name,max_seconds=30,setup=root/'setups/formal-001.json')
  stop.set();watcher.join(timeout=3)
  assert len(calls)==3
  items=[x for x in calls[1]['input'] if x.get('type')=='custom_tool_call_output']
  replies=[json.loads(x['text']) for item in items for x in item['output'] if x.get('type')=='input_text' and x['text'].startswith('{')]
  assert replies[-1]['exit_code']==0,replies
  assert 'LIVE_THREE_CAMERA_FIXTURE 3' in replies[-1]['output'],replies
  result=json.loads((out/'private/simulation/result.json').read_text());assert result['fault'] is None and result['subject_outcome']=='failure',result
  video=json.loads((out/'private/follow.json').read_text());assert video['frames']>1
  compact=json.loads((out/'private/follow-compact.json').read_text())
  dashboard=json.loads((out/'private/dashboard-recording.json').read_text())
  assert dashboard['status']=='saved' and dashboard['frames']>25,dashboard
  assert dashboard['width']==1920 and dashboard['height']==1080
  assert dashboard['final_page_state']['phase']=='会话完成'
  timing=[json.loads(line) for line in (out/'private/agent-timing.jsonl').read_text().splitlines()]
  ended=next(e['monotonic'] for e in timing if e['event']=='session/ended')
  assert dashboard['stopped_monotonic']>=ended,'capture stopped before Astra closeout'
  assert (out/'private/dashboard.mp4').stat().st_size>10000
  assert (out/'private/dashboard-last.png').is_file()
  assert any(s['frame'].get('lifecycle')=='closing' for s in samples),'closeout page missing'
  assert any(s['frame'].get('lifecycle')=='completed' for s in samples),'completed page missing'
  assert compact['frames']<video['frames']-20,compact
  frames=[json.loads(line) for line in (out/'private/follow.frames.jsonl').read_text().splitlines()]
  kept={i for segment in compact['segments'] for i in range(segment['source_start_frame'],segment['source_end_frame_exclusive'])}
  assert all(f['frame'] in kept for f in frames if f['moving'] or f['visual_change'])
  events=[json.loads(line) for line in (out/'private/simulation/events.jsonl').read_text().splitlines()]
  assert sum(e.get('request',{}).get('id')=='idempotency-check' for e in events)==1
  entries=[e for sample in samples for e in sample['workflow'].get('entries',[])]
  assert any(e.get('text')=='验收演示：' for e in entries),'streamed partial assistant text missing'
  assert any(e.get('text')=='验收演示：正在读取机器人状态。' for e in entries)
  assert any('LIVE_THREE_CAMERA_FIXTURE 3' in e.get('output','') for e in entries)
  assert any(e['title']=='底盘控制' and e['status']=='已接受' for e in entries)
  assert any(e['title']=='底盘控制' and e['status']=='已拒绝' for e in entries)
  assert any(e['title']=='三路新观测已送达' for e in entries)
  assert any(s['workflow']['phase']=='waiting' for s in samples)
  assert any(s['workflow']['phase']=='assistant' for s in samples)
  assert all(s['workflow']['error'] is None for s in samples)
  assert max(s['frame']['frames'] for s in samples)>min(s['frame']['frames'] for s in samples)+30
  assert all(len(s['frame']['views'])==4 for s in samples)
  (out/'private/workflow-live-verification.json').write_text(json.dumps(samples,ensure_ascii=False)+'\n')
  report={'passed':True,'real_model_called':False,'purpose':'synthetic launcher verification, not a formal attempt','native_tools':True,'three_camera_observe':True,'idempotency_preserved':True,'live_monitor':True,'automatic_full_video':video,'automatic_compact_video':compact,'motion_preserved_in_compact':True}
  report['workflow']={'live_samples':len(samples),'partial_text_seen':True,'tool_output_seen':True,'robot_accept_reject_seen':True,'four_cameras_advancing':True}
  report['dashboard_recording']=dashboard
  report['physics_max_lateness_s']=result['max_lateness_s']
  (out/'VERIFICATION.json').write_text(json.dumps(report,indent=2)+'\n');print('PASS',out)
 finally:stop.set();watcher.join(timeout=3);s.shutdown();s.server_close()

if __name__=='__main__': main()
