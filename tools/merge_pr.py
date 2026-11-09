"""pulls_merge (merge_pr.json): merge one of this run's open pull requests.
Assignment 5, the course's tool: rename nothing here. Nothing undoes a merge."""

import json
import re

PR = re.compile(r"^pr-(\d+)$")


def check(args: dict) -> list[str]:
    pr = args.get("pr")
    if isinstance(pr, str) and not PR.match(pr.strip()):
        return [f"pr: {pr!r} is not a pull request; write pr- and its number, such as pr-12."]
    return []


def describe(row: dict) -> str:
    return json.dumps({"pull_request": f"pr-{row['pr']}", "merged": True, "base": row.get("base", "develop")})


def run(ctx, pr, idempotency_key=None):
    from harness.tracker import RemoteRefused
    from tools import ToolError

    number = int(PR.match(pr.strip()).group(1))
    try:
        row = ctx.tracker.merge_pr(ctx.run_id, number, key=idempotency_key)
    except RemoteRefused as exc:
        raise ToolError(f"the remote refused the merge: {exc}.")
    return describe(row)
