import glob
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
from helpers import make_problem, needs_linux

from judge import compiler, sandbox
from judge.judging import judge

pytestmark = needs_linux

LIMITS = sandbox.Limits(cpu_seconds=2, wall_seconds=4, memory_mb=128, output_bytes=1024 * 1024)


def run_python(source, limits=LIMITS, stdin=b""):
    with tempfile.TemporaryDirectory() as code_dir:
        program = compiler.prepare("python", source, code_dir)
        return sandbox.run(program.command, limits, code_dir=code_dir, stdin=stdin, env=program.env)


def run_cpp(source, limits=LIMITS):
    with tempfile.TemporaryDirectory() as code_dir:
        program = compiler.prepare("cpp", source, code_dir)
        return sandbox.run(program.command, limits, code_dir=code_dir, env=program.env)


def test_runs_as_unprivileged_user():
    result = run_python("import os\nprint(os.getuid(), os.getgid(), os.geteuid())")
    assert result.stdout.split() == [b"65534", b"65534", b"65534"]


def test_environment_is_clean(monkeypatch):
    monkeypatch.setenv("DATABASE_PASSWORD", "topsecret")
    result = run_python("import os\nprint(sorted(os.environ))")
    assert b"topsecret" not in result.stdout
    assert b"JWT_SECRET" not in result.stdout
    assert b"DATABASE" not in result.stdout


def test_filesystem_view_is_minimal():
    result = run_python("import os\nprint(sorted(os.listdir('/')))")
    assert eval(result.stdout) == sorted(
        name for name in ["bin", "box", "code", "dev", "lib", "lib64", "sbin", "usr"]
        if name in ("box", "code", "dev", "usr") or os.path.exists(f"/{name}")
    )


def test_working_directory_is_writable():
    source = "import os\nopen('x.txt', 'w').write('hi')\nprint(os.getcwd(), open('x.txt').read())"
    assert run_python(source).stdout.split() == [b"/box", b"hi"]


def test_root_code_and_system_dirs_are_read_only():
    source = """
for path in ('/x', '/usr/x', '/code/x', '/dev/x'):
    try:
        open(path, 'w')
        print('WROTE', path)
    except OSError as error:
        print(error.errno)
"""
    assert b"WROTE" not in run_python(source).stdout


def test_box_size_is_limited():
    limits = sandbox.Limits(2, 4, 128, 64 * 1024 * 1024, box_mb=1)
    source = "open('big', 'wb').write(b'x' * (8 * 1024 * 1024))"
    result = run_python(source, limits)
    assert result.exit_code == 1
    assert b"No space left" in result.stderr


def test_rlimits_are_set():
    source = """
import resource as r
for name in ('RLIMIT_CPU', 'RLIMIT_AS', 'RLIMIT_FSIZE', 'RLIMIT_NPROC', 'RLIMIT_NOFILE', 'RLIMIT_CORE'):
    print(getattr(r, name), r.getrlimit(getattr(r, name))[0])
"""
    values = dict(line.split() for line in run_python(source).stdout.decode().splitlines())
    import resource as r

    assert int(values[str(r.RLIMIT_CPU)]) == 3
    assert int(values[str(r.RLIMIT_AS)]) == (128 + 64) * 1024 * 1024
    assert int(values[str(r.RLIMIT_FSIZE)]) == 1024 * 1024 + 1
    assert int(values[str(r.RLIMIT_NPROC)]) == 32
    assert int(values[str(r.RLIMIT_NOFILE)]) == 64
    assert int(values[str(r.RLIMIT_CORE)]) == 0


def test_limits_cannot_be_raised():
    source = """
import resource as r
r.setrlimit(r.RLIMIT_AS, (r.RLIM_INFINITY, r.RLIM_INFINITY))
"""
    result = run_python(source)
    assert result.exit_code == 1
    assert b"ValueError" in result.stderr


def test_open_files_are_limited():
    result = run_python("files = [open('/dev/null') for _ in range(1000)]")
    assert result.exit_code == 1
    assert b"Too many open files" in result.stderr


def test_process_count_is_limited():
    source = """
import os, time
count = 0
try:
    while True:
        if os.fork() == 0:
            time.sleep(5)
            os._exit(0)
        count += 1
except OSError:
    print(count)
"""
    result = run_python(source)
    assert 0 < int(result.stdout) < 32


def test_cpu_limit_is_enforced_by_the_kernel():
    limits = sandbox.Limits(cpu_seconds=1, wall_seconds=30, memory_mb=128, output_bytes=1024)
    result = run_python("while True: pass", limits)
    assert result.signal in (24, 9)
    assert not result.timed_out
    assert result.cpu_ms >= 1000


def test_wall_limit_kills_sleeper():
    limits = sandbox.Limits(cpu_seconds=1, wall_seconds=0.5, memory_mb=128, output_bytes=1024)
    result = run_python("import time\ntime.sleep(60)", limits)
    assert result.timed_out
    assert result.wall_ms < 1500


def test_output_is_cut_at_the_limit():
    result = run_python("import sys\nwhile True: sys.stdout.write('x' * 65536)")
    assert len(result.stdout) == 1024 * 1024 + 1


# timing tests take the best of three so a busy machine doesn't fail them
def test_cpu_time_is_measured():
    source = "import time\nend = time.process_time() + 0.5\nwhile time.process_time() < end: pass"
    results = [run_python(source).cpu_ms for _ in range(3)]
    assert 450 <= min(results) <= 800


def test_sleeping_uses_no_cpu_time():
    results = [run_python("import time\ntime.sleep(0.5)") for _ in range(3)]
    assert min(result.cpu_ms for result in results) < 300
    assert min(result.wall_ms for result in results) >= 500


def test_peak_memory_is_measured():
    source = "x = bytearray(60 * 1024 * 1024)\nfor i in range(0, len(x), 4096): x[i] = 1"
    peak_mb = run_python(source).peak_kb / 1024
    assert 60 <= peak_mb <= 85


def test_peak_memory_is_consistent_between_runs():
    source = "x = bytearray(40 * 1024 * 1024)\nfor i in range(0, len(x), 4096): x[i] = 1"
    peaks = [run_python(source).peak_kb for _ in range(3)]
    assert max(peaks) - min(peaks) < 2048


def stray_processes(marker):
    found = []
    for path in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            if marker in Path(path).read_bytes():
                found.append(path)
        except OSError:
            pass
    return found


def test_processes_that_escape_the_group_are_killed():
    marker = uuid.uuid4().hex
    source = f"""
import os, time
if os.fork() == 0:
    os.setsid()
    if os.fork() == 0:
        os.execv('{sys.executable}', ['python3', '-c', 'import time; time.sleep(60)', '{marker}'])
    os._exit(0)
time.sleep(0.2)
"""
    run_python(source)
    assert stray_processes(marker.encode()) == []


def test_background_child_cannot_outlive_a_timeout():
    marker = uuid.uuid4().hex
    limits = sandbox.Limits(cpu_seconds=1, wall_seconds=0.5, memory_mb=128, output_bytes=1024)
    source = f"""
import os, time
os.fork()
time.sleep(60)  # {marker}
"""
    with tempfile.TemporaryDirectory() as code_dir:
        program = compiler.prepare("python", source, code_dir)
        sandbox.run(program.command + [marker], limits, code_dir=code_dir, env=program.env)
    assert stray_processes(marker.encode()) == []


def test_temp_files_are_removed():
    before = set(glob.glob(f"{tempfile.gettempdir()}/sandbox-*") + glob.glob(f"{tempfile.gettempdir()}/judge-*"))
    judge("cpp", "int main() {}", make_problem())
    run_python("open('leftover', 'w').write('x')")
    after = set(glob.glob(f"{tempfile.gettempdir()}/sandbox-*") + glob.glob(f"{tempfile.gettempdir()}/judge-*"))
    assert after == before


def zombie_children():
    zombies = []
    for path in glob.glob("/proc/[0-9]*/stat"):
        try:
            state, parent = Path(path).read_text().rsplit(")", 1)[1].split()[:2]
        except OSError:
            continue
        if state == "Z" and int(parent) == os.getpid():
            zombies.append(path)
    return zombies


def test_no_zombies_left_behind():
    run_python("import os\nos.fork()")
    limits = sandbox.Limits(cpu_seconds=1, wall_seconds=0.3, memory_mb=128, output_bytes=1024)
    run_python("import time\ntime.sleep(60)", limits)
    assert zombie_children() == []


def test_runs_do_not_share_the_working_directory():
    run_python("open('/box/secret', 'w').write('x')")
    result = run_python("import os\nprint(os.listdir('/box'))")
    assert result.stdout.strip() == b"[]"


@pytest.mark.parametrize("call", [
    "unshare(CLONE_NEWUSER)",
    "ptrace(PTRACE_TRACEME, 0, 0, 0)",
    "mount(\"none\", \"/box\", \"tmpfs\", 0, 0)",
    "syscall(SYS_clone, CLONE_NEWUSER | SIGCHLD, 0, 0, 0, 0)",
    "syscall(SYS_bpf, 0, 0, 0)",
])
def test_seccomp_kills_dangerous_syscalls(call):
    source = f"""
#include <sched.h>
#include <signal.h>
#include <sys/mount.h>
#include <sys/ptrace.h>
#include <sys/syscall.h>
#include <unistd.h>
int main() {{ {call}; return 0; }}
"""
    assert run_cpp(source).signal == 31


def test_thirty_two_bit_syscalls_are_blocked():
    source = """
int main() {
    long result;
    asm volatile("int $0x80" : "=a"(result) : "a"(20));
    return 0;
}
"""
    assert run_cpp(source).signal == 31


def test_clone3_is_refused():
    source = """
#include <cerrno>
#include <cstdio>
#include <sys/syscall.h>
#include <unistd.h>
int main() {
    long result = syscall(435, 0, 0);
    std::printf("%ld %d", result, errno);
}
"""
    assert run_cpp(source).stdout == b"-1 38"


def test_threads_still_work():
    source = """
import threading
hits = []
threads = [threading.Thread(target=lambda: hits.append(1)) for _ in range(4)]
[t.start() for t in threads]
[t.join() for t in threads]
print(len(hits))
"""
    assert run_python(source).stdout == b"4\n"
