#!/usr/bin/env python3
"""Operator maintenance: one-time RAM profile preparation, snapshot or release.
No automatic parameter restoration, no EEPROM writes, no temperature reads.
"""
import argparse,json,time
from pathlib import Path
from machine import paths
from transport import ROOT,BACKUP,Transport
from profiles import joint_profile,base_raw_acceleration
HERE=Path(__file__).resolve().parent

def main():
    ap=argparse.ArgumentParser();ap.add_argument('operation',choices=['snapshot','prepare','release']);args=ap.parse_args()
    out=HERE/'maintenance'/time.strftime('%Y%m%d-%H%M%S');out.mkdir(parents=True)
    def audit(e):
        with (out/'writes.jsonl').open('a') as f:f.write(json.dumps(dict(e,unix=time.time()))+'\n');f.flush()
    selected=paths();h=Transport(selected['backup'],audit);c=json.loads(selected['calibration'].read_text());arms=[j['motor'] for j in c['joints'].values()];wheels=[w['motor'] for w in c['wheels'].values()]
    try:
        live=h.connect();h.modes_valid(arms,wheels)
        before={k:h.read(k,40,16) for k in h.motors};(out/'before.json').write_text(json.dumps(dict(ram_40_55=before,live=live),indent=2))
        if args.operation=='prepare':
            if any(v['torque'] for v in live.values()):raise RuntimeError('Prepare only while all motors are released')
            h.sync(41,1,{**{j['motor']:joint_profile(n)['raw_acceleration'] for n,j in c['joints'].items()},**{k:base_raw_acceleration(c) for k in wheels}},True)
            h.sync(44,2,{k:0 for k in arms},True)
            h.sync(46,2,{j['motor']:joint_profile(n)['raw_velocity'] for n,j in c['joints'].items()},True)
            h.sync(46,2,{k:0 for k in wheels},True)
            # STS3250 velocity writes auto-enable, even when the requested speed is zero.
            h.sync(40,1,{k:live[k]['torque'] for k in wheels},True)
        elif args.operation=='release':
            h.sync(46,2,{k:0 for k in wheels},True)
            errors={}
            for k in arms+wheels:
                try:h.sync(40,1,{k:0},True)
                except Exception as e:errors[k]=str(e)
            if errors:raise RuntimeError(str(errors))
        after={k:h.read(k,40,16) for k in h.motors};h.check_configs()
        for k,m in h.motors.items():
            if h.read(k,80,7)!=m['original'][80:87]:raise RuntimeError('Extended config changed')
        if args.operation=='prepare':
            for k in before:
                assert before[k][0]==after[k][0] # torque unchanged
                assert before[k][2:4]==after[k][2:4] # position targets unchanged
        (out/'after.json').write_text(json.dumps(dict(ram_40_55=after,live=h.sample(),persistent_registers_unchanged=True),indent=2))
        print(json.dumps(dict(ok=True,operation=args.operation,evidence=str(out),automatic_restore=False)))
    finally:h.close()
if __name__=='__main__':main()
