"""Fresh native Codex session: Codex owns tools, images and compaction."""
import json
import hashlib
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT.parents[1]/'mujoco_astra_local_20260917_final/.subject-deps'
DEFAULT_CODEX = '/usr/lib/chatgpt/resources/codex'


def toml_value(value):
    if isinstance(value, dict):
        return '{' + ', '.join(json.dumps(k)+' = '+toml_value(v) for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '['+', '.join(toml_value(v) for v in value)+']'
    return json.dumps(value, ensure_ascii=False)


def prepare_native(workspace, socket_path, private_dir, *, provider=None, reasoning='xhigh'):
    """Whitelist configuration, never import user instructions/skills/history."""
    home = private_dir/'codex-home'
    home.mkdir(mode=0o700, exist_ok=False)
    source_home = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))
    source_config = source_home/'config.toml'
    host = tomllib.loads(source_config.read_text()) if source_config.exists() else {}
    config = {k: host[k] for k in ('model', 'model_provider', 'model_providers') if k in host}
    config['model'] = 'gpt-6-astra' # Freeze the named experiment model, regardless of host UI changes.
    config.update(model_reasoning_effort=reasoning, approval_policy='never',
                  default_permissions='subject', web_search='disabled', project_doc_max_bytes=0)
    # Native image/compaction features and token thresholds retain their defaults.
    config['features'] = {k: False for k in (
        'apps', 'plugins', 'memories', 'multi_agent', 'browser_use', 'computer_use',
        'image_generation', 'workspace_dependencies', 'shell_snapshot', 'tool_suggest')}
    config['features']['skip_host_skill_discovery'] = True
    if provider is None and os.environ.get('ASTRA_BASE_URL'):
        provider = {'base_url': os.environ['ASTRA_BASE_URL'],
                    'token': os.environ['ASTRA_API_KEY'], 'model': os.environ['ASTRA_MODEL']}
    env = {k: v for k, v in os.environ.items() if k in (
        'PATH', 'LANG', 'LC_ALL', 'USER', 'LOGNAME', 'HOME', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
        'HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'NO_PROXY',
        'https_proxy', 'http_proxy', 'all_proxy', 'no_proxy')}
    env['CODEX_HOME'] = str(home)
    if provider is not None:
        config.update(model=provider['model'], model_provider='experiment')
        config['model_providers'] = {'experiment': {
            'name': 'Experiment Responses provider', 'base_url': provider['base_url'],
            'env_key': 'ASTRA_NATIVE_TOKEN', 'wire_api': 'responses',
            'supports_websockets': False, 'request_max_retries': 0, 'stream_max_retries': 0}}
        env['ASTRA_NATIVE_TOKEN'] = provider['token']
    else:
        for filename in ('auth.json', 'models_cache.json'):
            source = source_home/filename
            if source.is_file():
                shutil.copyfile(source, home/filename)
                (home/filename).chmod(0o600)
        for details in config.get('model_providers', {}).values():
            key = details.get('env_key')
            if key and key in os.environ:
                env[key] = os.environ[key]
    identity={'auth_source':str(source_home),'provider':config.get('model_provider','openai'),'chatgpt_account_fingerprint':None}
    if provider is None and (source_home/'auth.json').exists():
        auth=json.loads((source_home/'auth.json').read_text());account=(auth.get('tokens') or {}).get('account_id')
        if account:identity['chatgpt_account_fingerprint']=hashlib.sha256(account.encode()).hexdigest()[:16]
    (private_dir/'account-audit.json').write_text(json.dumps(identity,indent=2))
    tmp = workspace/'tmp'
    tmp.mkdir(exist_ok=True)
    shell_env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': str(workspace),
                 'TMPDIR': str(tmp), 'ROBOT_MAILBOX': str(workspace/'.robot-mailbox'),
                 'PYTHONPATH': str(DEPS), 'PYTHONDONTWRITEBYTECODE': '1',
                 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1',
                 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': str(workspace/'.gitconfig')}
    config['shell_environment_policy'] = {'inherit': 'none', 'set': shell_env}
    config['permissions'] = {'subject': {
        'filesystem': {':minimal': 'read', str(workspace): 'write',
                       str(DEPS): 'read', str(workspace/'.git'): 'write',
                       '/proc': 'deny'},
        'network': {'enabled': False}}}
    (home/'config.toml').write_text('\n'.join(k+' = '+toml_value(v) for k, v in config.items())+'\n')
    (home/'config.toml').chmod(0o600)
    return home, config, env


def run_agent(workspace, socket_path, private_dir, gate, *, reasoning='xhigh', max_seconds=1800., prompt=None, provider=None):
    """Fresh isolated native session, with unsolicited operator turn/steer delivery."""
    from .mailbox import Mailbox
    from .workflow import public_event
    workspace=Path(workspace).resolve();private_dir=Path(private_dir).resolve()
    home,config,env=prepare_native(workspace,socket_path,private_dir,provider=provider,reasoning=reasoning)
    binary=os.environ.get('ASTRA_CODEX_BIN',DEFAULT_CODEX)
    audit={'model':config['model'],'reasoning':reasoning,'features':config['features'],'permissions':config['permissions'],'source_history_loaded':False}
    (private_dir/'native-config-audit.json').write_text(json.dumps(audit,indent=2))
    inbox=queue.Queue();pending={};seq=0;thread_id=None;active_turn=None;completed=[];result={'status':'initializing'}
    mailbox=Mailbox(workspace/'.robot-mailbox',socket_path)
    with (private_dir/'native-stderr.log').open('w') as err,(private_dir/'agent-events.jsonl').open('w') as log,(private_dir/'agent-workflow.jsonl').open('w') as workflow:
        process=subprocess.Popen([binary,'app-server'],cwd=workspace,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,text=True)
        def reader():
            try:
                for line in process.stdout:inbox.put(json.loads(line))
            finally:inbox.put(None)
        threading.Thread(target=reader,daemon=True).start()
        def send(method,params,tag=None):
            nonlocal seq
            seq+=1;pending[seq]=(method,tag);process.stdin.write(json.dumps({'id':seq,'method':method,'params':params})+'\n');process.stdin.flush();return seq
        def receive(timeout=.1):
            nonlocal active_turn
            m=inbox.get(timeout=timeout)
            if m is None:raise RuntimeError('Native runner exited')
            log.write(json.dumps(m)+'\n');log.flush()
            row=public_event(m,time.monotonic())
            if row:workflow.write(json.dumps(row,ensure_ascii=False)+'\n');workflow.flush()
            method=m.get('method');params=m.get('params',{})
            if method=='turn/started':active_turn=params['turn']['id']
            if method=='turn/completed':
                if active_turn==params['turn']['id']:active_turn=None
                completed.append(params['turn'])
            if method=='item/started' and gate.t0 and not result.get('first_item_unix'):
                result['first_item_unix']=time.time();gate.record('first_native_item',unix_received=result['first_item_unix'])
            if method and 'id' in m:process.stdin.write(json.dumps({'id':m['id'],'error':{'code':-32601,'message':'Additional capabilities unavailable; operator outcomes arrive proactively.'}})+'\n');process.stdin.flush()
            return m
        def request(method,params):
            request_id=send(method,params);deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                try:m=receive()
                except queue.Empty:continue
                if m.get('id')==request_id and 'method' not in m:
                    pending.pop(request_id,None)
                    if 'error' in m:raise RuntimeError(m['error'].get('message','Native request failed'))
                    return m['result']
            raise TimeoutError('Native initialization timeout')
        def text_input(text):return [{'type':'text','text':text,'text_elements':[]}]
        try:
            request('initialize',{'clientInfo':{'name':'astra-real','version':'1.0'},'capabilities':{'experimentalApi':True}})
            process.stdin.write(json.dumps({'method':'initialized','params':{}})+'\n');process.stdin.flush()
            t=request('thread/start',{'cwd':str(workspace),'model':config['model'],'permissions':'subject','approvalPolicy':'never','ephemeral':False})
            thread_id=t['thread']['id'];result['thread_id']=thread_id
            if t['model']!=config['model']:raise RuntimeError('Resolved model differs')
            # Exact timing origin immediately before sending the first task request.
            gate.start();deadline=time.monotonic()+max_seconds
            send('turn/start',{'threadId':thread_id,'effort':reasoning,'input':text_input(prompt or (workspace/'PROMPT.md').read_text())},'initial')
            result['status']='running';terminal_since=None
            while True:
                if time.monotonic()>=deadline and not gate.terminal:gate.end('failure','timeout')
                if gate.terminal and terminal_since is None:terminal_since=time.monotonic()
                if terminal_since is not None and time.monotonic()-terminal_since>45:break
                in_flight={tag for _,tag in pending.values() if isinstance(tag,str)}
                for event in gate.pending():
                    eid=event['event_id']
                    if eid in in_flight:continue
                    # A start request may not yet have produced its turn id.
                    if any(method=='turn/start' for method,_ in pending.values()):break
                    message='Operator outcome event (authorized result feedback):\n'+json.dumps(event)+'\nAcknowledge via ack_events(event_ids=[event_id]). '+('Motion is stopped and locked; write your report and finish.' if event['outcome'] in ('success','wrong_button','stop') else 'The task is not yet successful; continue observing and adjusting. Do not request further confirmation.')
                    params={'threadId':thread_id,'input':text_input(message)}
                    if active_turn:
                        params['expectedTurnId']=active_turn;send('turn/steer',params,eid)
                    else:
                        params['effort']=reasoning;send('turn/start',params,eid)
                try:m=receive()
                except queue.Empty:continue
                if 'id' in m and 'method' not in m:
                    method,tag=pending.pop(m['id'],(None,None))
                    if 'error' in m:
                        if method=='turn/steer':
                            gate.record('delivery_retry',event_id=tag,error=m['error']);active_turn=None
                        else:raise RuntimeError(m['error'].get('message','Native request failed'))
                    elif tag not in (None,'initial'):
                        gate.delivered(tag)
                    if method=='turn/start' and 'result' in m:active_turn=m['result']['turn']['id']
                if m.get('method')=='turn/completed':
                    done=m['params']['turn']
                    if done.get('status')=='failed':raise RuntimeError(str(done.get('error')))
                    if not gate.pending() and not pending:
                        if gate.terminal or gate.finished_by_agent:break
                        if not gate.waiting:
                            gate.end('failure','agent_ended_without_finish');break
            result['status']='completed';result['terminal']=gate.terminal
        except BaseException as e:
            result.update(status='error',error=str(e))
            try:gate.end('failure','runner_error')
            except Exception:pass
            raise
        finally:
            if active_turn and process.poll() is None:
                try:send('turn/interrupt',{'threadId':thread_id,'turnId':active_turn})
                except Exception:pass
            mailbox.close()
            process.stdin.close()
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
            result.update(end_unix=time.time(),t0=gate.t0,elapsed_wall_s=time.time()-gate.t0 if gate.t0 else None)
            (private_dir/'agent-result.json').write_text(json.dumps(result,indent=2))
            (home/'auth.json').unlink(missing_ok=True)
    return result
