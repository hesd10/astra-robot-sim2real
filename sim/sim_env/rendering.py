"""Private asynchronous rendering and offline presentation-camera replay."""
import argparse
import base64
import gzip
import io
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import time
import numpy as np
from .progress import ExportProgress


def follow_camera(m, d):
    import mujoco
    camera = mujoco.MjvCamera()
    chassis = d.body('chassis')
    camera.lookat[:] = chassis.xpos + np.array([0, 0, .25])
    camera.distance = 2.1
    # Follow position while preserving a lobby-side angle. Rotating this camera
    # with chassis yaw can put it behind the elevator wall during a base turn.
    camera.azimuth = 45.
    camera.elevation = -20.
    return camera


def worker(input_queue, output_queue, width, height, warm_snapshot, role):
    os.environ.setdefault('MUJOCO_GL', 'egl')
    os.environ.setdefault('LP_NUM_THREADS', '2')
    import mujoco
    from PIL import Image
    from .model import OUTPUT, restore, CAMERAS
    try:
        m = mujoco.MjModel.from_xml_path(str(OUTPUT))
        d = mujoco.MjData(m)
        m.vis.quality.shadowsize = 1024
        m.vis.quality.offsamples = 2
        cameras = {role: CAMERAS[role]}
        with mujoco.Renderer(m, height=height, width=width) as renderer:
            restore(m, d, warm_snapshot)
            for xml in cameras.values():
                renderer.update_scene(d, camera=xml)
                renderer.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION] = False
                renderer.render()
            output_queue.put({'ready': True, 'role': role})
            while True:
                row = input_queue.get()
                if row is None:
                    return
                restore(m, d, row)
                render_started = time.monotonic()
                images = {}
                for public, xml in cameras.items():
                    renderer.update_scene(d, camera=xml)
                    renderer.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION] = False
                    out = io.BytesIO()
                    Image.fromarray(renderer.render()).save(out, format='JPEG', quality=85)
                    images[public] = base64.b64encode(out.getvalue()).decode('ascii')
                result = {'sim_time': row['sim_time'], 'sample_monotonic': row['sample_monotonic'],
                          'render_started_monotonic': render_started,
                          'render_done_monotonic': time.monotonic(), 'images': images,
                          'encoding': 'jpeg/base64', 'width': width, 'height': height}
                output_queue.put(result)
    except BaseException as exc:
        output_queue.put({'render_error': type(exc).__name__, 'role': role})


def replay_frame_count(states_path, fps, max_frames=None):
    """Count timestamp-resampled frames without loading the recording into memory."""
    if fps <= 0 or (max_frames is not None and max_frames <= 0):
        raise ValueError('fps and max_frames must be positive')
    first = last = None
    with gzip.open(states_path, 'rt') as stream:
        for line in stream:
            stamp = json.loads(line)['sim_time']
            if not math.isfinite(stamp) or (last is not None and stamp < last):
                raise ValueError('recording timestamps must be finite and ordered')
            if first is None:
                first = stamp
            last = stamp
    if first is None:
        raise ValueError('no recorded states to replay')
    total = max(0, math.ceil((last-1e-9-first)*fps))+1
    return min(total, max_frames) if max_frames is not None else total


def replay(log_dir, output, fps=20, width=960, height=720, max_frames=None, *, progress_label='完整视频'):
    """Replay state samples at their original timestamps, including reasoning waits.

    This output is private: the follow camera is never an API camera role.
    Zero-order hold between 20 Hz recorded states; no claim of 1 kHz visual recording.
    """
    os.environ.setdefault('MUJOCO_GL', 'egl')
    os.environ.setdefault('LP_NUM_THREADS', '2')
    import mujoco
    from .model import OUTPUT, restore
    import hashlib
    log_dir = Path(log_dir)
    meta = json.loads((log_dir/'manifest.json').read_text())
    if hashlib.sha256(OUTPUT.read_bytes()).hexdigest() != meta['model_sha256']:
        raise RuntimeError('model differs from recorded model')
    print(f'{progress_label}：读取轨迹，统计帧数…', file=sys.stderr, flush=True)
    total = replay_frame_count(log_dir/'states.jsonl.gz', fps, max_frames)
    m = mujoco.MjModel.from_xml_path(str(OUTPUT))
    d = mujoco.MjData(m)
    m.vis.quality.shadowsize = 2048
    m.vis.quality.offsamples = 2
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
               '-s', f'{width}x{height}', '-r', str(fps), '-i', '-', '-an', '-c:v', 'libx264',
               '-pix_fmt', 'yuv420p', '-crf', '20', str(output)]
    count = 0
    with ExportProgress(progress_label, total) as progress, \
         gzip.open(log_dir/'states.jsonl.gz', 'rt') as stream, \
         output.with_suffix('.frames.jsonl').open('w') as index, \
         mujoco.Renderer(m, height=height, width=width) as renderer:
        process = subprocess.Popen(command, stdin=subprocess.PIPE)
        previous_rgba = None
        def write_frame(row, sim_time):
            nonlocal previous_rgba
            restore(m, d, row)
            renderer.update_scene(d, camera=follow_camera(m, d))
            process.stdin.write(renderer.render().tobytes())
            changed = previous_rgba is not None and not np.array_equal(previous_rgba, m.geom_rgba)
            previous_rgba = m.geom_rgba.copy()
            index.write(json.dumps({'frame': count, 'sim_time': sim_time,
                'sample_monotonic': row['sample_monotonic']+(sim_time-row['sim_time']),
                'moving': bool(row.get('motion_command_active')) or bool(np.max(np.abs(d.qvel)) > 1e-4),
                'visual_change': changed})+'\n')
        try:
            rows = (json.loads(line) for line in stream)
            current = next(rows)
            next_time = current['sim_time']
            initial_time = next_time
            for upcoming in rows:
                while next_time < upcoming['sim_time']-1e-9:
                    write_frame(current, next_time)
                    count += 1
                    progress.update(count)
                    next_time = initial_time+count/fps
                    if max_frames and count >= max_frames:
                        break
                if max_frames and count >= max_frames:
                    break
                current = upcoming
            # Include the final recorded state for a non-preview export.
            if not max_frames or count < max_frames:
                write_frame(current, next_time)
                count += 1
                progress.update(count)
            progress.finalizing()
            process.stdin.close()
            returncode = process.wait()
            if returncode:
                raise RuntimeError(f'video encoding failed (exit {returncode})')
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
            raise
        finally:
            if not process.stdin.closed:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
        if count != total:
            raise RuntimeError(f'replay frame count mismatch: {count}/{total}')
        report = {'frames': count, 'fps': fps, 'duration_s': count/fps,
                  'camera': 'private robot-follow third-person', 'preview': bool(max_frames), 'version': 'full',
                  'state_sampling_hz': meta['state_hz'], 'frame_selection': 'timestamped zero-order hold'}
        output.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def replay_pair(log_dir, output, *, timing_path=None, **kwargs):
    from .video_timeline import compact_video
    output = Path(output)
    timing_path = Path(timing_path) if timing_path else Path(log_dir).parent/'agent-timing.jsonl'
    if not timing_path.is_file():
        raise RuntimeError('two-version export requires native agent timing; use full replay for older recordings')
    full = replay(log_dir, output, progress_label='[1/2] 完整视频', **kwargs)
    compact_path = output.with_name(output.stem+'-compact'+output.suffix)
    compact = compact_video(output, compact_path, timing_path, progress_label='[2/2] 精简视频')
    return {'full': full, 'compact': compact, 'full_path': str(output), 'compact_path': str(compact_path)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('log_dir')
    parser.add_argument('output')
    parser.add_argument('--fps', type=int, default=20)
    parser.add_argument('--width', type=int, default=960)
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--max-frames', type=int)
    parser.add_argument('--both', action='store_true', help='export full and compact versions using native timing')
    parser.add_argument('--timing-path', help='native agent-timing.jsonl; defaults to the parent of log_dir')
    args = vars(parser.parse_args())
    both = args.pop('both')
    if not both: args.pop('timing_path')
    print(json.dumps((replay_pair if both else replay)(**args), indent=2))
