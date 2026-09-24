"""Read-only operator feed. No monitor state is sent back to the subject."""
from collections import OrderedDict
import json
from pathlib import Path
import threading
import time

TEXT_LIMIT = 12000
ENTRY_LIMIT = 160


def clipped(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + '\n…（页面节略，完整内容见原始日志）'


def public_event(message, stamp):
    """Whitelist visible native events; never publish reasoning or image payloads."""
    method, p = message.get('method', ''), message.get('params', {})
    row = {'event': method, 'monotonic': stamp}
    if method in ('turn/started', 'turn/completed'):
        turn = p.get('turn', {})
        return dict(row, status=turn.get('status'), error=turn.get('error'))
    if method in ('item/agentMessage/delta', 'item/commandExecution/outputDelta', 'item/plan/delta'):
        return dict(row, id=p['itemId'], delta=clipped(p.get('delta', '')))
    if method not in ('item/started', 'item/completed'):
        return None
    item = p.get('item', {})
    kind = item.get('type')
    fields = {
        'agentMessage': ('text', 'phase'), 'plan': ('text',),
        'commandExecution': ('command', 'aggregatedOutput', 'exitCode', 'status'),
        'imageView': ('path',), 'contextCompaction': (), 'sleep': ('durationMs',),
        'reasoning': (),
        'fileChange': ('status',),
        'dynamicToolCall': ('tool', 'namespace', 'status', 'success'),
        'mcpToolCall': ('tool', 'server', 'status'),
    }
    if kind not in fields:
        return None
    public = {key: clipped(item[key]) if isinstance(item[key], str) else item[key]
              for key in fields[kind] if key in item}
    if kind == 'fileChange':
        public['paths'] = [c.get('path') for c in item.get('changes', [])][:50]
    return dict(row, id=item['id'], kind=kind, **public)


class Tail:
    """Bounded incremental JSONL reader; incomplete writes wait for the next poll."""
    def __init__(self, path):
        self.path = Path(path)
        self.offset = 0

    def read(self):
        rows = []
        try:
            with self.path.open('rb') as source:
                source.seek(self.offset)
                used = 0
                while used < 256 * 1024:
                    line = source.readline()
                    if not line.endswith(b'\n'):
                        break
                    self.offset += len(line)
                    used += len(line)
                    try: rows.append(json.loads(line))
                    except (ValueError, UnicodeDecodeError): pass
        except FileNotFoundError:
            pass
        return rows


class Workflow:
    def __init__(self, log_dir, agent_file=None):
        self.log_dir = Path(log_dir)
        self.agent = Tail(agent_file) if agent_file else None
        self.robot = Tail(self.log_dir / 'events.jsonl')
        self.entries = OrderedDict()
        self.active = {}
        self.revision = 0
        self.total = 0
        self.started = self.ended = None
        self.phase = 'starting' if agent_file else 'preview'
        self.model = None
        self.last_event = None
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def entry(self, ident, stamp, **fields):
        if ident not in self.entries:
            self.total += 1
            self.entries[ident] = {'id': ident, 'monotonic': stamp, 'order': self.total}
        self.entries[ident].update(fields, revision=self.revision)
        # This cap only bounds the operator page. Native context/logs are unchanged.
        while len(self.entries) > ENTRY_LIMIT:
            oldest = next((key for key in self.entries if key not in self.active), next(iter(self.entries)))
            del self.entries[oldest]

    def apply_agent(self, row):
        event, stamp = row['event'], row['monotonic']
        self.last_event = stamp
        self.revision += 1
        ident = 'agent:' + str(row.get('id', event))
        if event == 'session/started':
            self.started, self.model, self.phase = stamp, row.get('model'), 'starting'
            self.entry('session:start', stamp, source='session', title='原生 Codex 会话启动', status='已启动', text=self.model or '')
        elif event == 'turn/started':
            self.phase = 'waiting'
        elif event in ('turn/completed', 'session/ended'):
            status = row.get('status', 'completed')
            self.phase = 'completed' if status == 'completed' else 'error' if status in ('error', 'failed') else 'ended'
            self.ended = stamp
            self.active.clear()
            self.entry('session:end', stamp, source='session', title='Astra 会话结束', status=status,
                       text=clipped(row.get('error') or '模型会话状态不等同于物理任务判定。'))
        elif event.endswith('/delta') or event.endswith('/outputDelta'):
            is_output = event == 'item/commandExecution/outputDelta'
            old = self.entries.get(ident, {})
            field = 'output' if is_output else 'text'
            self.entry(ident, stamp, source='tool' if is_output else 'assistant',
                       title=old.get('title', '工具执行' if is_output else 'Astra 输出'),
                       status='执行中' if is_output else '输出中',
                       **{field: clipped(old.get(field, '') + row['delta'])})
            self.active[ident] = 'tool' if is_output else 'assistant'
            self.phase = 'waiting'
        elif event in ('item/started', 'item/completed'):
            kind, done = row['kind'], event == 'item/completed'
            if kind == 'reasoning':
                self.phase = 'waiting'
                return
            titles = {'agentMessage': 'Astra 输出', 'plan': 'Astra 计划', 'commandExecution': '执行命令',
                      'imageView': '读取图像', 'contextCompaction': 'Codex 整理上下文',
                      'fileChange': '修改文件', 'sleep': '等待', 'dynamicToolCall': '工具调用', 'mcpToolCall': '工具调用'}
            source = 'assistant' if kind in ('agentMessage', 'plan') else 'tool'
            failed = row.get('status') in ('failed', 'declined') or row.get('exitCode') not in (None, 0) or row.get('success') is False
            fields = dict(source=source, title=titles[kind],
                          status=('失败' if failed else '已完成') if done else '输出中' if source == 'assistant' else '执行中')
            for source_key, dest in [('text', 'text'), ('command', 'command'), ('aggregatedOutput', 'output'),
                                     ('path', 'text'), ('exitCode', 'exit_code')]:
                if row.get(source_key) is not None: fields[dest] = row[source_key]
            if row.get('paths'): fields['text'] = '\n'.join(row['paths'])
            if row.get('tool'): fields['title'] += ' · ' + row['tool']
            if done: self.active.pop(ident, None)
            else: self.active[ident] = 'reading' if kind == 'imageView' else 'compacting' if kind == 'contextCompaction' else source
            self.entry(ident, stamp, **fields)
            self.phase = 'waiting'

    def apply_robot(self, row):
        event = row.get('event')
        if event not in ('request', 'observation_delivered', 'subject_finish', 'fault'):
            return
        stamp = row.get('monotonic', row.get('received_monotonic', time.monotonic()))
        self.last_event = max(stamp, self.last_event or stamp)
        self.revision += 1
        common = dict(source='robot', sim_time=row.get('sim_time'))
        if event == 'request':
            req = row['request']; op = req.get('op', '?')
            labels = {'base': '底盘控制', 'move': '关节控制', 'state': '读取机器人状态',
                      'schema': '读取接口定义', 'stop': '停止指令', 'finish': '提交任务结果'}
            status = '已接受' if row['accepted'] else '已拒绝'
            if row['accepted'] and op in ('state', 'schema'): status = '已返回'
            note = '指令已接受；不代表运动已完成。' if row['accepted'] and op in ('base', 'move', 'stop') else ''
            self.entry('robot:' + req['id'], stamp, **common, title=labels.get(op, op), status=status,
                       command=clipped(req), output=clipped(row.get('reply', {'ok': row['accepted']})), text=note)
        elif event == 'observation_delivered':
            self.entry('robot:' + row['id'], stamp, **common, title='三路新观测已送达', status='已返回',
                       text=f"head · left_wrist · right_wrist\n采集延迟 {row['age_seconds']*1000:.0f} ms；读图工具调用另行显示。")
        elif event == 'subject_finish':
            self.entry('robot:finish', stamp, **common, title='模型声明任务结束', status=row['outcome'],
                       text='这是模型声明；物理判定另见实验结果。')
        else:
            self.entry('robot:fault', stamp, **common, title='机器人保护停机', status='故障', text=row.get('reason', ''))

    def poll(self):
        rows = [('robot', row) for row in self.robot.read()]
        if self.agent: rows += [('agent', row) for row in self.agent.read()]
        rows.sort(key=lambda pair: pair[1].get('monotonic', pair[1].get('received_monotonic', 0)))
        with self.lock:
            for source, row in rows:
                (self.apply_agent if source == 'agent' else self.apply_robot)(row)

    def snapshot(self, since=None):
        with self.lock:
            phase = self.phase
            if self.active and self.ended is None:
                phase = next((p for p in ('tool', 'reading', 'compacting', 'assistant') if p in self.active.values()), phase)
            result = dict(revision=self.revision, phase=phase, model=self.model,
                          started_monotonic=self.started, ended_monotonic=self.ended,
                          elapsed_seconds=max(0., (self.ended or time.monotonic())-self.started) if self.started else None,
                          last_event_monotonic=self.last_event, total_entries=self.total,
                          entry_limit=ENTRY_LIMIT, error=self.error)
            if since != self.revision:
                result['entries'] = [dict(e) for e in sorted(self.entries.values(), key=lambda e: (e['monotonic'], e['order']))]
            return result

    def run(self):
        while not self.stop.is_set():
            try: self.poll()
            except Exception as exc: self.error = type(exc).__name__
            self.stop.wait(.15)

    def close(self, output_path=None):
        self.stop.set(); self.thread.join(timeout=2)
        self.poll()
        output = Path(output_path) if output_path else self.log_dir/'workflow-last.json'
        output.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2)+'\n')
