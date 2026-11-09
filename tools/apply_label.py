"""issues_label (apply_label.json): one label on one issue. Assignment 5, the
course's tool: rename nothing here.

`idempotency_key` is never in the definition: the registry passes it. The
compensating endpoint, Tracker.remove_label, is not a tool."""

import json
import re

LABEL = re.compile(r"^[a-z][a-z0-9/_-]{0,39}$")


def check(args: dict) -> list[str]:
    from tools import issue_problem
    problems = []
    problem = issue_problem(args.get("issue"))
    if problem:
        problems.append(problem)
    label = args.get("label")
    if isinstance(label, str) and not LABEL.match(label.strip()):
        problems.append(f"label: {label!r}; a label is at most 40 characters of lower-case letters, digits, "
                        "- _ and /, such as bug.")
    return problems


def describe(row: dict) -> str:
    return json.dumps({"label": row["label"], "issue": f"issue-{row['issue']}", "applied": True})


def run(ctx, issue, label, idempotency_key=None):
    from harness.tracker import IssueNotFound
    from tools import ToolError, issue_number

    try:
        row = ctx.tracker.apply_label(ctx.run_id, issue_number(issue), label.strip(), key=idempotency_key)
    except IssueNotFound:
        raise ToolError(f"issue: {issue} is not in the tracker; label the issue you read.")
    return describe(row)
