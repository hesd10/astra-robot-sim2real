"""Operator feed contract: streaming, partial writes, privacy, and bounded history."""
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sim_env.workflow import Workflow, public_event, ENTRY_LIMIT


def event(method, stamp=1, **params):
    return public_event({'method': method, 'params': params}, stamp)


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    agent = root/'agent-workflow.jsonl'
    feed = Workflow(root, agent)
    feed.stop.set(); feed.thread.join()
    hidden = event('item/started', item={'id': 'r', 'type': 'reasoning', 'content': ['PRIVATE_REASONING'], 'summary': ['PRIVATE_SUMMARY']})
    assert 'PRIVATE' not in json.dumps(hidden)
    assert event('item/reasoning/textDelta', delta='PRIVATE') is None
    assert event('item/started', item={'id': 'u', 'type': 'userMessage', 'content': ['PROMPT']}) is None
    start = {'event': 'session/started', 'monotonic': 1., 'model': 'synthetic'}
    raw = json.dumps(start)
    agent.write_text(raw[:20]); feed.poll(); assert feed.snapshot()['entries'] == []
    with agent.open('a') as f: f.write(raw[20:]+'\n')
    feed.poll(); assert feed.snapshot()['phase'] == 'starting'
    rows = [event('turn/started', turn={}), hidden,
            event('item/agentMessage/delta', itemId='m', delta='第一段'),
            event('item/agentMessage/delta', itemId='m', delta='第二段')]
    for row in rows: feed.apply_agent(row)
    assert feed.entries['agent:m']['text'] == '第一段第二段'
    assert feed.snapshot()['phase'] == 'assistant'
    feed.apply_agent(event('item/completed', item={'id': 'm', 'type': 'agentMessage', 'text': '第一段第二段'}))
    assert feed.snapshot()['phase'] == 'waiting'
    feed.apply_agent(event('item/started', item={'id': 'cmd', 'type': 'commandExecution', 'command': 'echo fixture', 'status': 'inProgress'}))
    feed.apply_agent(event('item/commandExecution/outputDelta', itemId='cmd', delta='part'))
    assert feed.snapshot()['phase'] == 'tool'
    feed.apply_agent(event('item/completed', item={'id': 'cmd', 'type': 'commandExecution', 'command': 'echo fixture', 'aggregatedOutput': 'partial failed', 'exitCode': 2, 'status': 'completed'}))
    assert feed.entries['agent:cmd']['status'] == '失败'
    assert feed.entries['agent:cmd']['output'] == 'partial failed'
    for ok in (True, False):
        feed.apply_robot({'event': 'request', 'request': {'op': 'base', 'id': str(ok)}, 'accepted': ok, 'reply': {'ok': ok}, 'sim_time': 3., 'monotonic': 4.})
    assert feed.entries['robot:True']['status'] == '已接受'
    assert '不代表运动已完成' in feed.entries['robot:True']['text']
    assert feed.entries['robot:False']['status'] == '已拒绝'
    assert 'entries' not in feed.snapshot(feed.revision)
    for i in range(ENTRY_LIMIT+10):
        feed.apply_robot({'event': 'request', 'request': {'op': 'state', 'id': str(i)}, 'accepted': True, 'monotonic': i+5})
    assert len(feed.snapshot()['entries']) == ENTRY_LIMIT
    feed.apply_agent({'event': 'session/ended', 'monotonic': 300, 'status': 'failed', 'error': 'fixture'})
    assert feed.snapshot()['phase'] == 'error'
    feed.close()
    assert json.loads((root/'workflow-last.json').read_text())['phase'] == 'error'
print('PASS: visible streaming, private-event filtering, partial JSONL, failed commands, acceptance semantics, bounded UI history')
