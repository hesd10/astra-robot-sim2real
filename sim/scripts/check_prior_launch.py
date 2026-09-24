"""Real simulation/render/video integration fixture; no model request or motion."""
import base64
import json
from pathlib import Path
import socket
import sys
import time
import uuid
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prior_materials import write_json
from run_prior_comparison import STUDY, validate
import start_prior_experiment as launcher


def fixture(workspace, socket_path, private_dir, **kwargs):
    start = time.monotonic()
    def rpc(op, **fields):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
            channel.settimeout(20)
            channel.connect(str(socket_path))
            channel.sendall((json.dumps({'id': uuid.uuid4().hex, 'op': op, **fields})+'\n').encode())
            with channel.makefile('rb') as reader:
                result = json.loads(reader.readline())
            assert result['ok'], result
            return result['result']
    schema, state, observation = rpc('schema'), rpc('state'), rpc('observe')
    assert len(schema['joints']) == len(state['joints']) == 14
    assert set(observation['images']) == {'head', 'left_wrist', 'right_wrist'}
    assert observation['sample_monotonic'] >= observation['request_monotonic']
    evidence = workspace/'evidence'
    evidence.mkdir()
    for role, encoded in observation['images'].items():
        (evidence/(role+'.jpg')).write_bytes(base64.b64decode(encoded))
    rpc('stop')
    rpc('finish', outcome='failure')
    end = time.monotonic()
    (private_dir/'agent-timing.jsonl').write_text('\n'.join(json.dumps(x) for x in [
        {'event':'turn/started','monotonic':start},
        {'event':'item/started','monotonic':start,'item_id':'fixture','item_type':'commandExecution'},
        {'event':'item/completed','monotonic':end,'item_id':'fixture','item_type':'commandExecution'},
        {'event':'turn/completed','monotonic':end}])+'\n')
    write_json(private_dir/'fixture.json', {'real_model_called': False, 'motion_commands': 0,
        'schema_and_telemetry_ok': True, 'fresh_camera_set': True, 'finish_ok': True})
    return {'status':'completed'}


if __name__ == '__main__':
    validate()
    launcher.run_agent = fixture
    name = 'verification-priors-'+uuid.uuid4().hex[:8]
    run = launcher.start(name, input_dir=STUDY/'inputs/D',
        reference=STUDY/'private-initial-reference.json', setup=ROOT/'setups/formal-001.json', max_seconds=60.)
    private = run/'private'
    result = json.loads((private/'simulation/result.json').read_text())
    assert result['fault'] is None and not result['physical_success'], result
    assert result['actions'] == 0
    for video in ('dashboard.mp4', 'follow.mp4', 'follow-compact.mp4'):
        assert (private/video).stat().st_size > 0
    write_json(private/'checks.json', {'passed':True,'real_model_called':False,
        'initial_reference_verified':True,'camera_set_verified':True,'all_three_videos_saved':True})
    print('PASS:', private/'checks.json')
