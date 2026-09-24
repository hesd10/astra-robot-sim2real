"""Fresh native Codex session: Codex owns tools, images and compaction."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
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
    config.setdefault('model', 'gpt-6-astra')
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
    tmp = workspace/'tmp'
    tmp.mkdir(exist_ok=True)
    shell_env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': str(workspace),
                 'TMPDIR': str(tmp), 'ROBOT_MAILBOX': str(workspace/'.robot-mailbox'),
                 'PYTHONPATH': str(ROOT/'.subject-deps'), 'PYTHONDONTWRITEBYTECODE': '1',
                 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1',
                 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': str(workspace/'.gitconfig')}
    config['shell_environment_policy'] = {'inherit': 'none', 'set': shell_env}
    config['permissions'] = {'subject': {
        'filesystem': {':minimal': 'read', str(workspace): 'write',
                       str(ROOT/'.subject-deps'): 'read', str(workspace/'.git'): 'write',
                       '/proc': 'deny'},
        'network': {'enabled': False}}}
    (home/'config.toml').write_text('\n'.join(k+' = '+toml_value(v) for k, v in config.items())+'\n')
    (home/'config.toml').chmod(0o600)
    return home, config, env


def run_agent(workspace, socket_path, private_dir, *, provider=None, reasoning='xhigh',
              max_seconds=3600., prompt=None):
    workspace, private_dir = Path(workspace).resolve(), Path(private_dir).resolve()
    home, config, env = prepare_native(workspace, socket_path, private_dir,
                                       provider=provider, reasoning=reasoning)
    binary = os.environ.get('ASTRA_CODEX_BIN', DEFAULT_CODEX)
    version = subprocess.check_output([binary, '--version'], text=True, stderr=subprocess.DEVNULL).strip()
    result = {'runner': 'native-codex-app-server', 'codex_version': version,
              'model': config['model'], 'reasoning': reasoning,
              'context_management': 'Codex native defaults', 'image_history_limit': None,
              'request_limit': None, 'status': 'starting', 'start_unix': time.time()}
    (private_dir/'native-config-audit.json').write_text(json.dumps({
        **result, 'features': config['features'], 'permission_profile': config['permissions'],
        'source_history_loaded': False, 'operator_camera_exposed': False}, indent=2)+'\n')
    incoming = queue.Queue()
    from .mailbox import Mailbox
    from .workflow import public_event
    mailbox = Mailbox(workspace/'.robot-mailbox', socket_path)
    with (private_dir/'native-stderr.log').open('w') as stderr, \
         (private_dir/'agent-events.jsonl').open('w') as events, \
         (private_dir/'agent-timing.jsonl').open('w') as timing, \
         (private_dir/'agent-workflow.jsonl').open('w') as workflow:
        def publish(row):
            if row is not None:
                workflow.write(json.dumps(row, ensure_ascii=False)+'\n'); workflow.flush()
        publish({'event': 'session/started', 'monotonic': time.monotonic(), 'model': config['model']})
        process = subprocess.Popen([binary, 'app-server'], cwd=workspace, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, text=True)
        def reader():
            try:
                for line in process.stdout:
                    incoming.put((time.monotonic(), json.loads(line)))
            finally:
                incoming.put((time.monotonic(), None))
        threading.Thread(target=reader, daemon=True).start()
        def send(message):
            process.stdin.write(json.dumps(message)+'\n'); process.stdin.flush()
        def record_time(event, stamp=None, **fields):
            timing.write(json.dumps({'event': event, 'monotonic': time.monotonic() if stamp is None else stamp,
                                     **fields})+'\n'); timing.flush()
        def receive(timeout=1):
            received_at, message = incoming.get(timeout=timeout)
            if message is None:
                raise RuntimeError('native Codex exited; inspect private/native-stderr.log')
            events.write(json.dumps(message)+'\n'); events.flush()
            publish(public_event(message, received_at))
            method = message.get('method')
            if method in ('turn/started', 'turn/completed', 'item/started', 'item/completed'):
                item = message.get('params', {}).get('item', {})
                record_time(method, received_at, item_id=item.get('id'), item_type=item.get('type'))
            if 'method' in message and 'id' in message:
                send({'id': message['id'], 'error': {'code': -32601,
                    'message': 'Operator interaction and additional capabilities are unavailable.'}})
            return message
        sequence = 0
        def request(method, params):
            nonlocal sequence
            sequence += 1
            if method == 'turn/start': record_time('turn/requested')
            send({'id': sequence, 'method': method, 'params': params})
            deadline = time.monotonic()+60
            while time.monotonic() < deadline:
                try: message = receive()
                except queue.Empty: continue
                if message.get('id') == sequence and 'method' not in message:
                    if 'error' in message:
                        raise RuntimeError(message['error'].get('message', 'native request failed'))
                    return message['result']
            raise TimeoutError('native Codex initialization timed out')
        try:
            request('initialize', {'clientInfo': {'name': 'astra-local', 'version': '2.0'},
                                   'capabilities': {'experimentalApi': True}})
            send({'method': 'initialized', 'params': {}})
            thread = request('thread/start', {'cwd': str(workspace), 'model': config['model'],
                'permissions': 'subject', 'approvalPolicy': 'never', 'ephemeral': False})
            result['thread_id'] = thread['thread']['id']
            result['resolved_model'] = thread['model']
            if thread['model'] != config['model']:
                raise RuntimeError('native Codex resolved a different model')
            turn = request('turn/start', {'threadId': result['thread_id'], 'effort': reasoning,
                'input': [{'type': 'text', 'text': prompt if prompt is not None else
                           (workspace/'PROMPT.md').read_text(), 'text_elements': []}]})
            turn_id = turn['turn']['id']
            result['status'] = 'running'
            deadline = time.monotonic()+max_seconds
            final_text = []
            while True:
                if time.monotonic() >= deadline:
                    request('turn/interrupt', {'threadId': result['thread_id'], 'turnId': turn_id})
                    result['status'] = 'environment_ended'
                    break
                try: message = receive()
                except queue.Empty: continue
                if message.get('method') == 'item/completed':
                    item = message['params']['item']
                    if item.get('type') == 'agentMessage':
                        final_text.append(item.get('text', ''))
                if message.get('method') == 'turn/completed':
                    completed = message['params']['turn']
                    result['status'] = completed['status']
                    if completed.get('error'):
                        result['error'] = completed['error']
                    break
            (private_dir/'agent-final.txt').write_text('\n\n'.join(final_text)+'\n')
        except BaseException as exc:
            result.update(status='error', error_type=type(exc).__name__)
            raise
        finally:
            record_time('session/ended')
            publish({'event': 'session/ended', 'monotonic': time.monotonic(),
                     'status': result['status'], 'error': result.get('error') or result.get('error_type')})
            mailbox.close()
            process.stdin.close()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            result.update(end_unix=time.time(), exit_code=process.returncode)
            result['elapsed_wall_s'] = result['end_unix']-result['start_unix']
            (private_dir/'agent-result.json').write_text(json.dumps(result, indent=2)+'\n')
            (home/'auth.json').unlink(missing_ok=True)
    return result
