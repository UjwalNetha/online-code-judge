import pytest
from helpers import make_problem, needs_linux

from judge.judging import judge
from judge.models import (
    ACCEPTED,
    COMPILATION_ERROR,
    INTERNAL_ERROR,
    MEMORY_LIMIT,
    OUTPUT_LIMIT,
    RUNTIME_ERROR,
    TIME_LIMIT,
    WRONG_ANSWER,
)
from judge.sandbox import SandboxError

pytestmark = needs_linux

ADD = make_problem([(100, [("2 3\n", "5\n"), ("10 20\n", "30\n")])])

CPP_MAIN = "#include <iostream>\nint main() { %s }\n"


def test_accepted_python():
    outcome = judge("python", "a, b = map(int, input().split())\nprint(a + b)", ADD)
    assert outcome.verdict == ACCEPTED
    assert outcome.score == 100
    assert len(outcome.results) == 2


def test_accepted_cpp():
    source = CPP_MAIN % "int a, b; std::cin >> a >> b; std::cout << a + b << std::endl;"
    outcome = judge("cpp", source, ADD)
    assert outcome.verdict == ACCEPTED
    assert outcome.score == 100


@pytest.mark.parametrize("language,source", [
    ("python", "print(0)"),
    ("cpp", CPP_MAIN % "std::cout << 0;"),
])
def test_wrong_answer(language, source):
    outcome = judge(language, source, ADD)
    assert outcome.verdict == WRONG_ANSWER
    assert outcome.score == 0
    assert len(outcome.results) == 1


@pytest.mark.parametrize("language,source", [
    ("python", "while True: pass"),
    ("cpp", CPP_MAIN % "volatile int x = 0; while (true) x++;"),
])
def test_time_limit(language, source):
    assert judge(language, source, make_problem()).verdict == TIME_LIMIT


def test_time_limit_for_sleeping_program():
    outcome = judge("python", "import time\ntime.sleep(30)", make_problem(time_limit_ms=200))
    assert outcome.verdict == TIME_LIMIT
    assert outcome.results[0].time_ms < 200


@pytest.mark.parametrize("language,source", [
    ("python", "x = bytearray(512 * 1024 * 1024)"),
    ("python", "x = []\nwhile True: x.append(bytearray(1024 * 1024))"),
    ("cpp", CPP_MAIN % "char* p = new char[1024 * 1024 * 1024]; std::cout << (void*)p;"),
])
def test_memory_limit(language, source):
    assert judge(language, source, make_problem()).verdict == MEMORY_LIMIT


def test_memory_wins_over_time_when_both_are_exceeded():
    source = """
x = bytearray(100 * 1024 * 1024)
for i in range(0, len(x), 4096):
    x[i] = 1
while True:
    pass
"""
    assert judge("python", source, make_problem(memory_limit_mb=64)).verdict == MEMORY_LIMIT


def test_memory_over_limit_that_still_finishes():
    source = "x = bytearray(100 * 1024 * 1024)\nprint('ok')"
    assert judge("python", source, make_problem(memory_limit_mb=90)).verdict == MEMORY_LIMIT


def test_program_that_catches_memory_error_is_not_mle():
    source = "try:\n    x = bytearray(1 << 40)\nexcept MemoryError:\n    print('ok')"
    assert judge("python", source, make_problem()).verdict == ACCEPTED


@pytest.mark.parametrize("language,source", [
    ("python", "while True: print('x' * 1000)"),
    ("cpp", CPP_MAIN % "while (true) std::cout << 'x';"),
])
def test_output_limit(language, source):
    assert judge(language, source, make_problem()).verdict == OUTPUT_LIMIT


def test_output_limit_when_program_ignores_the_signal():
    source = """
#include <csignal>
#include <iostream>
int main() {
    std::signal(SIGXFSZ, SIG_IGN);
    while (true) {
        std::cout << 'x';
        std::cout.clear();
    }
}
"""
    assert judge("cpp", source, make_problem()).verdict == OUTPUT_LIMIT


def test_runtime_error_exit_code():
    outcome = judge("python", "raise SystemExit(5)", make_problem())
    assert outcome.verdict == RUNTIME_ERROR
    assert outcome.results[0].exit_code == 5
    assert outcome.results[0].signal is None


def test_runtime_error_exception():
    assert judge("python", "1 / 0", make_problem()).verdict == RUNTIME_ERROR


def test_runtime_error_signal():
    source = CPP_MAIN % "volatile int* p = nullptr; *p = 1;"
    outcome = judge("cpp", source, make_problem())
    assert outcome.verdict == RUNTIME_ERROR
    assert outcome.results[0].signal == 11
    assert outcome.results[0].exit_code is None


def test_abort_keeps_its_own_signal():
    source = "#include <cstdlib>\nint main() { std::abort(); }"
    outcome = judge("cpp", source, make_problem())
    assert outcome.verdict == RUNTIME_ERROR
    assert outcome.results[0].signal == 6


def test_compilation_error():
    outcome = judge("cpp", "int main( { nonsense", make_problem())
    assert outcome.verdict == COMPILATION_ERROR
    assert "error" in outcome.compile_output
    assert outcome.results == []


def test_compile_time_include_of_host_file_fails():
    outcome = judge("cpp", '#include "/etc/passwd"\nint main() {}', make_problem())
    assert outcome.verdict == COMPILATION_ERROR
    assert "root:" not in outcome.compile_output


def test_compile_error_output_is_capped():
    source = "\n".join(f"int f{i}() {{ return x; }}" for i in range(4000))
    outcome = judge("cpp", source, make_problem())
    assert outcome.verdict == COMPILATION_ERROR
    assert len(outcome.compile_output) <= 16 * 1024


def test_internal_error_when_sandbox_breaks(monkeypatch):
    def broken(*args, **kwargs):
        raise SandboxError("no namespaces here")

    monkeypatch.setattr("judge.judging.sandbox.run", broken)
    outcome = judge("python", "print(1)", make_problem())
    assert outcome.verdict == INTERNAL_ERROR
    assert outcome.score == 0


def test_stdin_is_fed_to_the_program():
    problem = make_problem([(100, [("hello world\n", "hello world\n")])], checker="exact")
    assert judge("python", "print(input())", problem).verdict == ACCEPTED
