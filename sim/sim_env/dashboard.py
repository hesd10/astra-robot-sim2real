"""Operator page that outlives physics so the recording includes Astra closeout."""
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import build_opener, ProxyHandler

from .monitor import VIEWS, PAGE_PATH
from .workflow import Workflow


class Dashboard:
    """Cache the existing monitor's JPEGs; never renders or sends robot commands."""
    def __init__(self, private_dir, source_url):
        self.private = Path(private_dir)
        self.simulation = self.private/'simulation'
        self.source = source_url
        self.workflow = Workflow(self.simulation, self.private/'agent-workflow.jsonl')
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.latest = None
        self.batches = OrderedDict()
        self.recording = 'starting'
        self.error = None
        token = secrets.token_urlsafe(24)
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                url = urlsplit(self.path)
                path = url.path
                if path in ('/'+token, '/'+token+'/'):
                    body, mime = PAGE_PATH.read_bytes(), 'text/html; charset=utf-8'
                elif path == '/'+token+'/status':
                    status = dashboard.status()
                    if status is None:
                        self.send_error(503, 'Waiting for first camera batch'); return
                    body, mime = json.dumps(status).encode(), 'application/json'
                elif path == '/'+token+'/workflow':
                    try: since = int(parse_qs(url.query).get('since', ['-1'])[0])
                    except ValueError:
                        self.send_error(400); return
                    body = json.dumps(dashboard.workflow.snapshot(since), ensure_ascii=False).encode()
                    mime = 'application/json'
                elif path.startswith('/'+token+'/frame/'):
                    role = path.rsplit('/', 1)[-1].removesuffix('.jpg')
                    try: number = int(parse_qs(url.query).get('n', ['-1'])[0])
                    except ValueError:
                        self.send_error(400); return
                    with dashboard.lock: body = dashboard.batches.get(number, {}).get(role)
                    if body is None:
                        self.send_error(410); return
                    mime = 'image/jpeg'
                else:
                    self.send_error(404); return
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                try: self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError): pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}/{token}/'
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.poll_thread = threading.Thread(target=self.poll, daemon=True)
        self.server_thread.start(); self.poll_thread.start()
        (self.private/'dashboard.json').write_text(json.dumps({
            'url': self.url, 'camera_source_url': source_url, 'viewport': [1920, 1080],
            'recording': 'automatic independent browser', 'output': 'dashboard.mp4',
            'lifetime': 'includes robot operation and native agent closeout'}, indent=2)+'\n')

    def status(self):
        with self.lock:
            if self.latest is None: return None
            result = dict(self.latest)
        result['age_seconds'] = max(0., time.monotonic()-result['sample_monotonic'])
        result['recording'] = self.recording
        for name, key in [('simulation/result.json', 'physical_result'), ('agent-result.json', 'agent_result')]:
            try:
                data = json.loads((self.private/name).read_text())
                result[key] = {k: data[k] for k in ('physical_success', 'fault', 'status') if k in data}
            except (OSError, ValueError): pass
        result['lifecycle'] = ('completed' if 'agent_result' in result and 'physical_result' in result else
                               'closing' if 'physical_result' in result else 'running')
        return result

    def poll(self):
        client = build_opener(ProxyHandler({}))
        last = None
        final_loaded = False
        while not self.stop_event.is_set():
            try:
                with client.open(self.source+'status', timeout=1) as response:
                    status = json.load(response)
                if status['frames'] != last:
                    images = {}
                    for role in VIEWS:
                        with client.open(self.source+f'frame/{role}.jpg?n={status["frames"]}', timeout=1) as response:
                            images[role] = response.read()
                    last = status['frames']
                    self.publish(status, images)
            except (OSError, ValueError):
                # Once physics stops, preserve its final images while workflow keeps streaming.
                if not final_loaded and (self.simulation/'result.json').exists():
                    try:
                        meta = json.loads((self.simulation/'monitor-result.json').read_text())
                        images = {role: (self.simulation/f'monitor-last-{role}.jpg').read_bytes() for role in VIEWS}
                        with self.lock: prior = dict(self.latest or {})
                        status = dict(prior, frames=(last or 0)+1, sim_time=meta['last_sim_time'],
                                      views={role: dict(spec, sim_time=meta['last_sim_time']) for role, spec in VIEWS.items()})
                        status.setdefault('sample_monotonic', time.monotonic())
                        self.publish(status, images)
                        final_loaded = True
                    except (OSError, ValueError): pass
            self.stop_event.wait(.1)

    def publish(self, status, images):
        with self.lock:
            self.batches[status['frames']] = images
            while len(self.batches) > 8: self.batches.popitem(last=False)
            self.latest = status

    def close(self):
        self.stop_event.set()
        self.poll_thread.join(timeout=6)
        self.server.shutdown(); self.server.server_close()
        self.server_thread.join(timeout=2)
        self.workflow.close(self.private/'dashboard-workflow-last.json')
