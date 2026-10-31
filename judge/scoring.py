from judge.models import ACCEPTED


def group_points(score, verdicts, total_cases):
    """A group pays out only if every one of its tests ran and was accepted."""
    if len(verdicts) == total_cases and all(v == ACCEPTED for v in verdicts):
        return score
    return 0


def final_verdict(verdicts):
    for verdict in verdicts:
        if verdict != ACCEPTED:
            return verdict
    return ACCEPTED
