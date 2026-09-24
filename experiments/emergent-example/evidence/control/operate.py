import sys,json,time,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from robot import call,observe
LOG=Path('evidence/control/events.jsonl')
def log(kind,result,**kw):
    with LOG.open('a') as f:f.write(json.dumps({'wall_time':time.time(),'kind':kind,**kw,'result':result})+'\n')
    display=result if kind!='state' else {k:result[k] for k in ('sim_time','health','fault','finished','motion_active','base_command')}
    print(json.dumps({'kind':kind,**kw,'result':display}),flush=True)
def request(op,**kw):
    r=call(op,**kw);log(op,r,request=kw);return r
def check():
    s=request('state')
    if s.get('fault') or s.get('finished') or s.get('health')!='normal':raise RuntimeError('Unsafe state')
    p=s['joints']['head_1']['position']
    ref=json.loads(Path('evidence/control/initial_reference.json').read_text())
    if not ref['head_1_allowed'][0]<=p<=ref['head_1_allowed'][1]:raise RuntimeError('Pan constraint')
    return s
def obs():
    r=observe(directory='evidence');log('observe',r);return r
if __name__=='__main__':
    spec=json.loads(sys.argv[1])
    spec=[dict((k,v) for k,v in a.items() if k!='repeat') for a in spec for _ in range(a.get('repeat',1))]
    check()
    for a in spec:
        op=a.pop('op')
        if op=='observe':time.sleep(.4);obs();continue
        if op=='pause':time.sleep(a['duration']);continue
        if op=='move':
            ref=json.loads(Path('evidence/control/initial_reference.json').read_text())
            p=a['targets'].get('head_1',ref['head_1_initial'])
            assert ref['head_1_allowed'][0]<=p<=ref['head_1_allowed'][1]
            assert -.76<=a['targets'].get('head_2',0)<=1.45
        r=request(op,**a)
        if r.get('accepted') is False or r.get('error'):raise RuntimeError(r)
        if op in ('move','base'):
            time.sleep(a['duration']+.15)
            check()
