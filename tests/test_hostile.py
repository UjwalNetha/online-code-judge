import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from helpers import make_problem, needs_linux

from judge.judging import judge
from judge.models import (
    ACCEPTED,
    MEMORY_LIMIT,
    OUTPUT_LIMIT,
    RUNTIME_ERROR,
    TIME_LIMIT,
)

pytestmark = needs_linux

HOSTILE = Path(__file__).parent.parent / "hostile"
SIGSYS = 31

CASES = [
    ("infinite_loop.py", TIME_LIMIT),
    ("infinite_loop.cpp", TIME_LIMIT),
    ("memory_bomb.py", MEMORY_LIMIT),
    ("memory_bomb.cpp", MEMORY_LIMIT),
    ("fork_bomb.py", TIME_LIMIT),
    ("fork_bomb.cpp", TIME_LIMIT),
    ("print_gigabytes.py", OUTPUT_LIMIT),
    ("print_gigabytes.cpp", OUTPUT_LIMIT),
    ("read_passwd.py", RUNTIME_ERROR),
    ("read_judge_files.py", RUNTIME_ERROR),
    ("write_outside.py", RUNTIME_ERROR),
    ("open_socket.py", RUNTIME_ERROR),
    ("open_socket.cpp", RUNTIME_ERROR),
    ("sleeper.py", TIME_LIMIT),
    ("kill_others.py", ACCEPTED),
    ("symlink_trick.py", RUNTIME_ERROR),
]


def judge_file(name):
    language = "cpp" if name.endswith(".cpp") else "python"
    return judge(language, (HOSTILE / name).read_text(), make_problem([(100, [("", "still alive\n")])]))


@pytest.mark.parametrize("name,verdict", CASES)
def test_hostile_submission_gets_the_right_verdict(name, verdict):
    outcome = judge_file(name)
    assert outcome.verdict == verdict
    assert outcome.score == (100 if verdict == ACCEPTED else 0)


def test_write_outside_leaves_nothing_on_the_host():
    judge_file("write_outside.py")
    assert not Path("/usr/pwned.txt").exists()


@pytest.mark.parametrize("name", ["open_socket.py", "open_socket.cpp"])
def test_socket_is_stopped_by_seccomp(name):
    assert judge_file(name).results[0].signal == SIGSYS


def test_kill_others_does_not_reach_outside_processes():
    bystander = subprocess.Popen(["sleep", "30"])
    try:
        outcome = judge_file("kill_others.py")
        assert outcome.verdict == ACCEPTED
        assert bystander.poll() is None
    finally:
        bystander.kill()
        bystander.wait()


@pytest.mark.parametrize("name", ["fork_bomb.cpp", "memory_bomb.cpp", "print_gigabytes.py", "kill_others.py"])
def test_normal_submission_is_not_affected_by_a_hostile_one(name):
    normal = "import time\ntime.sleep(0.5)\nprint(input())"
    problem = make_problem([(100, [("hello\n", "hello\n")])], time_limit_ms=1000)

    with ThreadPoolExecutor(2) as pool:
        attack = pool.submit(judge_file, name)
        time.sleep(0.2)
        victim = pool.submit(judge, "python", normal, problem)
        assert victim.result().verdict == ACCEPTED
        attack.result()
