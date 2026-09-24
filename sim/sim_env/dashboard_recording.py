"""Automatic recording of the real operator webpage in an isolated browser."""
import json
import atexit
import multiprocessing as mp
import os
from pathlib import Path
import signal
import subprocess
import time

from .progress import ExportProgress

ROOT = Path(__file__).resolve().parents[1]


def check_available():
    import importlib.util
    if importlib.util.find_spec('playwright') is None:
        raise RuntimeError('webpage recording requires the project Playwright dependency')
    directory = Path(os.environ.get('PLAYWRIGHT_BROWSERS_PATH', str(ROOT/'.browser-runtime')))
    if not any(directory.rglob('chrome-headless-shell')):
        raise RuntimeError('webpage recording requires Chromium: run scripts/install_dashboard_browser.sh')


def write_report(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    temporary.replace(path)


def capture_worker(url, private, stop, ready, owner_pid):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT/'.browser-runtime'))
    private = Path(private)
    report_path = private/'dashboard-recording.json'
    report = {'status': 'starting', 'width': 1920, 'height': 1080,
              'capture': 'actual operator webpage in an independent browser',
              'page_refresh_fps': 5, 'includes_agent_closeout': True,
              'contains': ['third_person', 'head', 'left_wrist', 'right_wrist', 'visible Astra workflow'],
              'audio': False}
    write_report(report_path, report)
    context = browser = video = None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--disable-gpu'])
            try:
                context = browser.new_context(viewport={'width': 1920, 'height': 1080},
                    record_video_dir=str(private/'dashboard-raw'),
                    record_video_size={'width': 1920, 'height': 1080},
                    device_scale_factor=1, locale='zh-CN')
                # A fresh context reads only this experiment's local operator page.
                context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(url) else route.abort())
                page = context.new_page()
                video = page.video
                report['page_opened_monotonic'] = time.monotonic()
                page.goto(url+'?recording=1', wait_until='load', timeout=30000)
                page.wait_for_function("Array.from(document.querySelectorAll('canvas')).length === 4 && Array.from(document.querySelectorAll('canvas')).every(c => c.dataset.frame)", timeout=30000)
                report.update(status='recording', ready_monotonic=time.monotonic(), started_unix=time.time())
                write_report(report_path, report)
                page.screenshot(path=str(private/'dashboard-first.png'))
                ready.put({'ready': True})
                while not stop.is_set() and os.getppid() == owner_pid:
                    page.wait_for_timeout(250)
                report.update(status='saving', stopped_monotonic=time.monotonic(),
                              stop_reason='experiment ended' if stop.is_set() else 'launcher exited')
                write_report(report_path, report)
                # Let the final completion/closeout text reach the page and remain readable.
                page.wait_for_timeout(1500)
                report['final_page_state'] = {'phase': page.locator('#phase').inner_text(),
                                              'status': page.locator('#status').inner_text()}
                page.screenshot(path=str(private/'dashboard-last.png'))
            finally:
                if context is not None:
                    context.close()
                    if video is not None:
                        raw = Path(video.path())
                        destination = private/'dashboard.webm'
                        raw.replace(destination)
                        report['raw_video'] = str(destination)
                if browser is not None: browser.close()
        report.update(status='captured', capture_closed_monotonic=time.monotonic())
        write_report(report_path, report)
    except BaseException as exc:
        report.update(status='error', error=f'{type(exc).__name__}: {exc}')
        write_report(report_path, report)
        ready.put({'error': report['error']})


class DashboardRecorder:
    def __init__(self, url, private_dir):
        self.private = Path(private_dir)
        context = mp.get_context('spawn')
        self.stop_event = context.Event()
        atexit.register(self.stop_event.set)
        self.ready = context.Queue(2)
        self.process = context.Process(target=capture_worker,
            args=(url, str(self.private), self.stop_event, self.ready, os.getpid()))
        self.process.start()
        try:
            result = self.ready.get(timeout=60)
            if not result.get('ready'):
                raise RuntimeError('automatic webpage recording failed to start: '+result.get('error', 'unknown'))
        except BaseException:
            self.stop_event.set()
            self.process.join(timeout=10)
            if self.process.is_alive(): self.process.terminate(); self.process.join(timeout=5)
            raise

    def stop(self):
        self.stop_event.set()
        atexit.unregister(self.stop_event.set)
        self.process.join(timeout=60)
        if self.process.is_alive():
            self.process.terminate(); self.process.join(timeout=5)
            raise RuntimeError('webpage recorder did not close; inspect dashboard-recording.json')
        report = json.loads((self.private/'dashboard-recording.json').read_text())
        if report['status'] != 'captured':
            raise RuntimeError('webpage recording failed: '+report.get('error', report['status']))
        return report


def export_dashboard(private_dir):
    """Convert the automatically closed browser video into upload-friendly H.264 MP4."""
    private = Path(private_dir)
    source, output = private/'dashboard.webm', private/'dashboard.mp4'
    path = private/'dashboard-recording.json'
    report = json.loads(path.read_text())
    # Count packets without decoding to obtain an exact denominator for progress.
    probe = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-map', '0:v:0',
        '-c', 'copy', '-progress', 'pipe:2', '-f', 'framecrc', '-'], capture_output=True, text=True, check=True)
    info = dict(line.split('=', 1) for line in probe.stderr.splitlines() if '=' in line)
    # VP8 WebM contains one displayed frame per packet. Stream-copy progress
    # omits "frame", so count the packet records produced by framecrc instead.
    total = sum(line.startswith('0,') for line in probe.stdout.splitlines())
    if not total: raise RuntimeError('webpage recording contains no video frames')
    report.update(status='encoding', frames=total)
    write_report(path, report)
    command = ['ffmpeg', '-v', 'error', '-n', '-i', str(source), '-an', '-c:v', 'libx264',
               '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-fps_mode', 'passthrough',
               '-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', str(output)]
    try:
        with ExportProgress('网页录像', total) as progress:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
            try:
                for line in process.stdout:
                    key, _, value = line.strip().partition('=')
                    if key == 'frame': progress.update(int(value))
                progress.finalizing()
                if process.wait(): raise subprocess.CalledProcessError(process.returncode, command)
                if progress.current != total: raise RuntimeError('webpage video frame count mismatch')
            except BaseException:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
                raise
            finally:
                process.stdout.close()
            report.update(status='saved', output=str(output.resolve()), encoding='H.264 / yuv420p',
                          raw_duration_s=int(info['out_time_us'])/1e6,
                          saved_unix=time.time())
            write_report(path, report)
    except BaseException as exc:
        report.update(status='export_error', error=f'{type(exc).__name__}: {exc}')
        write_report(path, report)
        raise
    return report
