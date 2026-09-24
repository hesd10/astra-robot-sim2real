"""Fresh USB frames; separate capture threads, never hold the motor-owner lock."""
import threading,time,base64
class Cameras:
    def __init__(self,config):self.config=config;self.cv=threading.Condition();self.frames={};self.errors={};self.running=True;self.threads=[]
    def start(self):
        if not self.config.get('roles_confirmed'):return
        for role,path in self.config['devices'].items():
            t=threading.Thread(target=self.worker,args=(role,path),daemon=True);t.start();self.threads.append(t)
    def worker(self,role,path):
        import cv2
        cap=cv2.VideoCapture(path,cv2.CAP_V4L2)
        try:
            cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*'MJPG'));cap.set(cv2.CAP_PROP_FRAME_WIDTH,640);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480);cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
            if not cap.isOpened():raise RuntimeError('Cannot open camera '+role)
            while self.running:
                # Use acquisition START, not encode completion, for freshness barrier.
                start=time.monotonic();ok,frame=cap.read();end=time.monotonic()
                if not ok:raise RuntimeError('Camera frame read failed '+role)
                ok,jpg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,85])
                if not ok:raise RuntimeError('JPEG encoding failed')
                with self.cv:self.frames[role]=(start,end,base64.b64encode(jpg).decode(),frame.shape[:2]);self.cv.notify_all()
        except Exception as e:
            with self.cv:self.errors[role]=str(e);self.cv.notify_all()
        finally:cap.release()
    def observe(self):
        if not self.config.get('roles_confirmed'):raise RuntimeError('Operator camera-role mapping not confirmed')
        begin=time.monotonic();deadline=begin+8
        with self.cv:
            while not all(r in self.frames and self.frames[r][0]>begin for r in ['head','left_wrist','right_wrist']):
                if self.errors:raise RuntimeError(str(self.errors))
                remaining=deadline-time.monotonic()
                if remaining<=0:raise RuntimeError('Fresh camera capture timeout')
                self.cv.wait(remaining)
            frames=dict(self.frames)
        return dict(images={r:v[2] for r,v in frames.items()},capture_monotonic={r:v[0] for r,v in frames.items()},read_completed_monotonic={r:v[1] for r,v in frames.items()},image_sizes={r:[v[3][1],v[3][0]] for r,v in frames.items()},capture_skew_seconds=max(v[0] for v in frames.values())-min(v[0] for v in frames.values()),latency_seconds=time.monotonic()-begin,synchronized=False,encoding='jpeg/base64',note='Fresh frames from independent USB cameras; no hardware synchronization; host acquisition times, not exposure timestamps.')
    def preview(self,role):
        if role not in ('head','left_wrist','right_wrist'):raise ValueError('Unknown camera role')
        with self.cv:
            if role in self.errors:raise RuntimeError(self.errors[role])
            frame=self.frames.get(role)
            if frame is None:raise RuntimeError('Camera warming up')
            age=time.monotonic()-frame[0]
            if age>2:raise RuntimeError('Camera frame stale')
            return dict(image=frame[2],age_seconds=age,captured_unix=time.time()-age)
    def close(self):
        self.running=False
        for thread in self.threads:thread.join(timeout=2)

