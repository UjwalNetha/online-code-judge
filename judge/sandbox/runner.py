import json
import os
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

LAUNCHER = Path(__file__).with_name("launcher.py")
GRACE_SECONDS = 5  # the launcher has its own watchdog, this one is a backup
MAX_STDERR_BYTES = 64 * 1024
DEFAULT_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/box", "LANG": "C.UTF-8"}


class SandboxError(Exception):
    pass


@dataclass
class Limits:
    cpu_seconds: float
    wall_seconds: float
    memory_mb: int
    output_bytes: int
    nproc: int = 32
    nofile: int = 64
    box_mb: int = 16


@dataclass
class RunResult:
    exit_code: int | None
    signal: int | None
    cpu_ms: int
    wall_ms: int
    peak_kb: int
    timed_out: bool
    stdout: bytes = b""
    stderr: bytes = b""


def run(command, limits, code_dir=None, box_dir=None, data_dir=None, stdin=b"", env=None):
    """Run a command in a new sandbox and return what happened.

    code_dir and data_dir are mounted read-only at /code and /data. box_dir is
    mounted writable at /box. Without it /box is a small throwaway tmpfs.
    """
    with tempfile.TemporaryDirectory(prefix="sandbox-", ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        (tmp / "root").mkdir()
        (tmp / "stdin").write_bytes(stdin)

        read_end, write_end = os.pipe()
        config = {
            "command": command,
            "env": env or DEFAULT_ENV,
            "root": str(tmp / "root"),
            "code_dir": code_dir and str(code_dir),
            "box_dir": box_dir and str(box_dir),
            "data_dir": data_dir and str(data_dir),
            "result_fd": write_end,
            "cpu_seconds": limits.cpu_seconds,
            "wall_seconds": limits.wall_seconds,
            "memory_mb": limits.memory_mb,
            "output_bytes": limits.output_bytes,
            "nproc": limits.nproc,
            "nofile": limits.nofile,
            "box_mb": limits.box_mb,
        }

        with open(tmp / "stdin", "rb") as stdin_file, \
                open(tmp / "stdout", "wb") as stdout_file, \
                open(tmp / "stderr", "wb") as stderr_file:
            process = subprocess.Popen(
                [sys.executable, "-I", "-S", str(LAUNCHER), json.dumps(config)],
                stdin=stdin_file,
                stdout=stdout_file,
                stderr=stderr_file,
                pass_fds=(write_end,),
                start_new_session=True,
                env={},
            )
        os.close(write_end)

        try:
            process.wait(timeout=limits.wall_seconds + GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        finally:
            kill_group(process)

        with os.fdopen(read_end, "rb") as pipe:
            report = pipe.read()

        if not report:
            raise SandboxError("sandbox ended without a result")
        result = json.loads(report)
        if "error" in result:
            raise SandboxError(result["error"])

        stdout = read_limited(tmp / "stdout", limits.output_bytes + 1)
        stderr = read_limited(tmp / "stderr", MAX_STDERR_BYTES)
        return RunResult(**result, stdout=stdout, stderr=stderr)


def kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def read_limited(path, size):
    with open(path, "rb") as f:
        return f.read(size)
