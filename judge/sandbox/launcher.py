"""Runs one command inside the sandbox.

Started by runner.py with the config as JSON in argv[1]. It is run with
python -I -S, so it can only use the standard library.

Process tree: launcher -> init (pid 1 in the new namespace) -> program.
The program can't be pid 1 because the kernel drops SIGXCPU and SIGXFSZ for
pid 1. When init exits, the kernel kills everything left in the namespace.
"""
import ctypes
import json
import math
import os
import platform
import resource
import signal
import struct
import sys
import time

libc = ctypes.CDLL(None, use_errno=True)

CLONE_NEWNS = 0x00020000
CLONE_NEWCGROUP = 0x02000000
CLONE_NEWUTS = 0x04000000
CLONE_NEWIPC = 0x08000000
CLONE_NEWUSER = 0x10000000
CLONE_NEWPID = 0x20000000
CLONE_NEWNET = 0x40000000
NAMESPACE_FLAGS = (
    CLONE_NEWNS | CLONE_NEWCGROUP | CLONE_NEWUTS | CLONE_NEWIPC
    | CLONE_NEWUSER | CLONE_NEWPID | CLONE_NEWNET
)

MS_RDONLY = 1
MS_NOSUID = 2
MS_NODEV = 4
MS_NOEXEC = 8
MS_REMOUNT = 32
MS_NOATIME = 1024
MS_NODIRATIME = 2048
MS_BIND = 4096
MS_REC = 16384
MS_PRIVATE = 1 << 18
MNT_DETACH = 2

SYS_PIVOT_ROOT = 155
PR_SET_NO_NEW_PRIVS = 38
PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2

SANDBOX_UID = 65534
AS_HEADROOM_MB = 64  # interpreters and shared libraries map memory they never touch
STACK_BYTES = 64 * 1024 * 1024
READ_ONLY_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib64")
DEVICES = ("null", "zero", "urandom")

# x86_64 syscall numbers
DENIED_SYSCALLS = (
    41, 42, 43, 49, 50, 288,  # socket, connect, accept, bind, listen, accept4
    101, 310, 311, 438,  # ptrace, process_vm_readv/writev, pidfd_getfd
    165, 166, 155, 161, 272, 308,  # mount, umount2, pivot_root, chroot, unshare, setns
    428, 429, 430, 431, 432, 433, 442,  # new mount api
    175, 176, 313, 246, 320,  # kernel modules and kexec
    321, 298, 323, 425, 426, 427,  # bpf, perf_event_open, userfaultfd, io_uring
    248, 249, 250, 303, 304,  # keyrings, file handles
    103, 159, 163, 164, 167, 168, 169, 172, 173, 179, 227,  # host admin calls
)
SYS_CLONE = 56
SYS_CLONE3 = 435

AUDIT_ARCH_X86_64 = 0xC000003E
X32_SYSCALL_BIT = 0x40000000
RET_KILL_PROCESS = 0x80000000
RET_ERRNO = 0x00050000
RET_ALLOW = 0x7FFF0000
ENOSYS = 38

BPF_LD_W_ABS = 0x20
BPF_JEQ = 0x15
BPF_JGE = 0x35
BPF_JSET = 0x45
BPF_RET = 0x06


def check(ret):
    if ret != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))


def mount(source, target, fstype, flags, data=None):
    args = [s.encode() if s else None for s in (source, target, fstype, data)]
    check(libc.mount(args[0], args[1], args[2], ctypes.c_ulong(flags), args[3]))


def bind_read_only(source, target):
    mount(source, target, None, MS_BIND | MS_REC)
    # flags the outer mount has set must be kept or the remount gets EPERM
    kept = os.statvfs(target).f_flag & (MS_NOSUID | MS_NODEV | MS_NOEXEC | MS_NOATIME | MS_NODIRATIME)
    mount(None, target, None, MS_BIND | MS_REMOUNT | MS_RDONLY | MS_NOSUID | kept)


def write_file(path, text):
    with open(path, "w") as f:
        f.write(text)


def enter_namespaces():
    uid, gid = os.getuid(), os.getgid()
    check(libc.unshare(
        CLONE_NEWUSER | CLONE_NEWNS | CLONE_NEWNET | CLONE_NEWPID | CLONE_NEWIPC | CLONE_NEWUTS
    ))
    write_file("/proc/self/setgroups", "deny")
    write_file("/proc/self/uid_map", f"{SANDBOX_UID} {uid} 1")
    write_file("/proc/self/gid_map", f"{SANDBOX_UID} {gid} 1")


def build_root(cfg):
    root = cfg["root"]
    mount(None, "/", None, MS_REC | MS_PRIVATE)
    mount("tmpfs", root, "tmpfs", MS_NOSUID | MS_NODEV, "size=1m,mode=755")

    for path in READ_ONLY_DIRS:
        target = root + path
        if os.path.islink(path):
            os.symlink(os.readlink(path), target)
        elif os.path.isdir(path):
            os.mkdir(target)
            bind_read_only(path, target)

    os.mkdir(root + "/dev")
    for name in DEVICES:
        target = f"{root}/dev/{name}"
        write_file(target, "")
        mount(f"/dev/{name}", target, None, MS_BIND)

    os.mkdir(root + "/box")
    if cfg["box_dir"]:
        mount(cfg["box_dir"], root + "/box", None, MS_BIND)
    else:
        size = f"size={cfg['box_mb']}m,mode=777"
        mount("tmpfs", root + "/box", "tmpfs", MS_NOSUID | MS_NODEV, size)

    for name in ("code", "data"):
        if cfg[f"{name}_dir"]:
            os.mkdir(f"{root}/{name}")
            bind_read_only(cfg[f"{name}_dir"], f"{root}/{name}")

    os.chdir(root)
    check(libc.syscall(ctypes.c_long(SYS_PIVOT_ROOT), b".", b"."))
    check(libc.umount2(b".", MNT_DETACH))
    os.chdir("/")
    mount(None, "/", None, MS_REMOUNT | MS_BIND | MS_RDONLY | MS_NOSUID | MS_NODEV)
    os.chdir("/box")


def apply_limits(cfg):
    memory = (cfg["memory_mb"] + AS_HEADROOM_MB) * 1024 * 1024
    cpu = math.ceil(cfg["cpu_seconds"]) + 1
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_FSIZE, (cfg["output_bytes"] + 1, cfg["output_bytes"] + 1))
    resource.setrlimit(resource.RLIMIT_NPROC, (cfg["nproc"], cfg["nproc"]))
    resource.setrlimit(resource.RLIMIT_NOFILE, (cfg["nofile"], cfg["nofile"]))
    resource.setrlimit(resource.RLIMIT_STACK, (STACK_BYTES, STACK_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def bpf(code, k, jt=0, jf=0):
    return struct.pack("=HBBI", code, jt, jf, k)


def seccomp_filter():
    prog = [
        bpf(BPF_LD_W_ABS, 4),  # architecture
        bpf(BPF_JEQ, AUDIT_ARCH_X86_64, jt=1),
        bpf(BPF_RET, RET_KILL_PROCESS),
        bpf(BPF_LD_W_ABS, 0),  # syscall number
        bpf(BPF_JGE, X32_SYSCALL_BIT, jf=1),
        bpf(BPF_RET, RET_KILL_PROCESS),
    ]
    for number in DENIED_SYSCALLS:
        prog.append(bpf(BPF_JEQ, number, jf=1))
        prog.append(bpf(BPF_RET, RET_KILL_PROCESS))

    # clone3 keeps its flags in memory where seccomp can't see them.
    # ENOSYS makes libc fall back to clone, which we can check.
    prog.append(bpf(BPF_JEQ, SYS_CLONE3, jf=1))
    prog.append(bpf(BPF_RET, RET_ERRNO | ENOSYS))
    prog.append(bpf(BPF_JEQ, SYS_CLONE, jf=3))
    prog.append(bpf(BPF_LD_W_ABS, 16))  # first argument, low 32 bits
    prog.append(bpf(BPF_JSET, NAMESPACE_FLAGS, jf=1))
    prog.append(bpf(BPF_RET, RET_KILL_PROCESS))
    prog.append(bpf(BPF_RET, RET_ALLOW))
    return b"".join(prog), len(prog)


def install_seccomp():
    code, length = seccomp_filter()
    buffer = ctypes.create_string_buffer(code)

    class SockFprog(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]

    program = SockFprog(length, ctypes.addressof(buffer))
    check(libc.prctl(PR_SET_NO_NEW_PRIVS, ctypes.c_ulong(1), ctypes.c_ulong(0),
                     ctypes.c_ulong(0), ctypes.c_ulong(0)))
    check(libc.prctl(PR_SET_SECCOMP, ctypes.c_ulong(SECCOMP_MODE_FILTER),
                     ctypes.byref(program), ctypes.c_ulong(0), ctypes.c_ulong(0)))


def start_program(cfg, result_fd):
    try:
        os.close(result_fd)
        os.setsid()
        # python ignores these two and exec would pass that on to the program
        signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        apply_limits(cfg)
        install_seccomp()
        os.execve(cfg["command"][0], cfg["command"], cfg["env"])
    finally:
        os._exit(127)


def run_init(cfg, result_fd):
    build_root(cfg)
    started = time.monotonic()
    pid = os.fork()
    if pid == 0:
        start_program(cfg, result_fd)

    timed_out = False

    def on_alarm(*_):
        nonlocal timed_out
        timed_out = True
        os.kill(pid, signal.SIGKILL)

    signal.signal(signal.SIGALRM, on_alarm)
    signal.setitimer(signal.ITIMER_REAL, cfg["wall_seconds"])
    _, status, usage = os.wait4(pid, 0)
    wall = time.monotonic() - started
    signal.setitimer(signal.ITIMER_REAL, 0)

    code = os.waitstatus_to_exitcode(status)
    os.write(result_fd, json.dumps({
        "exit_code": code if code >= 0 else None,
        "signal": -code if code < 0 else None,
        "cpu_ms": round((usage.ru_utime + usage.ru_stime) * 1000),
        "wall_ms": round(wall * 1000),
        "peak_kb": usage.ru_maxrss,
        "timed_out": timed_out,
    }).encode())


def main():
    cfg = json.loads(sys.argv[1])
    result_fd = cfg["result_fd"]
    os.set_inheritable(result_fd, False)
    try:
        if platform.machine() != "x86_64":
            raise RuntimeError("the seccomp filter only supports x86_64")
        if os.getuid() == 0:
            raise RuntimeError("refusing to run submissions as root")
        enter_namespaces()
        pid = os.fork()
        if pid == 0:
            try:
                run_init(cfg, result_fd)
            except Exception as error:
                os.write(result_fd, json.dumps({"error": repr(error)}).encode())
            finally:
                os._exit(0)
        os.waitpid(pid, 0)
    except Exception as error:
        os.write(result_fd, json.dumps({"error": repr(error)}).encode())


if __name__ == "__main__":
    main()
