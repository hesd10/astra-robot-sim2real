"""Developer-only physical checks; not an Astra trial or held-out evaluation.

Runs the unchanged public skill/client against the real-time simulation service.
Private replay state is used only afterwards for measurement, never skill input.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT/'studies/skill-induction-001'
SKILL = STUDY/'prototype/xlerobot-action-primitives/scripts/motion_skills.py'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--setup', default='setups/formal-001.json')
    ap.add_argument('--mode', choices=['primitives', 'source-composition', 'recovery-check', 'guard-replay'], default='primitives')
    ap.add_argument('--interactive', action='store_true', help='bounded developer image-guided continuation via numbered JSON files')
    args = ap.parse_args()
    run = STUDY/'development'/args.case
    run.mkdir(parents=True, exist_ok=False)
    setup_path = ROOT/args.setup
    cfg = json.loads(setup_path.read_text())['initialization']
    (run/'setup.json').write_text(setup_path.read_text())
    (run/'motion_skills.py').write_bytes(SKILL.read_bytes())
    (run/'plan.json').write_text(json.dumps({'kind':'developer physics check, no Astra',
        'mode':args.mode, 'interactive':args.interactive, 'skill_sha256':hashlib.sha256(SKILL.read_bytes()).hexdigest(),
        'setup_source':str(setup_path), 'measurement':'post-run private states only'},indent=2))
    sock = Path('/tmp')/('skill-dev-'+uuid.uuid4().hex[:12]+'.sock')
    cmd = [sys.executable,'-m','sim_env.service','--socket-path',str(sock),
           '--log-dir',str(run/'simulation'),'--max-seconds','240',
           '--standoff',str(cfg['standoff_m']),'--lateral',str(cfg['lateral_m']),
           '--yaw',str(math.radians(cfg['yaw_deg']))]
    robot = module('dev_public_robot',ROOT/'subject_template/robot.py')
    skills = module('dev_skills',SKILL).MotionSkills(robot,evidence_dir=run/'evidence')
    os.environ['ROBOT_SOCKET'] = str(sock)
    os.chdir(run)
    rows = []
    def invoke(name, **kw):
        result = getattr(skills,name)(**kw)
        rows.append({'skill':name,'parameters':kw,'result':result})
        (run/'calls.json').write_text(json.dumps(rows,indent=2))
        print(json.dumps({'case':args.case,'skill':name,'parameters':kw,
              'ok':result['ok'],'code':result['code'],'error':result.get('error'),
              'elapsed':result['elapsed_seconds']}),flush=True)
        if not result['ok']:
            raise RuntimeError(result)
        return result
    with (run/'service.log').open('w') as log:
        process = subprocess.Popen(cmd,cwd=ROOT,stdout=log,stderr=log)
        execution_error=None
        try:
            deadline = time.monotonic()+90
            while not sock.exists():
                if process.poll() is not None or time.monotonic()>deadline:
                    raise RuntimeError('service startup failed')
                time.sleep(.1)
            print('LIVE '+str(run)+' '+(run/'simulation/monitor.json').read_text(),flush=True)
            robot.observe(directory=str(run/'initial'))
            invoke('deploy_press_pose',stage='prepare')
            invoke('deploy_press_pose',stage='work')
            if args.mode=='recovery-check':
                class LostAck:
                    lost=False
                    def call(self,op,**fields):
                        reply=robot.call(op,**fields)
                        if op=='base' and not self.lost:
                            self.lost=True
                            raise OSError('developer-injected lost acknowledgement after real acceptance')
                        return reply
                    def observe(self,**fields):
                        return robot.observe(**fields)
                skills.client=LostAck()
                r=skills.translate_with_pose(vx=.08,vy=0,seconds=6.)
                rows.append({'skill':'translate_with_pose','parameters':{'vx':.08,'vy':0,'seconds':6.},'result':r})
                (run/'calls.json').write_text(json.dumps(rows,indent=2))
                assert not r['ok'] and r['code']=='interface_error',r
                assert r['recovery']['command_stop_confirmed'] and r['recovery']['arm_rest_confirmed'],r
                assert r['recovery']['physical_base_rest_confirmed'] is None,r
                assert r['observation']['sim_time']>=r['recovery']['state']['sim_time'],r
                # Explicit new developer decision; never an automatic retry by the skill.
                skills.client=robot
                invoke('translate_with_pose',vx=-.04,vy=0,seconds=1.)
                (run/'recovery-check.json').write_text(json.dumps({'passed':True,'injection':'one lost acknowledgement after the real base request was accepted','automatic_motion_retry':False,'explicit_subsequent_call_completed':True},indent=2))
            elif args.mode=='primitives':
                for vx,vy,seconds in [(.08,0,6.),(-.08,0,6.),(0,.08,2.),(0,-.08,2.)]:
                    invoke('translate_with_pose',vx=vx,vy=vy,seconds=seconds)
                for vx,vy,seconds in [(.04,0,.1),(.04,0,.6),(.04,0,1.),(0,-.04,.6)]:
                    invoke('contact_step',vx=vx,vy=vy,seconds=seconds)
            else:
                # Researcher-selected composition of the existing source's base segments.
                # Changed timing and new skill boundaries: not an exact replay.
                robot.call('move',targets={'head_1':3.05,'head_2':.2},duration=3.1)
                time.sleep(3.5)
                for vx,vy,seconds in [(.09,.043,6.),(.09,.043,6.),(.1,0,6.),(.07,.035,6.),(0,-.06,2.)]:
                    invoke('translate_with_pose',vx=vx,vy=vy,seconds=seconds)
                for vx,vy,seconds in [(.04,.006,1.),(.03,-.008,1.),(.05,-.015,.6)]:
                    invoke('contact_step',vx=vx,vy=vy,seconds=seconds)
                if args.mode=='guard-replay':
                    # Replay the preserved developer failure timings, not a new policy.
                    for target_time,vy in [(89.057,-.06),(116.952,.06),(144.523,-.1)]:
                        while robot.call('state')['sim_time'] < target_time:
                            time.sleep(.1)
                        invoke('contact_step',vx=0,vy=vy,seconds=1.)
            if args.interactive:
                (run/'ready-for-review.json').write_text(json.dumps({'last_observation':rows[-1]['result']['observation']}))
                print('READY_FOR_IMAGE_GUIDED_REVIEW',flush=True)
                deadline=time.monotonic()+120
                for index in range(1,11):
                    request=run/f'developer-action-{index:03d}.json'
                    while not request.exists() and time.monotonic()<deadline:
                        time.sleep(.1)
                    if not request.exists():
                        print('Developer review timeout; stopping',flush=True)
                        break
                    action=json.loads(request.read_text())
                    if action['skill']=='finish':break
                    if action['skill'] not in ('contact_step','translate_with_pose'):
                        raise ValueError('Unsupported developer continuation')
                    invoke(action['skill'],**action['parameters'])
            time.sleep(1)
            robot.observe(directory=str(run/'final'))
            # Close as a developer check, never claim success through the client.
            robot.call('finish',outcome='failure')
            process.wait(timeout=25)
        except Exception as error:
            execution_error=str(error)
            # Developer cleanup is distinct from the skill's best-effort stop.
            cleanup={}
            try:
                cleanup['stop_ack']=robot.call('stop')
                time.sleep(1.)
                cleanup['state_after_1s']=robot.call('state')
                cleanup['observation']=robot.observe(directory=str(run/'error-final'))
                robot.call('finish',outcome='failure')
                process.wait(timeout=25)
            except Exception as cleanup_error:
                cleanup['error']=str(cleanup_error)
            (run/'cleanup.json').write_text(json.dumps(cleanup,indent=2))
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=25)
    result = json.loads((run/'simulation/result.json').read_text())
    (run/'summary.json').write_text(json.dumps({'case':args.case,'macro_calls':len(rows),
        'all_macros_completed':all(r['result']['ok'] for r in rows),
        'execution_error':execution_error,'physical_result':result},indent=2))
    print('DONE '+json.dumps(result),flush=True)


if __name__=='__main__':
    main()
