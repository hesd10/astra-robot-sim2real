"""Read-only historical corpus extraction; never launches a simulator or agent."""
import collections
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'studies/skill-induction-001'

def read(p):
    return json.loads(p.read_text())

def digest(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    selections = []
    for batch, role, expected in [
        ('body-experience-001', 'core', 33),
        ('position-perturbation-001', 'core', 18),
        ('prior-information-001-block-1', 'supplement', 4),
        ('skill-v4-v5-repeat-001', 'supplement', 6),
    ]:
        path = ROOT / 'reports/batches' / batch / 'status.json'
        completed = read(path)['completed']
        assert len(completed) == expected, (batch, len(completed))
        for x in completed:
            selections.append(dict(run=x['run'], cohort=batch, role=role,
                condition=x.get('condition', x.get('group')), phase=x.get('phase'),
                point=x.get('point'), source_index=str(path.relative_to(ROOT))))
    selections += [dict(run=f'run-{i:03}', cohort='legacy-iterations', role='supplement',
                        condition='sequential-skill', source_index='explicit run-001..006 whitelist')
                   for i in range(1, 7)]
    assert len(selections) == len({x['run'] for x in selections}) == 67
    (OUT / 'extracted').mkdir(parents=True, exist_ok=True)
    corpus, extracted, warnings = [], [], []
    for selected in selections:
        run = selected['run']
        exp = ROOT / 'experiments' / run
        sim = exp / 'private/simulation'
        result = read(sim / 'result.json')
        manifest = read(sim / 'manifest.json')
        files = [sim / 'result.json', sim / 'manifest.json', sim / 'events.jsonl']
        files += [exp / 'subject' / n for n in ('PROMPT.md', 'API.md', 'PRIOR.md')
                  if (exp / 'subject' / n).exists()]
        row = {**selected, 'result': result,
            'model_sha256': manifest.get('model_sha256'),
            'runtime_sha256': manifest.get('runtime_sha256'),
            'initialization': manifest.get('initialization'),
            'files': {str(p.relative_to(ROOT)): digest(p) for p in files}}
        events = [json.loads(l) for l in (sim / 'events.jsonl').open()]
        requests, observations, signals, states = [], [], [], []
        targets = {}
        press_targets = None
        pending = None
        segments = []
        def flush():
            nonlocal pending
            if pending:
                segments.append(pending)
                pending = None
        for line, e in enumerate(events, 1):
            kind = e.get('event')
            t = e.get('sim_time')
            if kind == 'observation_delivered':
                flush()
                observations.append({'line': line, 'time': t, 'id': e.get('id')})
            elif kind == 'request':
                q = e['request']; op = q['op']; accepted = e.get('accepted')
                entry = {'line': line, 'time': t, 'request': q, 'accepted': accepted}
                if op in ('move', 'base', 'stop', 'finish'):
                    entry['reply'] = e.get('reply')
                    requests.append(entry)
                if op != 'base' or not accepted:
                    flush()
                if accepted and op == 'state':
                    state = e.get('reply', {}).get('result', {})
                    states.append({'line': line, 'time': t, 'state': state})
                    if not targets:
                        targets.update({k: v.get('target', v.get('position'))
                                        for k, v in state.get('joints', {}).items()})
                if accepted and op == 'move':
                    targets.update(q['targets'])
                if accepted and op == 'base':
                    params = {k: q.get(k, 0) for k in ('vx','vy','wz','duration')}
                    if pending and (pending['params'] != params or
                                    t - pending['last_time'] > pending['params']['duration'] + .5):
                        flush()
                    if pending is None:
                        pending = {'params': params, 'first_time': t, 'last_time': t,
                                   'lines': [], 'count': 0}
                    pending['last_time'] = t
                    pending['lines'].append(line)
                    pending['count'] += 1
            elif kind not in ('request',):
                signals.append({'line': line, **e})
                if kind == 'target_pressed' and press_targets is None:
                    press_targets = dict(targets)
        flush()
        moves = [q for q in requests if q['accepted'] and q['request']['op'] == 'move']
        bases = [q for q in requests if q['accepted'] and q['request']['op'] == 'base']
        arm_moves = {arm: [q for q in moves if any(k.startswith(arm+'_')
                      for k in q['request']['targets'])] for arm in ('left','right')}
        row['counts'] = {'base':len(bases), 'move':len(moves),
            'left_arm_move':len(arm_moves['left']), 'right_arm_move':len(arm_moves['right']),
            'observations':len(observations), 'base_segments':len(segments),
            'rejected_motion':sum(not q['accepted'] for q in requests
                                 if q['request']['op'] in ('move','base'))}
        if len(bases)+len(moves) != result.get('actions'):
            warnings.append({'run':run,'kind':'action_count_difference',
                             'extracted':len(bases)+len(moves),'result':result.get('actions')})
        row['press_command_targets'] = press_targets
        row['last_command_targets'] = targets
        # Targets are commands, never falsely labelled achieved physical poses.
        detail = {'run':run, 'event_source':str((sim/'events.jsonl').relative_to(ROOT)),
            'requests':requests,'observations':observations,'signals':signals,
            'public_states':states,'base_segments':segments,'arm_moves':arm_moves}
        (OUT/'extracted'/f'{run}.json').write_text(json.dumps(detail,ensure_ascii=False,indent=2)+'\n')
        corpus.append(row)
        extracted.append(detail)
    summary = {
        'runs':len(corpus), 'core_runs':sum(x['role']=='core' for x in corpus),
        'successes':sum(x['result']['physical_success'] for x in corpus),
        'failures':[x['run'] for x in corpus if not x['result']['physical_success']],
        'model_hashes':dict(collections.Counter(x['model_sha256'] for x in corpus)),
        'counts':{k:sum(x['counts'][k] for x in corpus) for k in corpus[0]['counts']},
        'warnings':warnings,
        'coverage':'All whitelisted event streams parsed; this is not visual review of every action.',
    }
    (OUT/'CORPUS.json').write_text(json.dumps(corpus,ensure_ascii=False,indent=2)+'\n')
    (OUT/'EXTRACTION_SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
