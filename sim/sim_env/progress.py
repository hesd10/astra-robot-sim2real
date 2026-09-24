"""Throttled terminal export progress; stdout remains available for JSON reports."""
import sys
import time
import shutil
import unicodedata


def duration(seconds):
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}' if hours else f'{minutes:02}:{seconds:02}'


class ExportProgress:
    def __init__(self, label, total, *, stream=None):
        if total <= 0:
            raise ValueError('export must contain frames')
        self.label, self.total = label, total
        self.stream = stream if stream is not None else sys.stderr
        self.interactive = self.stream.isatty()
        self.current = 0
        self.started = time.monotonic()
        self.last_display = -float('inf')
        self.last_width = 0
        self.status = '处理中'

    def __enter__(self):
        self._display(force=True)
        return self

    def update(self, current):
        if not self.current <= current <= self.total:
            raise ValueError(f'invalid export progress: {current}/{self.total}')
        self.current = current
        self._display()

    def finalizing(self):
        self.status = '封装中'
        self._display(force=True)

    def _display(self, *, force=False, final=False):
        now = time.monotonic()
        if not force and now-self.last_display < (.25 if self.interactive else 5.):
            return
        elapsed = now-self.started
        rate = self.current/elapsed if elapsed > 0 else 0.
        # All frames queued is not completion: the encoder and metadata must close.
        complete = self.status == '完成'
        fraction = 1. if complete else min(self.current/self.total, .999)
        filled = int(20*fraction)
        bar = '='*filled + '-'*(20-filled)
        eta = duration((self.total-self.current)/rate) if rate and 5 <= self.current < self.total else '--:--'
        prefix = f'{self.label} [{bar}] {100*fraction:5.1f}% {self.current}/{self.total} 帧'
        details = [f'{rate:.1f} 帧/秒', f'已用 {duration(elapsed)}', f'预计剩余 {eta}']
        line = ' | '.join([prefix, *details, self.status])
        if self.interactive:
            columns = shutil.get_terminal_size(fallback=(120, 24)).columns
            # Avoid wrapped lines accumulating as the carriage-return bar updates.
            while details and sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in line) >= columns:
                details.pop(0)
                line = ' | '.join([prefix, *details, self.status])
        if self.interactive:
            self.stream.write('\r'+line+' '*max(0, self.last_width-len(line))+('\n' if final else ''))
        else:
            self.stream.write(line+'\n')
        self.stream.flush()
        self.last_display, self.last_width = now, len(line)

    def __exit__(self, kind, value, traceback):
        self.status = ('已中断' if kind is KeyboardInterrupt else '失败') if kind else '完成'
        self._display(force=True, final=True)
        return False
