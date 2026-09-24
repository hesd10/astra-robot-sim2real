"""Developer integration checks. No images are opened or sent to a model."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
import urllib.request
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def rpc(path, op, **kwargs):
    started = time.monotonic()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(20)
        s.connect(str(path))
        s.sendall((json.dumps(dict(op=op, id=kwargs.pop('id', uuid.uuid4().hex), **kwargs))+'\n').encode())
        with s.makefile('rb') as f:
            result = json.loads(f.readline())
    return result, time.monotonic()-started


def check(seconds=30, render=True):
    run = ROOT/'reports'/'runtime'/('integration-'+uuid.uuid4().hex[:8])
    run.mkdir(parents=True)
    sock = Path('/tmp')/('astra-'+uuid.uuid4().hex[:12]+'.sock')
    command = [sys.executable, '-m', 'sim_env.service', '--socket-path', str(sock),
               '--log-dir', str(run/'private'), '--wall-seconds', str(seconds)]
    if not render:
        command.append('--no-render')
    with (run/'service.log').open('w') as log:
        p = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log)
        results = []
        try:
            deadline = time.monotonic()+90
            while not sock.exists():
                if p.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('service startup failed; inspect service.log')
                time.sleep(.1)
            start = time.monotonic()
            monitor = json.loads((run/'private'/'monitor.json').read_text())
            roles = {'third_person', 'head', 'left_wrist', 'right_wrist'}
            assert set(monitor['views']) == roles, monitor
            client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            live_samples = []
            last_monitor_check = 0.
            state, _ = rpc(sock, 'state')
            assert state['ok'] and not state['result']['fault'], state
            initial = state['result']['sim_time']
            schema, _ = rpc(sock, 'schema')
            assert schema['result']['cameras'] == ['head', 'left_wrist', 'right_wrist']
            assert len(schema['result']['joints']) == 14
            for op, fields in [('reset', {}), ('observe', {'camera': 'third_person'}),
                               ('base', {'vx': .2, 'duration': 1}), ('move', {'targets': {'qpos': 1}, 'duration': 1})]:
                rejected, _ = rpc(sock, op, **fields)
                assert not rejected['ok'], (op, rejected)
            ident = uuid.uuid4().hex
            a, _ = rpc(sock, 'base', id=ident, vx=.04, duration=.4)
            b, _ = rpc(sock, 'base', id=ident, vx=.04, duration=.4)
            assert a == b and a['ok'], (a, b)
            changed, _ = rpc(sock, 'base', id=ident, vx=.02, duration=.4)
            assert not changed['ok']
            time.sleep(1)
            stopped, _ = rpc(sock, 'state')
            assert max(abs(v) for v in stopped['result']['base_command']) < 1e-6
            pose = stopped['result']['joints']['head_2']['target']
            moved, _ = rpc(sock, 'move', targets={'head_2': pose+.01}, duration=1.)
            assert moved['ok'], moved
            while time.monotonic()-start < seconds-3:
                if time.monotonic()-last_monitor_check >= 1.:
                    with client.open(monitor['url']+'status', timeout=2) as response:
                        sample = json.load(response)
                    assert sample['age_seconds'] < 1. and sample['error'] is None, sample
                    assert set(sample['views']) == roles
                    assert all(v['sim_time'] == sample['sim_time'] for v in sample['views'].values())
                    if live_samples:
                        assert sample['frames'] > live_samples[-1]['frames'], sample
                    live_samples.append(sample)
                    digests = set()
                    for role in sorted(roles):
                        url = monitor['url']+f'frame/{role}.jpg?n='+str(sample['frames'])
                        with client.open(url, timeout=2) as response:
                            jpeg = response.read()
                        with Image.open(io.BytesIO(jpeg)) as frame:
                            assert frame.size == (sample['views'][role]['width'], sample['views'][role]['height'])
                        digests.add(hashlib.sha256(jpeg).hexdigest())
                        (run/f'live-{role}.jpg').write_bytes(jpeg)
                    assert len(digests) == 4, 'monitor views are not distinct'
                    if len(live_samples) == 1:
                        # A numbered batch remains stable across a new publication.
                        time.sleep(.12)
                        with client.open(url, timeout=2) as response:
                            assert response.read() == jpeg
                    last_monitor_check = time.monotonic()
                if render:
                    before, _ = rpc(sock, 'state')
                    observed, latency = rpc(sock, 'observe')
                    assert observed['ok'], observed
                    row = observed['result']
                    assert set(row['images']) == {'head', 'left_wrist', 'right_wrist'}
                    assert row['sample_monotonic'] >= row['request_monotonic']
                    after, _ = rpc(sock, 'state')
                    progress = after['result']['sim_time']-before['result']['sim_time']
                    assert progress >= .5*latency, (progress, latency)
                    results.append({'latency': latency, 'age': row['age_seconds'],
                        'physics_progress': progress, 'sim_time': row['sim_time'],
                        'encoded_bytes': {k: len(v) for k,v in row['images'].items()},
                        'snapshot_after_request': True})
                    if len(results)%30==1:
                        print(json.dumps(results[-1]), flush=True)
                else:
                    time.sleep(.5)
            state, _ = rpc(sock, 'state')
            assert state['result']['sim_time'] > initial+seconds-5
            assert not state['result']['fault'], state
            p.wait(timeout=15)
            assert p.returncode == 0
            result = json.loads((run/'private'/'result.json').read_text())
            assert not result['fault'] and result['recording_error'] is None, result
            with gzip.open(run/'private'/'states.jsonl.gz', 'rt') as f:
                times = [json.loads(line)['sim_time'] for line in f]
            assert max(b-a for a,b in zip(times,times[1:])) < .051
            monitor_result = json.loads((run/'private'/'monitor-result.json').read_text())
            assert monitor_result['error'] is None and monitor_result['frames'] > (seconds-3)*8, monitor_result
            assert not result['operator_monitor']['error'], result
            summary = {'passed': True, 'observations': results, 'runtime': result,
                       'live_monitor': monitor_result, 'live_samples': live_samples}
            (run/'checks.json').write_text(json.dumps(summary, indent=2)+'\n')
            print('PASS', run, flush=True)
            return run
        finally:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=15)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--no-render', action='store_true')
    args = parser.parse_args()
    check(args.seconds, not args.no_render)
