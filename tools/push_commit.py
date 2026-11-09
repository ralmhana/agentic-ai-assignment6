"""branches_push (push_commit.json): one commit to an existing branch. Assignment 5,
the course's tool: rename nothing here.

The mock remote runs no code: it records the message and the files. Branch
protection on main is the remote's rule, not your policy: a push to main reaches
the remote and is rejected there, and the write log keeps the attempt. Nothing
undoes a push."""

import json
import re

MAX_FILES, MAX_MESSAGE = 20, 200
ISSUE_BRANCH = re.compile(r"^repomind/issue-(\d+)$")


def check(args: dict) -> list[str]:
    problems = []
    branch = args.get("branch")
    if isinstance(branch, str) and not branch.strip():
        problems.append("branch: empty. Name the branch to commit to, such as repomind/issue-4192.")
    message = args.get("message")
    if isinstance(message, str) and (not message.strip() or len(message) > MAX_MESSAGE):
        problems.append(f"message: one line of 1 to {MAX_MESSAGE} characters.")
    files = args.get("files")
    if isinstance(files, list) and (not files or len(files) > MAX_FILES or not all(isinstance(f, str) and f.strip()
                                                                                    for f in files)):
        problems.append(f"files: 1 to {MAX_FILES} paths, relative to the repository root.")
    return problems


def describe(row: dict) -> str:
    return json.dumps({"commit": f"commit-{row['id']}", "branch": row["branch"], "files": row["files"]})


def run(ctx, branch, message, files, idempotency_key=None):
    from harness.tracker import RemoteRefused
    from tools import ToolError

    match = ISSUE_BRANCH.match(branch.strip())
    issue = int(match.group(1)) if match else getattr(ctx, "issue", None)
    try:
        row = ctx.tracker.push_commit(ctx.run_id, issue, branch.strip(), message.strip(), [f.strip() for f in files],
                                      key=idempotency_key)
    except RemoteRefused as exc:
        raise ToolError(f"the remote refused the push: {exc}.")
    return describe(row)
