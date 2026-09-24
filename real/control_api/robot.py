"""Low-level transport only. No motion strategy, kinematics or scene information."""
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import socket
import time
import uuid


def call(op, *, request_id=None, **fields):
    if os.environ.get('ROBOT_OFFLINE'):
        raise RuntimeError('attempt is offline; evidence and skill closeout remain available')
    request = dict(op=op, id=request_id or uuid.uuid4().hex, **fields)
    raw = (json.dumps(request, allow_nan=False)+'\n').encode()
    if len(raw) > 16384:
        raise ValueError('request too large')
    if os.environ.get('ROBOT_MAILBOX'):
        mailbox = Path(os.environ['ROBOT_MAILBOX'])
        transfer = uuid.uuid4().hex
        pending = mailbox/(transfer+'.pending')
        reply = mailbox/(transfer+'.response')
        pending.write_bytes(raw)
        pending.replace(mailbox/(transfer+'.request'))
        deadline = time.monotonic()+25
        while not reply.exists():
            if time.monotonic() > deadline:
                raise RuntimeError('robot transport timeout; inspect fresh state before another motion')
            time.sleep(.01)
        response = json.loads(reply.read_bytes())
        reply.unlink()
        if not response['ok']:
            raise RuntimeError(response['error'])
        return response['result']
    # The isolated launcher supplies an already-connected descriptor. Subjects
    # cannot open other sockets. A lock serializes CLI calls sharing the stream.
    with open('.robot-transport.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if 'ROBOT_FD' in os.environ:
            connection = socket.socket(fileno=os.dup(int(os.environ['ROBOT_FD'])))
        else:
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.connect(os.environ['ROBOT_SOCKET'])
        with connection:
            connection.settimeout(20)
            connection.sendall(raw)
            # Do not use buffered read-ahead on the shared connection.
            chunks = bytearray()
            while True:
                byte = connection.recv(65536)
                if not byte:
                    raise RuntimeError('environment disconnected')
                chunks.extend(byte)
                if chunks.endswith(b'\n'):
                    break
                if len(chunks) > 8*1024*1024:
                    raise RuntimeError('response too large')
            response = json.loads(chunks)
    if not response['ok']:
        raise RuntimeError(response['error'])
    return response['result']


def observe(directory='evidence', *, request_id=None):
    result = call('observe', request_id=request_id)
    if set(result['images']) != {'head', 'left_wrist', 'right_wrist'}:
        raise RuntimeError('unexpected camera roles')
    out = Path(directory)/uuid.uuid4().hex
    out.mkdir(parents=True, exist_ok=False)
    paths = {}
    for camera, encoded in result.pop('images').items():
        path = out/(camera+'.jpg')
        path.write_bytes(base64.b64decode(encoded, validate=True))
        paths[camera] = str(path)
    result['files'] = paths
    (out/'observation.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('op', choices=['schema', 'state', 'observe', 'move', 'base', 'stop', 'finish'])
    parser.add_argument('--json', default='{}', help='operation fields as JSON')
    parser.add_argument('--request-id')
    args = parser.parse_args()
    fields = json.loads(args.json)
    result = observe(**fields, request_id=args.request_id) if args.op == 'observe' else call(args.op, request_id=args.request_id, **fields)
    print(json.dumps(result, indent=2))
