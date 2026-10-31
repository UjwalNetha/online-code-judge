import logging
import signal
import tempfile
from dataclasses import dataclass, field

from judge import compiler, config, sandbox
from judge.checker import CheckerError, make_checker
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
from judge.scoring import final_verdict, group_points

logger = logging.getLogger(__name__)

# allocation failures show up as a crash, so we look for what the runtime printed
OUT_OF_MEMORY_MARKERS = (b"MemoryError", b"std::bad_alloc")


@dataclass
class CaseOutcome:
    group_name: str
    verdict: str
    time_ms: int = 0
    memory_kb: int = 0
    exit_code: int | None = None
    signal: int | None = None


@dataclass
class Outcome:
    verdict: str
    score: int = 0
    time_ms: int | None = None
    memory_kb: int | None = None
    compile_output: str | None = None
    results: list[CaseOutcome] = field(default_factory=list)


def limits_for(problem):
    seconds = problem.time_limit_ms / 1000
    return sandbox.Limits(
        cpu_seconds=seconds,
        wall_seconds=seconds * 2 + 1,
        memory_mb=problem.memory_limit_mb,
        output_bytes=config.MAX_OUTPUT_BYTES,
    )


def classify(result, problem):
    """The verdict from how the run ended, or None if it finished cleanly."""
    if len(result.stdout) > config.MAX_OUTPUT_BYTES or result.signal == signal.SIGXFSZ:
        return OUTPUT_LIMIT
    failed = result.exit_code != 0
    out_of_memory = failed and any(marker in result.stderr for marker in OUT_OF_MEMORY_MARKERS)
    if result.peak_kb > problem.memory_limit_mb * 1024 or out_of_memory:
        return MEMORY_LIMIT
    if result.timed_out or result.cpu_ms > problem.time_limit_ms or result.signal == signal.SIGXCPU:
        return TIME_LIMIT
    # not a timeout, so this SIGKILL came from the kernel OOM killer
    if result.signal == signal.SIGKILL:
        return MEMORY_LIMIT
    if failed:
        return RUNTIME_ERROR
    return None


def run_case(program, code_dir, case, group_name, problem, check):
    input_data = case.input.encode()
    result = sandbox.run(
        program.command, limits_for(problem), code_dir=code_dir, stdin=input_data, env=program.env
    )
    verdict = classify(result, problem)
    if verdict is None:
        correct = check(input_data, result.stdout, case.expected_output.encode())
        verdict = ACCEPTED if correct else WRONG_ANSWER
    return CaseOutcome(
        group_name=group_name,
        verdict=verdict,
        time_ms=result.cpu_ms,
        memory_kb=result.peak_kb,
        exit_code=result.exit_code,
        signal=result.signal,
    )


def judge(language, source, problem):
    with tempfile.TemporaryDirectory(prefix="judge-") as code_dir, \
            tempfile.TemporaryDirectory(prefix="judge-checker-") as checker_dir:
        try:
            program = compiler.prepare(language, source, code_dir)
        except compiler.CompileError as error:
            return Outcome(verdict=COMPILATION_ERROR, compile_output=str(error))
        return run_tests(program, code_dir, problem, checker_dir)


def run_tests(program, code_dir, problem, checker_dir):
    results = []
    score = 0
    try:
        check = make_checker(problem, checker_dir)
        for group in problem.groups:
            verdicts = []
            for case in group.cases:
                outcome = run_case(program, code_dir, case, group.name, problem, check)
                results.append(outcome)
                verdicts.append(outcome.verdict)
                if outcome.verdict != ACCEPTED and problem.stop_on_first_fail:
                    return summary(results, score)
            score += group_points(group.score, verdicts, len(group.cases))
    except (sandbox.SandboxError, CheckerError) as error:
        logger.error("judging failed: %s", error)
        return summary(results + [CaseOutcome("", INTERNAL_ERROR)], 0)
    return summary(results, score)


def summary(results, score):
    return Outcome(
        verdict=final_verdict(r.verdict for r in results),
        score=score,
        time_ms=max((r.time_ms for r in results), default=0),
        memory_kb=max((r.memory_kb for r in results), default=0),
        results=results,
    )
