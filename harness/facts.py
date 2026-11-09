"""Assignment 5: the circumstance of one call, as facts the harness computed.

A policy places an action class: a tool together with its circumstance (Lecture 5,
slide 51). Your hook decides the class; these are the facts it decides from, the
same fields for a live call (Tracker.facts) and for a line of the recorded day,
fixtures/rollup_2026-08-04.jsonl (checks/FORMATS.md, section 13.2). So one
function of yours can place both, and bin/replay_policy runs your hook's own code.

    issue                         the issue the call is about, or None
    issue_opened_by_agent         True when RepoMind opened that issue
    minutes_since_human_comment   minutes since a person last commented on its thread, or None
    label                         the label apply_label adds, or None
    branch                        the branch open_pr opens, push_commit pushes to, or merge_pr merges
    branch_protected              True when the call writes to a protected branch (main):
                                  push_commit's branch, merge_pr's base; None when no branch
    base                          the branch a pull request goes into, or None
    target_created_by_agent       True when RepoMind made what the call changes: an issue it
                                  opened, the branch of a pull request it opened, its own
                                  pull request; None for a read
    paths                         every file path in the arguments: read_file's path,
                                  search's path filter, push_commit's files

None of it comes from the model, and none of it is shown to the model.
"""

from __future__ import annotations

FIELDS = ("issue", "issue_opened_by_agent", "minutes_since_human_comment", "label", "branch", "branch_protected",
          "base", "target_created_by_agent", "paths")
READS = ("read_issue", "search_repo", "read_file", "run_tests")


def _arg(args: dict, role: str, name: str):
    from harness.roles import arg
    try:
        return args.get(arg(role, name))
    except (KeyError, OSError, ValueError):
        return None


def _issue(value) -> int | None:
    text = str(value or "").strip().lower().removeprefix("issue-").removeprefix("#")
    return int(text) if text.isdigit() else None


def _pr(value) -> int | None:
    text = str(value or "").strip().lower().removeprefix("pr-").removeprefix("#")
    return int(text) if text.isdigit() else None


def facts(tracker, run_id: str, action: str, args: dict, issue: int | None = None) -> dict:
    from harness.formats import ACTIONS
    from harness.tracker import BASE, PROTECTED, IssueNotFound

    if action not in ACTIONS:
        raise ValueError(f"no action {action!r}: one of {', '.join(ACTIONS)}")
    role = ACTIONS[action]
    args = args or {}
    out = dict.fromkeys(FIELDS)
    out["paths"] = []
    number = _issue(_arg(args, role, "number")) if role in ("read_issue", "comment", "open_pr", "apply_label",
                                                             "close_issue") else None
    out["issue"] = number if number is not None else issue
    if out["issue"] is not None:
        try:
            meta = tracker.metadata(out["issue"])
            out["issue_opened_by_agent"] = meta["opened_by_agent"]
            out["minutes_since_human_comment"] = meta["minutes_since_human_comment"]
        except IssueNotFound:
            pass
    if role in ("comment", "apply_label", "close_issue"):
        out["target_created_by_agent"] = out["issue_opened_by_agent"]
    if role == "apply_label":
        out["label"] = _arg(args, role, "label")
    if role == "open_pr":
        out["branch"] = _arg(args, role, "branch")
        out["base"] = BASE
        out["branch_protected"] = out["branch"] in PROTECTED if out["branch"] else None
        out["target_created_by_agent"] = True        # a new branch, which the pull request creates
    if role == "push_commit":
        branch = _arg(args, role, "branch")
        out["branch"] = branch
        out["branch_protected"] = branch in PROTECTED if branch else None
        mine = branch in [p["branch"] for p in tracker.prs(run_id, state=None)] if branch else False
        out["target_created_by_agent"] = bool(mine)
        files = _arg(args, role, "files")
        out["paths"] = [str(f) for f in files] if isinstance(files, list) else []
    if role == "merge_pr":
        found = tracker.pr(run_id, _pr(_arg(args, role, "pr"))) if _pr(_arg(args, role, "pr")) is not None else None
        out["target_created_by_agent"] = found is not None
        if found is not None:
            out["branch"], out["base"] = found["branch"], found["base"]
            out["issue"] = found["issue"]
            out["branch_protected"] = found["base"] in PROTECTED
    if role == "read_file":
        path = _arg(args, role, "path")
        out["paths"] = [str(path)] if path else []
    if role == "search":
        path = _arg(args, role, "path")
        out["paths"] = [str(path)] if path else []
    return out
