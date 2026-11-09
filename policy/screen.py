"""What bin/review shows a reviewer. Assignment 5's working solution.

Information, not a recommendation (Lecture 5, slides 27 and 30). First the dry run:
the change exactly as it would be applied, nothing applied yet (slide 19). Then
facts the harness computed, which the model never asserted: who opened the issue,
when a person last spoke on it, whether RepoMind made what it is changing, this run's
tests, the files touched. Then the thread, read from the tracker: what the people
on it last said, which a comment on an active thread answers. The model's own words
are never on this screen: the system under review does not write the case for its
own approval (slide 27).
"""

from __future__ import annotations

import json
import textwrap

from harness.roles import arg
from harness.tracker import Tracker


def _quoted(text: str) -> str:
    return "\n".join("    │ " + line for line in str(text or "").splitlines() or [""])


def _arg(args: dict, role: str, name: str):
    try:
        return args.get(arg(role, name))
    except (KeyError, ValueError, OSError):
        return None


def dry_run(action: str, args: dict, facts: dict) -> str:
    if action == "post_comment":
        return f"Posts this comment on issue-{facts.get('issue')}, exactly as it will appear:\n" + _quoted(
            _arg(args, "comment", "body"))
    if action == "open_pr":
        return (f"Opens a draft pull request from {_arg(args, 'open_pr', 'branch')} into {facts.get('base')}.\n"
                f"  title: {_arg(args, 'open_pr', 'title')}\n  body:\n" + _quoted(_arg(args, "open_pr", "body")))
    if action == "push_commit":
        files = _arg(args, "push_commit", "files") or []
        return (f"Pushes one commit to {facts.get('branch')}"
                f"{' (PROTECTED)' if facts.get('branch_protected') else ''}.\n"
                f"  message: {_arg(args, 'push_commit', 'message')}\n  files: {', '.join(files) or 'none'}")
    if action == "merge_pr":
        return f"Merges {_arg(args, 'merge_pr', 'pr')} ({facts.get('branch')}) into {facts.get('base')}."
    return f"{action} with {json.dumps(args)}"


def facts_block(request: dict) -> str:
    f = request.get("facts") or {}
    minutes = f.get("minutes_since_human_comment")
    rows = [
        ("issue opened by", "RepoMind itself" if f.get("issue_opened_by_agent") else "a person"),
        ("last human comment", "none on the thread" if minutes is None else f"{minutes:g} minutes ago"),
        ("made by RepoMind", {True: "yes: RepoMind created what this changes", False: "no: it was already there",
                              None: "n/a"}[f.get("target_created_by_agent")]),
        ("tests in this run", request.get("tests") or "not run in this run"),
        ("files touched", ", ".join(f.get("paths") or []) or "none named"),
    ]
    return "\n".join(f"  {k:<20} {v}" for k, v in rows)


def thread(number) -> str:
    """The issue's title and the last two comments people wrote on it (FORMATS.md, 12.7)."""
    try:
        issue = Tracker().issue(int(number))
    except Exception:
        return "  (the issue could not be read)"
    lines = [f"  title: {issue.get('title')}"]
    said = (issue.get("discussion") or [])[-2:]
    for c in said:
        role = f" ({c['role']})" if c.get("role") else ""
        lines += [f"  {c.get('author')}{role} · {c.get('date')}", _quoted(textwrap.shorten(c.get("body") or "", 400))]
    if not said:
        lines.append("  nobody has commented")
    return "\n".join(lines)


def render(request: dict) -> str:
    action = request.get("action")
    if request.get("kind") == "escalation":
        p = request.get("packet") or {}
        return textwrap.dedent(f"""\
            ESCALATION · {request.get('action_class')} · issue {request.get('issue')}
            The run stopped before: {p.get('attempted')}
            Why it stopped (the harness saw this): {p.get('why_stopped')}
            What it needs from you: {p.get('needs_from_human')}
            Nothing proceeds until you answer; no answer and it stays held.""")
    return "\n".join([
        f"APPROVAL · {request.get('action_class')} · issue {(request.get('facts') or {}).get('issue')}",
        "",
        "What it will do (a dry run; nothing has been applied):",
        dry_run(action, request.get("args") or {}, request.get("facts") or {}),
        "",
        "Facts the harness computed (none of this is the agent's claim):",
        facts_block(request),
        "",
        "The thread, as people wrote it:",
        thread((request.get("facts") or {}).get("issue")),
        "",
        "The agent's reasons are not shown here: check the change, not its case for itself.",
    ])
