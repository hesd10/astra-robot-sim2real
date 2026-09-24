"""Fail-closed Linux runner for subject shell tools.

The orchestration layer must route EVERY subject filesystem/exec tool here.
This cannot restrict a separate tool provider which bypasses this runner.
"""
import argparse
import ctypes as C
import errno
import os
from pathlib import Path
import platform
import resource
import socket

SUBJECT_DEPENDENCIES = Path(__file__).resolve().parents[1] / '.subject-deps'


def check(ret, operation):
    if ret < 0:
        raise OSError(C.get_errno(), operation)
    return ret


def restrict(workspace):
    if platform.machine() not in ('x86_64', 'aarch64'):
        raise RuntimeError('unsupported architecture; no unsandboxed fallback')
    libc = C.CDLL(None, use_errno=True)
    abi = check(libc.syscall(444, 0, 0, 1), 'Landlock ABI query')
    if abi < 1:
        raise RuntimeError('Landlock unavailable')
    # ABI 1 controls bits 0..12. Later versions also control REFER/TRUNCATE.
    handled = (1 << (15 if abi >= 3 else 14 if abi >= 2 else 13))-1
    class Ruleset(C.Structure):
        _fields_ = [('handled_access_fs', C.c_uint64)]
    class PathRule(C.Structure):
        _pack_ = 1
        _fields_ = [('allowed_access', C.c_uint64), ('parent_fd', C.c_int32)]
    ruleset = Ruleset(handled)
    fd = check(libc.syscall(444, C.byref(ruleset), C.sizeof(ruleset), 0), 'Landlock create')
    try:
        readonly = (1 << 0) | (1 << 2) | (1 << 3)  # execute/read_file/read_dir
        entries = [(workspace, handled), ('/usr', readonly), ('/lib', readonly),
                   ('/lib64', readonly), ('/bin', readonly),
                   ('/etc/ld.so.cache', 1 << 2), ('/dev/null', (1 << 1) | (1 << 2)),
                   ('/dev/urandom', 1 << 2)]
        # Optional operator-installed generic libraries, never the host venv or
        # user site-packages. Subjects can read these dependencies but not edit
        # them; the rest of the private project remains inaccessible.
        if SUBJECT_DEPENDENCIES.is_dir():
            entries.append((SUBJECT_DEPENDENCIES, readonly))
        for path, rights in entries:
            if not Path(path).exists():
                continue
            parent = os.open(str(path), os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathRule(rights, parent)
                check(libc.syscall(445, fd, 1, C.byref(rule), 0), 'Landlock add rule')
            finally:
                os.close(parent)
        check(libc.prctl(38, 1, 0, 0, 0), 'no_new_privs')
        check(libc.syscall(446, fd, 0), 'Landlock restrict')
    finally:
        os.close(fd)
    seccomp = C.CDLL('libseccomp.so.2', use_errno=True)
    seccomp.seccomp_init.argtypes = [C.c_uint32]
    seccomp.seccomp_init.restype = C.c_void_p
    seccomp.seccomp_rule_add.argtypes = [C.c_void_p, C.c_uint32, C.c_int, C.c_uint]
    seccomp.seccomp_load.argtypes = [C.c_void_p]
    seccomp.seccomp_release.argtypes = [C.c_void_p]
    seccomp.seccomp_syscall_resolve_name.argtypes = [C.c_char_p]
    ctx = seccomp.seccomp_init(0x7fff0000)  # ALLOW except denied capabilities
    if not ctx:
        raise RuntimeError('seccomp initialization failed')
    denied = '''socket socketpair connect bind listen accept accept4 ptrace
        process_vm_readv process_vm_writev process_madvise pidfd_open pidfd_getfd
        pidfd_send_signal kill tkill tgkill mount umount2 pivot_root chroot unshare
        setns clone3 open_by_handle_at name_to_handle_at bpf perf_event_open
        userfaultfd io_uring_setup keyctl add_key request_key syslog reboot swapon
        swapoff init_module finit_module delete_module kexec_load kexec_file_load
        settimeofday clock_settime adjtimex mount_setattr open_tree move_mount
        fsopen fsconfig fsmount fspick truncate truncate64 chmod fchmodat fchmodat2
        chown lchown fchownat mknod mknodat'''.split()
    try:
        for name in denied:
            syscall = seccomp.seccomp_syscall_resolve_name(name.encode())
            if syscall >= 0:
                ret = seccomp.seccomp_rule_add(ctx, 0x00050000 | errno.EPERM, syscall, 0)
                if ret:
                    raise RuntimeError(f'seccomp rule failed: {name}')
        if seccomp.seccomp_load(ctx):
            raise RuntimeError('seccomp load failed')
    finally:
        seccomp.seccomp_release(ctx)
    # Drop all process capabilities even if the host runner is root.
    class Header(C.Structure):
        _fields_ = [('version', C.c_uint32), ('pid', C.c_int)]
    class CapData(C.Structure):
        _fields_ = [('effective', C.c_uint32), ('permitted', C.c_uint32), ('inheritable', C.c_uint32)]
    header = Header(0x20080522, 0)
    data = (CapData*2)()
    check(libc.capset(C.byref(header), C.byref(data)), 'drop capabilities')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return abi


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--socket-path')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    workspace = Path(args.workspace).resolve(strict=True)
    if not workspace.is_dir() or workspace == Path('/'):
        raise ValueError('dedicated subject directory required')
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        raise ValueError('command required')
    # Connection is made by the trusted launcher before networking is denied.
    connection = None
    if args.socket_path:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.connect(args.socket_path)
        except (FileNotFoundError, ConnectionRefusedError):
            connection.close()
            connection = None
        if connection:
            os.set_inheritable(connection.fileno(), True)
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1',
           'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': str(workspace/'.gitconfig'),
           'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'safe.directory', 'GIT_CONFIG_VALUE_0': str(workspace),
           'TMPDIR': str(workspace/'tmp')}
    if SUBJECT_DEPENDENCIES.is_dir():
        env['PYTHONPATH'] = str(SUBJECT_DEPENDENCIES)
    (workspace/'tmp').mkdir(exist_ok=True)
    if connection:
        env['ROBOT_FD'] = str(connection.fileno())
    else:
        env['ROBOT_OFFLINE'] = '1'
    os.chdir(workspace)
    restrict(workspace)
    os.execvpe(command[0], command, env)


if __name__ == '__main__':
    main()
