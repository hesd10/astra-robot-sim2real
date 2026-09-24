"""Run isolated attempts sequentially, carrying only each predecessor's clean skill."""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim_env.setup import load_setup
from sim_env.transfer import audit


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    temporary.replace(path)


def git(subject, *args):
    return subprocess.check_output(
        ['git', '--git-dir='+str(subject/'.git'), '--work-tree='+str(subject), *args],
        stderr=subprocess.PIPE)


def finished_run(run):
    """A failed physical task may teach a skill; an incomplete/contaminated one cannot transfer."""
    private, subject = run/'private', run/'subject'
    agent = read_json(private/'agent-result.json')
    result = read_json(private/'simulation'/'result.json')
    if agent.get('status') != 'completed' or agent.get('exit_code') != 0:
        raise RuntimeError(f'{run.name}: Astra 未正常完成收尾，不能继续继承 skill')
    if result.get('subject_outcome') not in ('success', 'failure'):
        raise RuntimeError(f'{run.name}: 结果缺失或出现污染，禁止跨轮继承')
    screened = audit(subject/'skill')
    if not screened['mechanical_pass']:
        raise RuntimeError(f'{run.name}: skill 检查失败: {screened["findings"]}')
    if git(subject, 'status', '--porcelain', '--untracked-files=all', '--', 'skill').strip():
        raise RuntimeError(f'{run.name}: skill 存在未提交修改')
    # Each attempt starts with initialization + skill import, then one final audit commit.
    if int(git(subject, 'rev-list', '--count', 'HEAD')) != 3:
        raise RuntimeError(f'{run.name}: 未找到初始化、skill 导入及单次收尾提交')
    changed = git(subject, 'diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').decode().splitlines()
    if any(not name.startswith('skill/') for name in changed):
        raise RuntimeError(f'{run.name}: 收尾提交包含 skill/ 以外的文件')
    imported = read_json(private/'transfer-audit.json')['sha256']
    for name, digest in imported.items():
        if hashlib.sha256(git(subject, 'show', 'HEAD^:skill/'+name)).hexdigest() != digest:
            raise RuntimeError(f'{run.name}: 导入提交与继承记录不一致')
    for name, digest in screened['sha256'].items():
        if hashlib.sha256(git(subject, 'show', 'HEAD:skill/'+name)).hexdigest() != digest:
            raise RuntimeError(f'{run.name}: 已提交 skill 与工作目录不一致')
    for name in ('dashboard.mp4', 'follow.mp4', 'follow-compact.mp4'):
        if not (private/name).is_file() or not (private/name).stat().st_size:
            raise RuntimeError(f'{run.name}: 视频尚未保存: {name}')
    if read_json(private/'dashboard-recording.json').get('status') != 'saved':
        raise RuntimeError(f'{run.name}: 网页录像未完成保存')
    return {
        'run': run.name,
        'skill': str(subject/'skill'),
        'commit': git(subject, 'rev-parse', 'HEAD').decode().strip(),
        'skill_sha256': screened['sha256'],
        'physical_success': result['physical_success'],
        'subject_outcome': result['subject_outcome'],
        'elapsed_seconds': result['sim_seconds'],
        'motion_commands': result['actions'],
        'agent_wall_seconds': agent['elapsed_wall_s'],
        'videos': [str(private/name) for name in ('dashboard.mp4', 'follow.mp4', 'follow-compact.mp4')],
    }


def command_for(root, name, skill, setup, max_seconds, reasoning):
    return [sys.executable, '-u', str(root/'scripts'/'start_experiment.py'), name,
            '--setup', str(setup), '--skill', str(skill),
            '--max-seconds', str(max_seconds), '--reasoning', reasoning]


def run_batch(root, *, first=3, last=5, max_seconds=1800., reasoning='xhigh',
              setup=None, check_only=False):
    root = Path(root).resolve()
    setup = Path(setup or root/'setups'/'formal-001.json').resolve()
    if first < 2 or last < first or not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError('轮次范围和时间预算必须有效，first 至少为 2')
    load_setup(setup)
    names = [f'run-{number:03d}' for number in range(first, last+1)]
    previous = root/'experiments'/f'run-{first-1:03d}'
    source = finished_run(previous)
    for name in names:
        if (root/'experiments'/name).exists():
            raise RuntimeError(f'{name} 已存在；不覆盖、不自动续跑或跳过已有实验')
    batch = root/'reports'/'batches'/f'{names[0]}-to-{names[-1]}'
    if batch.exists():
        raise RuntimeError(f'批次目录已存在: {batch}')
    print(f'顺序执行: {" → ".join(names)}；每轮 {max_seconds/60:g} 分钟；{reasoning}', flush=True)
    print(f'初始 skill: {source["run"]} / {source["commit"]}', flush=True)
    print(f'正式起点: {setup}', flush=True)
    if check_only:
        print('预检通过；未创建轮次、未调用模型。', flush=True)
        return None

    batch.parent.mkdir(parents=True, exist_ok=True)
    with (root/'experiments'/'.iterations.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('已有自动迭代批次正在运行') from None
        # Recheck after obtaining the lock; the individual launcher also uses mkdir atomically.
        if any((root/'experiments'/name).exists() for name in names):
            raise RuntimeError('预检后出现同名实验，未启动批次')
        batch.mkdir()
        state = {'status': 'running', 'pid': os.getpid(), 'started_unix': time.time(),
                 'runs': names, 'max_seconds': max_seconds, 'reasoning': reasoning,
                 'setup': str(setup), 'initial_source': source,
                 'current_run': None, 'completed': [], 'active': None}
        status_path = batch/'status.json'
        write_json(status_path, state)
        process = None
        old_handlers = {}

        def interrupt(signum, frame):
            raise KeyboardInterrupt(f'received signal {signum}')

        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                old_handlers[sig] = signal.signal(sig, interrupt)
            for number, name in enumerate(names, 1):
                # Revalidate immediately before use; never fall back to an older round.
                source = finished_run(previous)
                command = command_for(root, name, source['skill'], setup, max_seconds, reasoning)
                state['current_run'] = name
                state['active'] = {'run': name, 'source': source, 'command': command,
                                   'log': str(batch/(name+'.log')), 'started_unix': time.time()}
                write_json(status_path, state)
                print(f'\n[{number}/{len(names)}] {name} ← {previous.name}，开始运行', flush=True)
                with (batch/(name+'.log')).open('x') as log:
                    process = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                        bufsize=1, start_new_session=True)
                    state['active']['pid'] = process.pid
                    write_json(status_path, state)
                    for line in process.stdout:
                        log.write(line); log.flush()
                        print(f'[{name}] {line}', end='', flush=True)
                    code = process.wait()
                    process.stdout.close()
                    process = None
                if code:
                    raise RuntimeError(f'{name}: 启动器退出码 {code}；详见本轮日志')
                destination = root/'experiments'/name
                if read_json(destination/'private'/'transfer-audit.json')['sha256'] != source['skill_sha256']:
                    raise RuntimeError(f'{name}: 实际导入 skill 与上一轮记录不一致')
                outcome = finished_run(destination)
                state['completed'].append({**state['active'], 'result': outcome, 'ended_unix': time.time()})
                state['active'] = None
                write_json(status_path, state)
                print(f'[{name}] 已归档；物理成功={outcome["physical_success"]}；'
                      f'新 skill 提交={outcome["commit"]}', flush=True)
                previous = destination
            state.update(status='completed', current_run=None, ended_unix=time.time())
            write_json(status_path, state)
            print(f'全部 {len(names)} 轮已完成，视频和 skill 均已归档。汇总: {status_path}', flush=True)
            return state
        except BaseException as exc:
            if process is not None and process.poll() is None:
                # Interrupt only the launcher; let its finally block close physics and videos.
                process.send_signal(signal.SIGINT)
                try:
                    remaining, _ = process.communicate(timeout=180)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    remaining, _ = process.communicate(timeout=15)
                if remaining:
                    with Path(state['active']['log']).open('a') as log:
                        log.write(remaining)
            state.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                         error=f'{type(exc).__name__}: {exc}', ended_unix=time.time())
            write_json(status_path, state)
            print(f'批次已停止: {state["error"]}；保留现有结果，不启动后续轮次。', flush=True)
            raise
        finally:
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first', type=int, default=3)
    parser.add_argument('--last', type=int, default=5)
    parser.add_argument('--max-seconds', type=float, default=1800.)
    parser.add_argument('--reasoning', choices=['medium', 'high', 'xhigh'], default='xhigh')
    parser.add_argument('--setup', default=str(ROOT/'setups'/'formal-001.json'))
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    from sim_env.dashboard_recording import check_available
    check_available()
    run_batch(ROOT, **vars(args))


if __name__ == '__main__':
    main()
