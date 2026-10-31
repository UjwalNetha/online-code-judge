import sys
from dataclasses import dataclass
from pathlib import Path

from judge import sandbox
from judge.sandbox.runner import DEFAULT_ENV

GXX = "/usr/bin/g++"
MAX_LOG_CHARS = 16 * 1024
COMPILE_LIMITS = sandbox.Limits(
    cpu_seconds=15,
    wall_seconds=30,
    memory_mb=1024,
    output_bytes=64 * 1024 * 1024,
    nofile=256,
)


class CompileError(Exception):
    pass


@dataclass
class Program:
    command: list[str]
    env: dict


def prepare(language, source, code_dir):
    """Write the source into code_dir and compile it if needed."""
    code_dir = Path(code_dir)
    if language == "python":
        (code_dir / "main.py").write_text(source)
        env = {**DEFAULT_ENV, "PYTHONDONTWRITEBYTECODE": "1", "LD_LIBRARY_PATH": "/usr/local/lib"}
        return Program([sys.executable, "/code/main.py"], env)
    if language == "cpp":
        (code_dir / "main.cpp").write_text(source)
        compile_cpp(code_dir)
        return Program(["/code/main"], DEFAULT_ENV)
    raise ValueError(f"unsupported language: {language}")


def compile_cpp(code_dir):
    command = [GXX, "-std=c++17", "-O2", "-o", "main", "main.cpp"]
    env = {**DEFAULT_ENV, "TMPDIR": "/box"}
    result = sandbox.run(command, COMPILE_LIMITS, box_dir=code_dir, env=env)
    log = (result.stderr or result.stdout).decode(errors="replace")[:MAX_LOG_CHARS]
    if result.timed_out or result.cpu_ms > COMPILE_LIMITS.cpu_seconds * 1000:
        raise CompileError("Compilation took too long")
    if result.exit_code != 0:
        raise CompileError(log or f"Compiler failed with signal {result.signal}")
    if (code_dir / "main").is_symlink():
        raise CompileError("Compiler did not produce a program")
