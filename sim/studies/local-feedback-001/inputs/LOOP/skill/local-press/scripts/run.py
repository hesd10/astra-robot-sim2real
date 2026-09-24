import sys,json
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from primitive import Live,step
from feedback import run
if __name__=='__main__':
    params=json.loads(sys.argv[1]);result=run(Live(),**params)
    Path('evidence').mkdir(exist_ok=True)
    with Path('evidence/local-skill-calls.jsonl').open('a') as f:f.write(json.dumps({'parameters':params,'result':result})+'\n')
    print(json.dumps(result))
