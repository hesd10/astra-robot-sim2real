"""Private four-view live monitor. Its queue never blocks the physics owner."""
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit

VIEWS = {
    'third_person': {'label': '第三人称跟随', 'width': 960, 'height': 720},
    'head': {'label': '头部相机', 'width': 640, 'height': 480},
    'left_wrist': {'label': '左腕相机', 'width': 640, 'height': 480},
    'right_wrist': {'label': '右腕相机', 'width': 640, 'height': 480},
}

PAGE_PATH = Path(__file__).with_name('monitor.html')
PAGE = PAGE_PATH.read_text()


def camera_worker(frames, ready, log_dir, initial, fps, port, token, workflow_file):
    os.environ.setdefault('MUJOCO_GL', 'egl')
    import mujoco
    from PIL import Image
    from .model import OUTPUT, restore, CAMERAS
    from .rendering import follow_camera
    from .workflow import Workflow
    log_dir = Path(log_dir)
    workflow = Workflow(log_dir, workflow_file)
    latest = {'images': {}, 'views': {}, 'frames': 0, 'sim_time': 0., 'sample_monotonic': time.monotonic(),
              'fault': None, 'error': None}
    # Keep bounded image batches so four separate HTTP reads use the exact same
    # snapshot even when a newer batch is published between those requests.
    batches = OrderedDict()
    lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            url = urlsplit(self.path)
            path = url.path
            if path in ('/'+token, '/'+token+'/'):
                # UI-only fixes take effect on refresh without restarting an attempt.
                body, mime = PAGE_PATH.read_bytes(), 'text/html; charset=utf-8'
            elif path == '/'+token+'/frame.jpg' or path.startswith('/'+token+'/frame/'):
                role = 'third_person' if path == '/'+token+'/frame.jpg' else path.rsplit('/', 1)[-1].removesuffix('.jpg')
                if role not in VIEWS:
                    self.send_error(404); return
                try:
                    requested = parse_qs(url.query).get('n', [None])[0]
                    requested = int(requested) if requested is not None else None
                except ValueError:
                    self.send_error(400); return
                with lock:
                    batch = batches.get(requested) if requested is not None else latest['images']
                    body = batch.get(role) if batch else None
                if body is None:
                    self.send_error(410, 'Frame expired; fetch current status'); return
                mime = 'image/jpeg'
            elif path == '/'+token+'/status':
                with lock: status = {k: v for k, v in latest.items() if k != 'images'}
                status['age_seconds'] = time.monotonic()-status['sample_monotonic']
                body, mime = json.dumps(status).encode(), 'application/json'
            elif path == '/'+token+'/workflow':
                try:
                    since = int(parse_qs(url.query).get('since', ['-1'])[0])
                except ValueError:
                    self.send_error(400); return
                body, mime = json.dumps(workflow.snapshot(since), ensure_ascii=False).encode(), 'application/json'
            else:
                self.send_error(404); return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try: self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError): pass
    server = None
    count = 0
    max_age = 0.
    prewarm_age = None
    error = None
    try:
        m = mujoco.MjModel.from_xml_path(str(OUTPUT)); d = mujoco.MjData(m)
        m.vis.quality.shadowsize = 1024; m.vis.quality.offsamples = 2
        with mujoco.Renderer(m, height=720, width=960) as renderer, \
             mujoco.Renderer(m, height=480, width=640) as onboard:
            row = initial
            while row is not None:
                restore(m, d, row)
                images = {}
                for role in VIEWS:
                    active = renderer if role == 'third_person' else onboard
                    camera = follow_camera(m, d) if role == 'third_person' else CAMERAS[role]
                    active.update_scene(d, camera=camera)
                    active.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION] = False
                    output = io.BytesIO()
                    Image.fromarray(active.render()).save(output, format='JPEG', quality=88 if role == 'third_person' else 85)
                    images[role] = output.getvalue()
                count += 1
                age = time.monotonic()-row['sample_monotonic']
                if count == 1: prewarm_age = age
                else: max_age = max(max_age, age)
                with lock:
                    batches[count] = images
                    while len(batches) > 8: batches.popitem(last=False)
                    latest.update(images=images, views={role: dict(spec, sim_time=row['sim_time']) for role, spec in VIEWS.items()},
                                  frames=count, sim_time=row['sim_time'],
                                  sample_monotonic=row['sample_monotonic'], fault=row.get('fault'))
                if server is None:
                    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
                    threading.Thread(target=server.serve_forever, daemon=True).start()
                    info = {'url': f'http://127.0.0.1:{server.server_port}/{token}/',
                            'fps_target': fps, 'width': 960, 'height': 720,
                            'camera': 'private lobby-side position follow', 'views': VIEWS,
                            'capture': 'one state snapshot shared by all four monitor views',
                            'agent_observations': 'independent on-demand fresh captures',
                            'workflow': 'native visible events and robot receipts; read-only',
                            'workflow_mode': 'live' if workflow_file else 'preview'}
                    (log_dir/'monitor.json').write_text(json.dumps(info, indent=2)+'\n')
                    ready.put({'ready': True, **info})
                row = frames.get()
    except BaseException as exc:
        error = type(exc).__name__
        ready.put({'error': error})
    finally:
        workflow.close()
        if server: server.shutdown(); server.server_close()
        for role, jpeg in latest['images'].items():
            (log_dir/f'monitor-last-{role}.jpg').write_bytes(jpeg)
        if latest['images']: (log_dir/'monitor-last.jpg').write_bytes(latest['images']['third_person'])
        (log_dir/'monitor-result.json').write_text(json.dumps({
            'frames': count, 'max_age_seconds': max_age, 'prewarm_age_seconds': prewarm_age, 'error': error,
            'last_sim_time': latest['sim_time'], 'views': VIEWS}, indent=2)+'\n')


class Monitor:
    def __init__(self, log_dir, initial, *, fps=10, port=0, workflow_file=None):
        if not 1 <= fps <= 20: raise ValueError('monitor fps must be 1..20')
        context = mp.get_context('spawn')
        self.frames = context.Queue(1); self.ready = context.Queue(2)
        self.process = context.Process(target=camera_worker, args=(self.frames, self.ready,
            str(log_dir), initial, fps, port, secrets.token_urlsafe(24), workflow_file), daemon=True)
        self.dropped = 0
        self.error = None
        self.process.start()
        try:
            self.info = self.ready.get(timeout=60)
            if not self.info.get('ready'): raise RuntimeError('operator camera startup failed')
        except BaseException:
            self.process.terminate(); self.process.join(timeout=5); raise

    def submit(self, row):
        if not self.process.is_alive():
            self.error = 'operator_camera_exited'; return
        try: self.frames.put_nowait(row)
        except queue.Full: self.dropped += 1

    def close(self):
        try: self.frames.put(None, timeout=2)
        except queue.Full: pass
        self.process.join(timeout=5)
        if self.process.is_alive():
            self.error = 'operator_camera_shutdown_timeout'
            self.process.terminate(); self.process.join(timeout=3)
