from judge.models import ACCEPTED, COMPILATION_ERROR, INTERNAL_ERROR

NOT_COUNTED = (COMPILATION_ERROR, INTERNAL_ERROR, None)


def build_leaderboard(contest, submissions):
    """Rank users from their judged submissions, which must be sorted by time.

    In ICPC style a problem is worth 1 once solved. In score style it is worth
    the best score. The penalty for a problem is the minutes taken to reach that
    value plus penalty_minutes for each wrong attempt before it.
    """
    entries = {}
    for submission in submissions:
        if submission.verdict in NOT_COUNTED:
            continue
        user = submission.user.username
        problems = entries.setdefault(user, {})
        problem = problems.setdefault(
            submission.problem_id, {"value": 0, "wrong": 0, "wrong_before_best": 0, "penalty": 0}
        )

        if contest.style == "icpc":
            value = 1 if submission.verdict == ACCEPTED else 0
        else:
            value = submission.score

        if value > problem["value"]:
            minutes = int((submission.created_at - contest.start_time).total_seconds() // 60)
            problem["value"] = value
            problem["wrong_before_best"] = problem["wrong"]
            problem["penalty"] = minutes + problem["wrong"] * contest.penalty_minutes
        elif submission.verdict != ACCEPTED:
            problem["wrong"] += 1

    rows = [
        {
            "username": user,
            "total": sum(p["value"] for p in problems.values()),
            "penalty": sum(p["penalty"] for p in problems.values()),
            "problems": {
                problem_id: {
                    "value": p["value"],
                    "wrong_attempts": p["wrong_before_best"] if p["value"] else p["wrong"],
                    "penalty": p["penalty"],
                }
                for problem_id, p in problems.items()
            },
        }
        for user, problems in entries.items()
    ]
    rows.sort(key=lambda row: (-row["total"], row["penalty"], row["username"]))

    previous = None
    for position, row in enumerate(rows, start=1):
        tied = previous and (previous["total"], previous["penalty"]) == (row["total"], row["penalty"])
        row["rank"] = previous["rank"] if tied else position
        previous = row
    return rows
