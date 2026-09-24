"""Filesystem-only transport for native Codex commands in a networkless sandbox.

An open directory descriptor anchors all IO. No symlink is followed, even if the
subject renames the directory or replaces requests/results while it is running.
Only the same bounded JSON robot protocol is forwarded to the private service.
"""
import json
import os
from pathlib import Path
import re
import socket
import stat
import threading


class Mailbox:
    def __init__(self, directory, socket_path):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, exist_ok=False)
        self.fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.socket_path = str(socket_path)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop_event.wait(.01):
            # Bound directory work. The transport is not a filesystem tool.
            for name in os.listdir(self.fd)[:64]:
                if not re.fullmatch(r'[0-9a-f]{32}\.request', name): continue
                request_fd = None
                try:
                    request_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
                    info = os.fstat(request_fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
                        continue
                    raw = os.read(request_fd, 16385)
                    request = json.loads(raw)
                    if not isinstance(request, dict): continue
                    raw = (json.dumps(request, allow_nan=False)+'\n').encode()
                    if len(raw) > 16384: continue
                    try:
                        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
                            channel.settimeout(20)
                            channel.connect(self.socket_path)
                            channel.sendall(raw)
                            with channel.makefile('rb') as stream:
                                body = stream.readline(8*1024*1024)
                        if not body.endswith(b'\n'): raise OSError('incomplete response')
                    except OSError:
                        body = b'{"ok":false,"error":"attempt is offline; evidence and skill closeout remain available"}\n'
                    temp = name+'.tmp'
                    output_fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                        0o600, dir_fd=self.fd)
                    with os.fdopen(output_fd, 'wb') as output: output.write(body)
                    os.replace(temp, name[:-8]+'.response', src_dir_fd=self.fd, dst_dir_fd=self.fd)
                except (OSError, ValueError, TypeError):
                    pass
                finally:
                    if request_fd is not None: os.close(request_fd)
                    try: os.unlink(name, dir_fd=self.fd)
                    except OSError: pass

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=22)
        if not self.thread.is_alive(): os.close(self.fd)
