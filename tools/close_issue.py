"""issues_close (close_issue.json): close one issue with a reason. Assignment 5,
the course's tool: rename nothing here.

The compensating endpoint, Tracker.reopen_issue, is not a tool."""

import json

MAX_REASON = 300


def check(args: dict) -> list[str]:
    from tools import issue_problem
    problems = []
    problem = issue_problem(args.get("issue"))
    if problem:
        problems.append(problem)
    reason = args.get("reason")
    if isinstance(reason, str) and not reason.strip():
        problems.append("reason: empty. Say in one sentence why the issue is closed.")
    elif isinstance(reason, str) and len(reason) > MAX_REASON:
        problems.append(f"reason: {len(reason):,} characters, over the cap of {MAX_REASON}. Shorten it.")
    return problems


def describe(row: dict) -> str:
    return json.dumps({"issue": f"issue-{row['issue']}", "closed": True, "reason": row["reason"]})


def run(ctx, issue, reason, idempotency_key=None):
    from harness.tracker import IssueNotFound
    from tools import ToolError, issue_number

    try:
        row = ctx.tracker.close_issue(ctx.run_id, issue_number(issue), reason.strip(), key=idempotency_key)
    except IssueNotFound:
        raise ToolError(f"issue: {issue} is not in the tracker.")
    return describe(row)
