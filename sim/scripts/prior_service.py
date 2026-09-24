"""Unchanged legacy service plus a private initial-condition verification."""
import argparse
import json
from pathlib import Path
import signal
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from sim_env.service import Service
from prior_materials import initial_target, write_json, digest


def verify_initial(core, reference):
    expected = json.loads(Path(reference).read_text())
    actual = initial_target(core.m, core.d)
    for key in ('button_face_center_m', 'button_outward_unit_normal'):
        np.testing.assert_allclose(actual[key], expected['public_measurement'][key], rtol=0, atol=1e-10)
    np.testing.assert_allclose(core.d.qpos, expected['qpos'], rtol=0, atol=1e-10)
    np.testing.assert_allclose(core.d.qvel, expected['qvel'], rtol=0, atol=1e-10)
    np.testing.assert_allclose(core.d.ctrl, expected['ctrl'], rtol=0, atol=1e-10)
    assert core.d.time == 0
    return {'passed': True, 'reference_sha256': digest(reference),
            'initial_measurement': actual, 'all_initial_joint_and_base_states_match': True,
            'private_only': True, 'no_online_localization_exposed': True}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--socket-path', required=True)
    p.add_argument('--log-dir', required=True)
    p.add_argument('--reference', required=True)
    p.add_argument('--max-seconds', type=float, default=1800.)
    p.add_argument('--standoff', type=float, default=.9)
    p.add_argument('--lateral', type=float, default=0.)
    p.add_argument('--yaw', type=float, default=0.)
    p.add_argument('--monitor-fps', type=int, default=10)
    p.add_argument('--monitor-port', type=int, default=0)
    p.add_argument('--workflow-file')
    a = vars(p.parse_args())
    reference = a.pop('reference')
    service = Service(**a)
    try:
        write_json(Path(a['log_dir'])/'initial-prior-audit.json', verify_initial(service.core, reference))
    except BaseException:
        service.journal.close()
        raise
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: service.stop_event.set())
    service.run()


if __name__ == '__main__':
    main()
