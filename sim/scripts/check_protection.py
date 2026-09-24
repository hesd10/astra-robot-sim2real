"""Private physics fault injection and state-contract checks."""
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sim_env.core import Core
from sim_env.model import snapshot,restore


def main():
    report={}
    c=Core()
    start=c.d.qpos.copy()
    for bad in (float('nan'),float('inf'),True,'1'):
        try:c.dispatch({'op':'base','vx':bad,'duration':.1})
        except ValueError:pass
        else:raise AssertionError('invalid number accepted')
    report['invalid_numbers_rejected']=True
    try:c.dispatch({'op':'move','targets':{'head_2':.5},'duration':.05})
    except ValueError:pass
    else:raise AssertionError('unsafe target trajectory accepted')
    assert np.array_equal(c.d.qpos,start)
    report['rejected_commands_do_not_move']=True
    c.dispatch({'op':'base','vx':.08,'duration':.5},now=0.)
    for i in range(2500):c.step(now=i*.001)
    assert np.linalg.norm(c.base_current)<1e-9 and not c.fault
    report['expired_base_brakes']=True
    state=snapshot(c.m,c.d)
    before=c.d.qpos.copy()
    c.d.qpos[:]=0
    restore(c.m,c.d,state)
    assert np.array_equal(c.d.qpos,before)
    report['replay_state_roundtrip']=True
    c=Core()
    channel=c.channels['right_2']
    c.d.ctrl[channel['a']]=c.d.qpos[channel['q']]-.2
    joint=c.m.joint('Pitch_L')
    joint.range[:]=c.d.qpos[joint.qposadr[0]]+np.array([-.00001,.00001])
    c.m.jnt_solref[joint.id]=[.002,1]
    for i in range(6000):
        c.step(now=i*.001)
        if c.fault:break
    assert c.fault=='joint_overload',c.private_result()
    report['blocked_joint_fault_s']=float(c.d.time)
    risk=c.risk.copy()
    c.d.ctrl[channel['a']]=c.d.qpos[channel['q']]
    for i in range(100):c.step(now=10+i*.001)
    assert c.fault=='joint_overload' and all(c.risk[k]>=v for k,v in risk.items())
    for op in ({'op':'reset'},{'op':'base','vx':.01,'duration':.1}):
        try:c.dispatch(op)
        except ValueError:pass
        else:raise AssertionError('fault bypass accepted')
    report['fault_latches_and_blocks_motion']=True
    # Deterministic external collision: move the initialized base into the wall
    # in this private fixture; this operation is not available in the public API.
    c=Core()
    adr=c.m.joint('base_free').qposadr[0]
    c.d.qpos[adr+1]=4.0
    for i in range(100):
        c.step(now=i*.001)
        if c.fault:break
    assert c.fault=='severe_contact',c.private_result()
    report['severe_collision_trips']=True
    c=Core()
    finished=c.dispatch({'op':'finish','outcome':'success'})
    assert finished['finished'] and not c.private_result()['physical_success']
    report['declared_success_is_not_ground_truth']=True
    out=ROOT/'reports'/'runtime'/'protection.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS',json.dumps(report),flush=True)


if __name__=='__main__':main()
