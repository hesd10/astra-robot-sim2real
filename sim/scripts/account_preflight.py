"""Read the launcher's account, quota and model catalog; no thread or model turn."""
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim_env.agent import DEFAULT_CODEX, prepare_native


def preflight(expected_model='gpt-6-astra', expected_effort='xhigh'):
    if os.environ.get('ASTRA_BASE_URL'):
        raise RuntimeError('This frozen batch requires the ChatGPT account, not a provider override')
    with tempfile.TemporaryDirectory(prefix='astra-account-preflight-') as folder:
        folder = Path(folder)
        workspace = folder/'workspace'; workspace.mkdir()
        private = folder/'private'; private.mkdir()
        home, config, env = prepare_native(workspace, folder/'unused.sock', private,
                                           reasoning=expected_effort)
        if config['model'] != expected_model or config.get('model_provider') not in (None, 'openai'):
            raise RuntimeError('Launcher model/provider does not match frozen experiment')
        auth = json.loads((home/'auth.json').read_text())
        account_id = auth.get('tokens', {}).get('account_id')
        if not account_id:
            raise RuntimeError('No ChatGPT account identity in launcher credentials')
        fingerprint = hashlib.sha256(account_id.encode()).hexdigest()
        del auth, account_id
        inbox = queue.Queue()
        process = subprocess.Popen([os.environ.get('ASTRA_CODEX_BIN', DEFAULT_CODEX), 'app-server'],
                                   cwd=workspace, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        def reader():
            try:
                for line in process.stdout:
                    inbox.put(json.loads(line))
            finally:
                inbox.put(None)
        threading.Thread(target=reader, daemon=True).start()
        sequence = 0
        def send(value):
            process.stdin.write(json.dumps(value)+'\n'); process.stdin.flush()
        def request(method, params):
            nonlocal sequence
            sequence += 1
            send({'id': sequence, 'method': method, 'params': params})
            deadline = time.monotonic()+45
            while time.monotonic() < deadline:
                try: item = inbox.get(timeout=min(1, max(.01, deadline-time.monotonic())))
                except queue.Empty: continue
                if item is None:
                    raise RuntimeError('Account preflight app-server exited')
                if item.get('id') == sequence and 'method' not in item:
                    if 'error' in item:
                        raise RuntimeError(f'{method}: {item["error"].get("message", "request failed")}')
                    return item['result']
                if 'id' in item and 'method' in item:
                    send({'id': item['id'], 'error': {'code': -32601, 'message': 'Read-only preflight'}})
            raise TimeoutError('Account preflight timed out: '+method)
        try:
            request('initialize', {'clientInfo': {'name': 'astra-quota-preflight', 'version': '1.0'},
                                   'capabilities': {'experimentalApi': True}})
            send({'method': 'initialized', 'params': {}})
            account = request('account/read', {'refreshToken': False}).get('account') or {}
            if account.get('type') != 'chatgpt':
                raise RuntimeError('Launcher did not authenticate with ChatGPT')
            limits = request('account/rateLimits/read', {})
            bucket = (limits.get('rateLimitsByLimitId') or {}).get('codex') or limits.get('rateLimits')
            if not bucket:
                raise RuntimeError('No Codex quota returned')
            model = None; cursor = None
            for _ in range(10):
                params = {'limit': 100}
                if cursor: params['cursor'] = cursor
                catalog = request('model/list', params)
                model = next((x for x in catalog['data'] if x.get('model') == expected_model), None)
                if model: break
                cursor = catalog.get('nextCursor')
                if not cursor: break
            efforts = [x.get('reasoningEffort') for x in (model or {}).get('supportedReasoningEfforts', [])]
            if not model or expected_effort not in efforts:
                raise RuntimeError('Requested model/effort is absent from account model catalog')
            windows = []
            for key in ('primary', 'secondary'):
                w = bucket.get(key)
                if w and isinstance(w.get('usedPercent'), (int, float)):
                    windows.append({'name': key, **w, 'remaining_percent': max(0, 100-w['usedPercent'])})
            if not windows:
                raise RuntimeError('No measurable account quota window')
            return {'checked_unix': time.time(), 'account_fingerprint': fingerprint,
                    'plan': bucket.get('planType') or account.get('planType'), 'model': expected_model,
                    'effort': expected_effort, 'catalog_available': True, 'windows': windows,
                    'minimum_remaining_percent': min(w['remaining_percent'] for w in windows),
                    'spend_control_reached': bucket.get('spendControlReached'),
                    'rate_limit_reached_type': bucket.get('rateLimitReachedType'),
                    'reset_credits_consumed': False, 'model_turns_started': 0}
        finally:
            process.stdin.close()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            process.stdout.close()


if __name__ == '__main__':
    print(json.dumps(preflight(), ensure_ascii=False, indent=2))
