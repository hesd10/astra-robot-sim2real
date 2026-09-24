"""Private real-time service. Public surface: a narrow Unix stream protocol."""
import argparse
from collections import OrderedDict
import gzip
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import signal
import socketserver
import threading
import time
import traceback
import numpy as np
import mujoco
from .core import Core
from .model import OUTPUT, snapshot


def encode(value):
    return json.dumps(value, allow_nan=False, separators=(',', ':'),
                      default=lambda x: x.tolist() if isinstance(x, np.ndarray) else float(x))


class Journal:
    def __init__(self, path):
        self.path = path
        self.queue = queue.Queue(maxsize=2048)
        self.error = None
        self.count = 0
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        try:
            with gzip.open(self.path/'states.jsonl.gz', 'wt', compresslevel=1) as states, (self.path/'events.jsonl').open('w') as events:
                while True:
                    row = self.queue.get()
                    if row is None:
                        return
                    kind, item = row
                    target = states if kind == 'state' else events
                    target.write(encode(item)+'\n')
                    if kind == 'state':
                        self.count += 1
                    else:
                        target.flush()
        except BaseException:
            self.error = 'journal_write_failed'

    def write(self, kind, row):
        if self.error:
            return False
        try:
            if kind == 'event': row = dict(row, monotonic=time.monotonic())
            self.queue.put_nowait((kind, row))
            return True
        except queue.Full:
            self.error = 'journal_overflow'
            return False

    def close(self):
        if self.thread.is_alive():
            try:
                self.queue.put(None, timeout=3)
            except queue.Full:
                self.error = 'journal_shutdown_failed'
            self.thread.join(timeout=10)
            if self.thread.is_alive():
                self.error = 'journal_shutdown_failed'


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(30)
        while True:
            try:
                raw = self.rfile.readline(16385)
                if not raw:
                    return
                if len(raw) > 16384 or not raw.endswith(b'\n'):
                    return
                req = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                if not isinstance(req, dict):
                    raise ValueError()
                result = self.server.service.request(req)
            except (ValueError, TypeError):
                result = {'ok': False, 'error': 'invalid request'}
            except (TimeoutError, OSError):
                return
            except Exception:
                result = {'ok': False, 'error': 'request unavailable'}
            self.wfile.write((encode(result)+'\n').encode())
            self.wfile.flush()


class Service:
    def __init__(self, socket_path, log_dir, *, render=True, width=640, height=480,
                 wall_seconds=None, max_seconds=3600., standoff=.9, lateral=0., yaw=0.,
                 monitor=True, monitor_fps=10, monitor_port=0, workflow_file=None):
        self.socket_path = Path(socket_path)
        if self.socket_path.exists():
            raise RuntimeError('socket path exists; use a fresh run path')
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=False)
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self.core = Core(standoff=standoff, lateral=lateral, yaw=yaw, max_seconds=max_seconds)
        self.journal = Journal(self.log_dir)
        self.commands = queue.Queue(maxsize=32)
        self.status = self.core.status()
        self.schema = self.core.schema()
        self.observations = queue.Queue(maxsize=16)
        self.render_waiters = []
        self.render_busy = False
        self.render_parts = []
        self.render_error = None
        self.stop_event = threading.Event()
        self.wall_seconds = wall_seconds
        self.seen = OrderedDict()
        self.render = render
        self.render_processes = []
        self.in_frames = []
        self.out_frames = None
        self.width, self.height = width, height
        self.monitor_enabled, self.monitor_fps, self.monitor_port = monitor, monitor_fps, monitor_port
        self.workflow_file = workflow_file
        self.monitor = None
        self.manifest = {'protocol': 'astra-sim-v1', 'model_sha256': hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
                         'runtime_sha256': {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},
                         'mujoco_version': mujoco.__version__, 'dt': self.core.dt, 'state_hz': 20,
                         'initialization': {'standoff': standoff, 'lateral': lateral, 'yaw': yaw},
                         'subject_cameras': list(self.schema['cameras']),
                         'presentation_camera': 'live and replay follow, private only',
                         'monitor_fps': monitor_fps if monitor else None,
                         'online_render': {'workers':3, 'shadow_size':1024, 'samples':2, 'reflections':False},
                         'width': width, 'height': height, 'created_unix': time.time(),
                         'render_enabled': render, 'status': 'running'}
        self._manifest()

    def _manifest(self):
        (self.log_dir/'manifest.json').write_text(json.dumps(self.manifest, indent=2)+'\n')

    def request(self, req):
        ident = req.get('id')
        if not isinstance(ident, str) or not 1 <= len(ident) <= 80:
            return {'ok': False, 'error': 'request id required'}
        if req.get('op') == 'observe':
            if set(req) != {'op', 'id'}:
                return {'ok': False, 'error': 'observe has no camera/path parameters'}
            if not self.render or self.render_error:
                return {'ok': False, 'error': 'camera unavailable; retry state/observe'}
            item = {'id': ident, 'reply': queue.Queue(maxsize=1), 'received': time.monotonic()}
            try:
                self.observations.put_nowait(item)
            except queue.Full:
                return {'ok': False, 'error': 'observation queue busy'}
            try:
                return item['reply'].get(timeout=15)
            except queue.Empty:
                return {'ok': False, 'error': 'observation timed out; no cached frame returned'}
        item = {'req': req, 'reply': queue.Queue(maxsize=1), 'received': time.monotonic()}
        try:
            self.commands.put_nowait(item)
        except queue.Full:
            return {'ok': False, 'error': 'command queue busy'}
        try:
            return item['reply'].get(timeout=2)
        except queue.Empty:
            return {'ok': False, 'error': 'ack timeout; reuse the same id to resolve'}

    def _commands(self, now):
        # Bound the work per tick; command flood must not starve physics.
        for _ in range(4):
            try:
                item = self.commands.get_nowait()
            except queue.Empty:
                return
            req = item['req']
            ident = req['id']
            signature = encode(req)
            if ident in self.seen:
                old_signature, reply = self.seen[ident]
                if signature != old_signature:
                    reply = {'ok': False, 'error': 'request id reused with different payload'}
            elif now-item['received'] > .5:
                reply = {'ok': False, 'error': 'expired before execution'}
            else:
                try:
                    result = self.core.dispatch(req, now)
                    reply = {'ok': True, 'result': result}
                except (ValueError, TypeError):
                    reply = {'ok': False, 'error': 'invalid, busy, out of limits, or motion disabled'}
                self.seen[ident] = signature, reply
                self.journal.write('event', {'event': 'request', 'request': req,
                    'accepted': reply['ok'], 'reply': reply,
                    'sim_time': float(self.core.d.time), 'received_monotonic': item['received']})
            item['reply'].put_nowait(reply)

    def _observe(self, now, camera_age):
        if not self.render:
            return
        try:
            frame = self.out_frames.get_nowait()
        except queue.Empty:
            frame = None
        if frame is not None:
            if 'render_error' in frame:
                self.render_error = frame['render_error']
                self.core.trip('camera_failure')
            else:
                self.render_parts.append(frame)
            if len(self.render_parts) == 3:
                frame = dict(self.render_parts[0])
                frame['images'] = {k:v for part in self.render_parts for k,v in part['images'].items()}
                frame['render_started_monotonic'] = min(p['render_started_monotonic'] for p in self.render_parts)
                frame['render_done_monotonic'] = max(p['render_done_monotonic'] for p in self.render_parts)
                self.render_parts = []
                self.render_busy = False
                delivered = time.monotonic()
                age = delivered-frame['sample_monotonic']
                camera_age.append(age)
                for item in self.render_waiters:
                    latency = delivered-item['received']
                    result = dict(frame, age_seconds=age, request_latency_seconds=latency,
                                  request_monotonic=item['received'])
                    item['reply'].put_nowait({'ok': True, 'result': result})
                    self.journal.write('event', {'event': 'observation_delivered', 'id': item['id'],
                        'sim_time': frame['sim_time'], 'age_seconds': age, 'request_latency_seconds': latency,
                        'snapshot_after_request': frame['sample_monotonic'] >= item['received']})
                self.render_waiters = []
        if not all(p.is_alive() for p in self.render_processes):
            self.core.trip('camera_failure')
        # Capture only when requested and when the renderer is free. Concurrent
        # requests present before this snapshot share it; later requests never do.
        if not self.render_busy and not self.render_error:
            for _ in range(16):
                try:
                    item = self.observations.get_nowait()
                except queue.Empty:
                    break
                if now-item['received'] < 14.:
                    self.render_waiters.append(item)
            if self.render_waiters:
                row = dict(snapshot(self.core.m, self.core.d), sample_monotonic=time.monotonic())
                for frames in self.in_frames:
                    frames.put_nowait(row)
                self.render_busy = True

    def run(self):
        try:
            self._run()
        except BaseException:
            if self.monitor: self.monitor.close()
            for process in self.render_processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=3)
            self.journal.close()
            if self.manifest['status']=='running':
                self.manifest.update(status='startup_failed',complete_recording=False)
                self._manifest()
            raise

    def _run(self):
        from .rendering import worker
        if self.render:
            context = mp.get_context('spawn')
            self.out_frames = context.Queue(3)
            for role in self.schema['cameras']:
                frames = context.Queue(1)
                process = context.Process(target=worker, args=(frames, self.out_frames, self.width, self.height,
                    snapshot(self.core.m, self.core.d), role), daemon=True)
                self.in_frames.append(frames)
                self.render_processes.append(process)
                process.start()
            for _ in self.render_processes:
                ready = self.out_frames.get(timeout=60)
                if not ready.get('ready'):
                    raise RuntimeError('renderer startup failed')
        if self.monitor_enabled:
            from .monitor import Monitor
            self.monitor = Monitor(self.log_dir, dict(snapshot(self.core.m, self.core.d),
                sample_monotonic=time.monotonic()), fps=self.monitor_fps, port=self.monitor_port,
                workflow_file=self.workflow_file)
        # Expose the socket only after renderer prewarm, outside timed execution.
        server = Server(str(self.socket_path), Handler)
        server.service = self
        os.chmod(self.socket_path, 0o600)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        start = time.monotonic()
        lateness = []
        max_lateness = 0.
        camera_age = []
        fault_at = None
        finish_at = None
        next_monitor = 0.
        self.journal.write('state', dict(snapshot(self.core.m, self.core.d), sample_monotonic=start))
        try:
            while not self.stop_event.is_set():
                now = time.monotonic()
                if self.wall_seconds and now-start >= self.wall_seconds:
                    break
                self._commands(now)
                self.core.step(now)
                if self.core.steps % 20 == 0:
                    self.status = self.core.status()
                if self.core.steps % 50 == 0:
                    row = dict(snapshot(self.core.m, self.core.d), sample_monotonic=time.monotonic(),
                               motion_command_active=self.core.motion is not None or
                               bool(np.max(np.abs(self.core.base_current)) > 1e-6))
                    self.journal.write('state', row)
                if self.monitor and self.core.d.time >= next_monitor:
                    self.monitor.submit(dict(snapshot(self.core.m, self.core.d),
                        sample_monotonic=time.monotonic(), fault=self.core.fault))
                    next_monitor = float(self.core.d.time)+1./self.monitor_fps
                self._observe(now, camera_age)
                if self.journal.error:
                    self.core.trip('recording_failure')
                if self.monitor and self.monitor.error:
                    self.core.trip('operator_camera_failure')
                for event in self.core.events:
                    self.journal.write('event', event)
                self.core.events.clear()
                if self.core.fault and fault_at is None:
                    fault_at = now
                if self.core.finished and finish_at is None:
                    finish_at = now
                if (fault_at is not None and now-fault_at >= 1.) or (finish_at is not None and now-finish_at >= 1.):
                    break
                deadline = start+self.core.steps*self.core.dt
                delay = deadline-time.monotonic()
                if delay > 0:
                    self.stop_event.wait(delay)
                late = max(0., time.monotonic()-deadline)
                max_lateness = max(max_lateness, late)
                if self.core.steps % 100 == 0:
                    lateness.append(late)
                if late > .5:
                    self.core.trip('realtime_overrun')
            self.core.stop()
        except BaseException:
            self.core.trip('service_exception')
            (self.log_dir/'exception.txt').write_text(traceback.format_exc())
            raise
        finally:
            elapsed = time.monotonic()-start
            self.journal.write('state', dict(snapshot(self.core.m, self.core.d), sample_monotonic=time.monotonic()))
            server.shutdown()
            server.server_close()
            self.socket_path.unlink(missing_ok=True)
            for frames, process in zip(self.in_frames, self.render_processes):
                # Rendering may be slow; shutdown is bounded and never touches other processes.
                try:
                    frames.put_nowait(None)
                except queue.Full:
                    pass
                process.join(timeout=5)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=3)
            self.journal.close()
            if self.monitor: self.monitor.close()
            result = self.core.private_result()
            result.update(wall_seconds=elapsed, max_lateness_s=max_lateness,
                          sampled_lateness_p99_s=float(np.percentile(lateness, 99)) if lateness else None,
                          camera_delivery_age_max_s=max(camera_age, default=None),
                          states_written=self.journal.count, recording_error=self.journal.error)
            result['operator_monitor'] = {'enabled': bool(self.monitor),
                'dropped_snapshots': self.monitor.dropped if self.monitor else 0,
                'error': self.monitor.error if self.monitor else None}
            (self.log_dir/'result.json').write_text(json.dumps(result, indent=2)+'\n')
            self.manifest.update(status='closed', complete_recording=self.journal.error is None)
            self._manifest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--socket-path', required=True)
    parser.add_argument('--log-dir', required=True)
    parser.add_argument('--no-render', action='store_true', help='developer tests only')
    parser.add_argument('--width', type=int, default=640)
    parser.add_argument('--height', type=int, default=480)
    parser.add_argument('--wall-seconds', type=float)
    parser.add_argument('--max-seconds', type=float, default=3600.)
    parser.add_argument('--standoff', type=float, default=.9)
    parser.add_argument('--lateral', type=float, default=0.)
    parser.add_argument('--yaw', type=float, default=0.)
    parser.add_argument('--no-monitor', action='store_true', help='developer tests only')
    parser.add_argument('--monitor-fps', type=int, default=10)
    parser.add_argument('--monitor-port', type=int, default=0)
    parser.add_argument('--workflow-file', help='private normalized native event log for the operator panel')
    args = vars(parser.parse_args())
    args['render'] = not args.pop('no_render')
    args['monitor'] = not args.pop('no_monitor')
    service = Service(**args)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: service.stop_event.set())
    service.run()


if __name__ == '__main__':
    main()
