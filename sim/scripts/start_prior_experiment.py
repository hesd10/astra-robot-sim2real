"""Prior-study launcher; legacy start_experiment.py remains unchanged."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sim_env.agent import run_agent
from prior_materials import prepare_subject, hashes, write_json
from sim_env.setup import load_setup


def start(name, *, prepare_only=False, max_seconds=1800., reasoning='xhigh', input_dir=None, reference=None,
          monitor_port=0, monitor_fps=10, no_video=False, setup=None, no_dashboard_video=False):
    if not name or any(x not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for x in name):
        raise ValueError('use a simple unique run name')
    setup_record=load_setup(setup) if setup else None
    record_dashboard=not no_video and not no_dashboard_video
    if record_dashboard and not prepare_only:
        from sim_env.dashboard_recording import check_available
        check_available()
    if not input_dir or not reference: raise ValueError('frozen inputs and reference required')
    run=ROOT/'experiments'/name
    if run.exists():raise RuntimeError('run already exists; never overwrite or silently resume an attempt')
    run.mkdir(parents=True)
    input_dir = Path(input_dir).resolve()
    input_sha256 = hashes(input_dir)
    subject=prepare_subject(run/'subject', input_dir, input_sha256)
    private=run/'private';private.mkdir()
    write_json(private/'prior-input-audit.json', {'sha256': input_sha256, 'source': str(input_dir)})
    configuration={'run':name,'max_seconds':max_seconds,'max_requests':None,'reasoning':reasoning,
                   'runner':'native-codex-app-server','context_management':'Codex native defaults',
                   'image_history_limit':None,'monitor_fps':monitor_fps,'export_video':not no_video,
                   'operator_workflow':True,
                   'automatic_dashboard_video':record_dashboard,
                   'setup':setup_record,
                   'cameras':['head','left_wrist','right_wrist'],'display_camera':'private live follow and replay',
                   'skill_transfer':'none; independent attempt', 'prior_input_sha256':input_sha256,
                   'task_budget_seconds':max_seconds, 'agent_session_budget_seconds':max_seconds+180.,'ready':True}
    (private/'launch.json').write_text(json.dumps(configuration,indent=2)+'\n')
    if prepare_only:
        print('Prepared only:',run)
        return run
    sock=Path('/tmp')/('astra-'+uuid.uuid4().hex[:16]+'.sock')
    service_args=[sys.executable,str(ROOT/'scripts/prior_service.py'),'--reference',str(reference),'--socket-path',str(sock),
                  '--log-dir',str(private/'simulation'),'--max-seconds',str(max_seconds),
                  '--monitor-port',str(monitor_port),'--monitor-fps',str(monitor_fps),
                  '--workflow-file',str(private/'agent-workflow.jsonl')]
    if setup_record:
        for key,value in setup_record['parameters'].items():
            service_args.extend(['--'+key,str(value)])
    dashboard=recorder=None
    recording_error=None
    with (private/'service.log').open('w') as log:
        service=subprocess.Popen(service_args,cwd=ROOT,stdout=log,stderr=log)
        try:
            deadline=time.monotonic()+90
            while not sock.exists():
                if service.poll() is not None or time.monotonic()>deadline:
                    raise RuntimeError('simulation failed before ready')
                time.sleep(.1)
            monitor=json.loads((private/'simulation'/'monitor.json').read_text())
            operator_url=monitor['url']
            if record_dashboard:
                from sim_env.dashboard import Dashboard
                from sim_env.dashboard_recording import DashboardRecorder
                dashboard=Dashboard(private,monitor['url'])
                recorder=DashboardRecorder(dashboard.url,private)
                dashboard.recording='recording'
                operator_url=dashboard.url
                print('网页自动录像已启动：四路画面 + Astra 指令流，结束后保存为 private/dashboard.mp4。',flush=True)
            print('Live operator camera:',operator_url,flush=True)
            print('Environment ready; starting a fresh native Codex attempt:',name,flush=True)
            result=run_agent(subject,sock,private,max_seconds=max_seconds+180.,reasoning=reasoning)
            if result['status']=='failed':
                raise RuntimeError('native Codex turn failed; inspect private/agent-result.json')
        finally:
            if service.poll() is None and sock.exists():
                try:
                    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as channel:
                        channel.settimeout(3);channel.connect(str(sock))
                        channel.sendall((json.dumps({'op':'finish','id':uuid.uuid4().hex,'outcome':'failure'})+'\n').encode())
                        channel.recv(65536)
                    (private/'operator-closeout.json').write_text(json.dumps({'reason':'agent ended; preserve an existing finish or close an unfinished attempt as failure'})+'\n')
                    service.wait(timeout=15)
                except (OSError,subprocess.TimeoutExpired):
                    service.terminate();service.wait(timeout=15)
            elif service.poll() is None:
                service.terminate();service.wait(timeout=15)
            if recorder:
                dashboard.recording='saving'
                print('Astra 已结束，正在自动停止并保存网页录像…',flush=True)
                try: recorder.stop()
                except Exception as exc:
                    recording_error=exc
                    print('网页录像保存异常：',exc,flush=True)
            if dashboard: dashboard.close()
            if recorder and recording_error is None:
                from sim_env.dashboard_recording import export_dashboard
                try:
                    export_dashboard(private)
                    print('网页录像已保存：',private/'dashboard.mp4',flush=True)
                except Exception as exc:
                    recording_error=exc
                    print('网页录像转码异常，原始 WebM 保留：',exc,flush=True)
            if not no_video and (private/'simulation'/'result.json').exists():
                from sim_env.rendering import replay_pair
                print('正在导出两版第三人称录像，进度显示在本终端；请等待导出完成。',flush=True)
                replay_pair(private/'simulation',private/'follow.mp4')
    if recording_error is not None:
        raise RuntimeError('attempt preserved, but webpage video export failed') from recording_error
    print('Attempt archived:',run,flush=True)
    print('本轮已归档，后台处理已结束，可以关闭终端。任务是否成功请查看 private/simulation/result.json。',flush=True)
    return run


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('name')
    p.add_argument('--prepare-only',action='store_true')
    p.add_argument('--max-seconds',type=float,default=1800.)
    p.add_argument('--reasoning',choices=['medium','high','xhigh'],default='xhigh')
    p.add_argument('--input-dir',required=True)
    p.add_argument('--reference',required=True)
    p.add_argument('--setup',help='private starting-pose JSON; omitted means the original nearby pilot pose')
    p.add_argument('--monitor-port',type=int,default=0,help='loopback only; 0 selects a free port')
    p.add_argument('--monitor-fps',type=int,default=10)
    p.add_argument('--no-video',action='store_true',help='disable automatic webpage recording and replay exports; keep states and live view')
    p.add_argument('--no-dashboard-video',action='store_true',help='disable only automatic webpage recording')
    a=p.parse_args();start(**vars(a))
