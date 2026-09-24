"""Cut stationary native-model waits while retaining all physical activity."""
import json
from pathlib import Path
import shutil
import subprocess
import numpy as np
from .progress import ExportProgress


def model_waits(timing_path):
    """Native turn time outside tool execution, including generation/network waits.

    This is an observable waiting-time definition, not a measurement of private
    model reasoning. Timestamps use the same host monotonic clock as snapshots.
    """
    rows = [json.loads(line) for line in Path(timing_path).read_text().splitlines()]
    intervals, tools = [], set()
    active = False
    begin = None
    for row in rows:
        event, stamp = row['event'], row['monotonic']
        kind, ident = row.get('item_type'), row.get('item_id')
        is_tool = kind is not None and kind not in ('userMessage', 'agentMessage', 'reasoning', 'contextCompaction')
        if event in ('turn/requested', 'turn/started') and not active:
            active = True; begin = stamp; tools.clear()
        elif event == 'item/started' and is_tool and active:
            if begin is not None:
                intervals.append((begin, stamp)); begin = None
            tools.add(ident)
        elif event == 'item/completed' and is_tool and active:
            tools.discard(ident)
            if not tools and begin is None: begin = stamp
        elif event in ('turn/completed', 'session/ended'):
            if begin is not None: intervals.append((begin, stamp))
            active = False; begin = None; tools.clear()
    return [(a, b) for a, b in intervals if b > a]


def runs(mask):
    start = None
    for index, value in enumerate(list(mask)+[False]):
        if value and start is None: start = index
        elif not value and start is not None:
            yield start, index  # Exclusive end.
            start = None


def cut_plan(frames, waits, fps, padding_seconds=.35, minimum_cut_seconds=1.):
    keep = np.ones(len(frames), dtype=bool)
    interval = 0
    for index, frame in enumerate(frames):
        stamp = frame['sample_monotonic']
        while interval < len(waits) and waits[interval][1] <= stamp: interval += 1
        waiting = interval < len(waits) and waits[interval][0] <= stamp < waits[interval][1]
        if waiting and not frame['moving'] and not frame['visual_change']:
            keep[index] = False
    # Keep a readable opening/ending and a buffer around actions/visual changes.
    bookend = min(len(frames), max(1, round(fps)))
    keep[:bookend] = True; keep[-bookend:] = True
    padding = round(padding_seconds*fps)
    if padding:
        original = keep.copy()
        for start, end in runs(original):
            keep[max(0, start-padding):min(len(keep), end+padding)] = True
    for start, end in list(runs(~keep)):
        if (end-start)/fps < minimum_cut_seconds: keep[start:end] = True
    return keep


def compact_video(full_video, output, timing_path, *, progress_label='精简视频'):
    full_video, output = Path(full_video), Path(output)
    if full_video.resolve() == output.resolve(): raise ValueError('compact output must differ from full video')
    meta = json.loads(full_video.with_suffix('.json').read_text())
    frames = [json.loads(line) for line in full_video.with_suffix('.frames.jsonl').read_text().splitlines()]
    if not frames: raise ValueError('no frames to edit')
    if len(frames) != meta['frames']: raise ValueError('frame index does not match video')
    fps = meta['fps']
    waits = model_waits(timing_path)
    keep = cut_plan(frames, waits, fps)
    segments = list(runs(keep))
    output.parent.mkdir(parents=True, exist_ok=True)
    total = int(keep.sum())
    with ExportProgress(progress_label, total) as progress:
        if keep.all():
            shutil.copyfile(full_video, output)
            progress.update(total)
            progress.finalizing()
        else:
            selection = '+'.join(f'between(n\\,{start}\\,{end-1})' for start, end in segments)
            script = output.with_suffix('.filter.txt')
            script.write_text(f'select={selection},setpts=N/({fps}*TB)\n')
            command = ['ffmpeg', '-v', 'error', '-y', '-nostats', '-progress', 'pipe:1',
                '-i', str(full_video), '-filter_script:v', str(script), '-an', '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p', '-crf', '20', '-r', str(fps), str(output)]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
            try:
                for line in process.stdout:
                    key, _, value = line.strip().partition('=')
                    if key == 'frame':
                        progress.update(int(value))
                progress.finalizing()
                if process.wait():
                    raise subprocess.CalledProcessError(process.returncode, command)
                if progress.current != total:
                    raise RuntimeError(f'compact frame count mismatch: {progress.current}/{total}')
            except BaseException:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait()
                raise
            finally:
                process.stdout.close()
        timeline = []
        output_frame = 0
        for start, end in segments:
            timeline.append({'output_start_s': output_frame/fps, 'output_end_s': (output_frame+end-start)/fps,
                             'source_start_frame': start, 'source_end_frame_exclusive': end,
                             'source_sim_start_s': frames[start]['sim_time'],
                             'source_sim_end_s': frames[end-1]['sim_time']+1./fps})
            output_frame += end-start
        result = {'version': 'compact', 'frames': total, 'fps': fps,
                  'duration_s': total/fps, 'source_duration_s': meta['duration_s'],
                  'removed_wait_seconds': float((~keep).sum())/fps,
                  'policy': 'remove stationary native-model waits; retain motion, commands, visual changes and .35s buffers',
                  'waiting_definition': 'native turn outside tool execution; includes generation and network waits',
                  'velocity_threshold': 1e-4, 'minimum_cut_seconds': 1., 'bookend_seconds': 1.,
                  'timing_source': str(Path(timing_path).resolve()), 'source_video': str(full_video.resolve()),
                  'segments': timeline,
                  'cuts': [{'source_start_frame': a, 'source_end_frame_exclusive': b,
                            'source_sim_start_s': frames[a]['sim_time'],
                            'source_sim_end_s': frames[b-1]['sim_time']+1./fps}
                           for a, b in runs(~keep)]}
        output.with_suffix('.json').write_text(json.dumps(result, indent=2)+'\n')
    return result
