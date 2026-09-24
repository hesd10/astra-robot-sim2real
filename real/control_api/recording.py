"""Operator-only three-camera recording; disk/encoding never block motor ticks."""
import base64,json,threading,time
from pathlib import Path

class Recorder:
    roles=('head','left_wrist','right_wrist')
    def __init__(self,cameras,folder,fps=10):
        self.cameras=cameras;self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=False)
        self.fps=fps;self.frames={r:0 for r in self.roles};self.error=None;self.done=threading.Event();self.started=time.time();self.ended=None
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def status(self):
        return dict(active=self.thread.is_alive() and not self.done.is_set(),frames=dict(self.frames),error=self.error,started_unix=self.started,ended_unix=self.ended,fps=self.fps,folder=str(self.folder),timestamp_file='frames.jsonl',note='Independent cameras. Frame index timestamps are authoritative; AVI playback uses nominal fixed frame rate.')
    def run(self):
        writers={};last={};next_frame=time.monotonic()
        try:
            import cv2,numpy as np
            with (self.folder/'frames.jsonl').open('w') as metadata:
                while not self.done.is_set():
                    with self.cameras.cv:frames=dict(self.cameras.frames);errors=dict(self.cameras.errors)
                    if errors:raise RuntimeError(str(errors))
                    for role in self.roles:
                        value=frames.get(role)
                        if value is None or value[0]==last.get(role):continue
                        if time.monotonic()-value[0]>2:raise RuntimeError('Stale camera: '+role)
                        jpg=base64.b64decode(value[2]);frame=cv2.imdecode(np.frombuffer(jpg,dtype=np.uint8),cv2.IMREAD_COLOR)
                        if frame is None:raise RuntimeError('Invalid frame: '+role)
                        if role not in writers:
                            h,w=frame.shape[:2];writer=cv2.VideoWriter(str(self.folder/(role+'.avi')),cv2.VideoWriter_fourcc(*'MJPG'),self.fps,(w,h))
                            if not writer.isOpened():raise RuntimeError('Cannot create recording: '+role)
                            writers[role]=writer
                        writers[role].write(frame)
                        metadata.write(json.dumps(dict(role=role,frame_index=self.frames[role],capture_monotonic=value[0],capture_unix=time.time()-(time.monotonic()-value[0]),written_unix=time.time()))+'\n')
                        self.frames[role]+=1;last[role]=value[0]
                    metadata.flush();next_frame+=1/self.fps
                    if next_frame<time.monotonic()-1/self.fps:next_frame=time.monotonic()
                    self.done.wait(max(0,next_frame-time.monotonic()))
        except Exception as e:self.error=str(e)
        finally:
            self.done.set()
            for writer in writers.values():writer.release()
            self.ended=time.time()
            (self.folder/'recording.json').write_text(json.dumps(self.status(),indent=2))
    def close(self):
        self.done.set();self.thread.join(timeout=5)
        if self.thread.is_alive():self.error='Recording finalization timed out'
        return self.status()
