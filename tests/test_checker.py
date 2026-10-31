from helpers import make_problem, needs_linux

from judge.checker import exact_match, float_match, token_match
from judge.judging import judge
from judge.models import ACCEPTED, INTERNAL_ERROR, WRONG_ANSWER


def test_exact_match():
    assert exact_match(b"1 2\n3\n", b"1 2\n3\n")
    assert exact_match(b"1 2", b"1 2\n")
    assert not exact_match(b"1  2\n", b"1 2\n")
    assert not exact_match(b"1 2 \n", b"1 2\n")
    assert not exact_match(b"1\n2\n", b"1 2\n")


def test_token_match_ignores_whitespace():
    assert token_match(b"1   2\n\n3  ", b"1 2 3\n")
    assert not token_match(b"1 2", b"1 2 3")
    assert not token_match(b"1 3 2", b"1 2 3")


def test_float_match():
    assert float_match(b"1.0000001 2", b"1 2.0000001", 1e-6)
    assert not float_match(b"1.1", b"1", 1e-6)
    assert not float_match(b"1 2", b"1", 1e-6)
    assert float_match(b"yes 1.0", b"yes 1", 1e-6)
    assert not float_match(b"no 1.0", b"yes 1", 1e-6)
    assert not float_match(b"nan", b"1", 1e-6)
    assert not float_match(b"inf", b"1", 1e-6)


CHECKER = """
import sys
output = open(sys.argv[2]).read().split()
answer = open(sys.argv[3]).read().split()
sys.exit(0 if sorted(output) == sorted(answer) else 1)
"""

CHECKER_CPP = """
#include <fstream>
#include <string>
int main(int argc, char** argv) {
    std::ifstream output(argv[2]), answer(argv[3]);
    std::string a, b;
    output >> a;
    answer >> b;
    return a == b ? 0 : 1;
}
"""


@needs_linux
def test_custom_checker_accepts_and_rejects():
    problem = make_problem(
        [(100, [("", "1 2 3\n")])],
        checker="custom",
        checker_language="python",
        checker_source=CHECKER,
    )
    assert judge("python", "print(3, 1, 2)", problem).verdict == ACCEPTED
    assert judge("python", "print(3, 1, 1)", problem).verdict == WRONG_ANSWER


@needs_linux
def test_custom_checker_in_cpp():
    problem = make_problem(
        [(100, [("", "same\n")])],
        checker="custom",
        checker_language="cpp",
        checker_source=CHECKER_CPP,
    )
    assert judge("python", "print('same')", problem).verdict == ACCEPTED
    assert judge("python", "print('different')", problem).verdict == WRONG_ANSWER


@needs_linux
def test_broken_checker_is_internal_error():
    problem = make_problem(checker="custom", checker_language="python", checker_source="raise SystemExit(7)")
    outcome = judge("python", "print('ok')", problem)
    assert outcome.verdict == INTERNAL_ERROR
    assert outcome.score == 0


@needs_linux
def test_checker_that_does_not_compile_is_internal_error():
    problem = make_problem(checker="custom", checker_language="cpp", checker_source="not c++")
    assert judge("python", "print('ok')", problem).verdict == INTERNAL_ERROR


@needs_linux
def test_float_checker_end_to_end():
    problem = make_problem([(100, [("", "3.14159\n")])], checker="float", float_tolerance=0.001)
    assert judge("python", "print(3.1415)", problem).verdict == ACCEPTED
    assert judge("python", "print(3.15)", problem).verdict == WRONG_ANSWER
