"""Two tiny protocol checks; no images, experiment prompt or robot tools."""
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sim_env.provider_probe import configured_provider,response


def main():
    p=configured_provider()
    tools=[{'type':'function','name':'ping','description':'Protocol connectivity check only.',
            'parameters':{'type':'object','properties':{'text':{'type':'string'}},'required':['text'],'additionalProperties':False}}]
    items=[{'role':'user','content':'Call ping with text READY. After its result, reply READY. This is a protocol check; do nothing else.'}]
    start=time.monotonic()
    a=response(p,{'model':p['model'],'input':items,'tools':tools,'tool_choice':{'type':'function','name':'ping'},
                  'parallel_tool_calls':False,'store':False,'include':['reasoning.encrypted_content']})
    calls=[o for o in a.get('output',[]) if o.get('type')=='function_call']
    assert len(calls)==1 and calls[0]['name']=='ping', 'function-call protocol unavailable'
    assert json.loads(calls[0]['arguments'])['text']=='READY'
    items+=a['output']+[{'type':'function_call_output','call_id':calls[0]['call_id'],'output':'READY'}]
    b=response(p,{'model':p['model'],'input':items,'tools':tools,'tool_choice':'none','store':False})
    text=' '.join(c.get('text','') for o in b.get('output',[]) if o.get('type')=='message' for c in o.get('content',[]))
    assert 'READY' in text, 'tool-output continuation failed'
    report={'passed':True,'model':p['model'],'requests':2,'robot_access':False,'images_sent':0,
            'wall_seconds':time.monotonic()-start,'usage':[a.get('usage'),b.get('usage')]}
    (ROOT/'reports/runtime/provider.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
