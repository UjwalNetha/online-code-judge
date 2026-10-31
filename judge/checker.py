import tempfile
from pathlib import Path

from judge import compiler, sandbox

CHECKER_LIMITS = sandbox.Limits(cpu_seconds=10, wall_seconds=20, memory_mb=512, output_bytes=1024 * 1024)
WRONG_EXIT_CODE = 1


class CheckerError(Exception):
    pass


def exact_match(output, expected):
    return output.rstrip(b"\n") == expected.rstrip(b"\n")


def token_match(output, expected):
    return output.split() == expected.split()


def float_match(output, expected, tolerance):
    output, expected = output.split(), expected.split()
    if len(output) != len(expected):
        return False
    return all(_tokens_close(a, b, tolerance) for a, b in zip(output, expected))


def _tokens_close(a, b, tolerance):
    try:
        return abs(float(a) - float(b)) <= tolerance
    except ValueError:
        return a == b


class CustomChecker:
    """A checker program. It is called as: checker input output answer

    Exit code 0 means correct, 1 means wrong, anything else is a broken checker.
    """

    def __init__(self, language, source, code_dir):
        self.code_dir = code_dir
        try:
            self.program = compiler.prepare(language, source, code_dir)
        except compiler.CompileError as error:
            raise CheckerError(f"checker did not compile: {error}")

    def check(self, input_data, output, expected):
        with tempfile.TemporaryDirectory(prefix="checker-") as data_dir:
            data = Path(data_dir)
            (data / "input.txt").write_bytes(input_data)
            (data / "output.txt").write_bytes(output)
            (data / "answer.txt").write_bytes(expected)
            result = sandbox.run(
                self.program.command + ["/data/input.txt", "/data/output.txt", "/data/answer.txt"],
                CHECKER_LIMITS,
                code_dir=self.code_dir,
                data_dir=data,
                env=self.program.env,
            )
        if result.exit_code == 0:
            return True
        if result.exit_code == WRONG_EXIT_CODE:
            return False
        raise CheckerError(f"checker failed: exit {result.exit_code}, signal {result.signal}")


def make_checker(problem, code_dir):
    """Returns a function (input, output, expected) -> bool for this problem."""
    if problem.checker == "exact":
        return lambda _, output, expected: exact_match(output, expected)
    if problem.checker == "token":
        return lambda _, output, expected: token_match(output, expected)
    if problem.checker == "float":
        return lambda _, output, expected: float_match(output, expected, problem.float_tolerance)
    if problem.checker == "custom":
        return CustomChecker(problem.checker_language, problem.checker_source, code_dir).check
    raise ValueError(f"unknown checker: {problem.checker}")
