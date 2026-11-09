"""The autonomy policy, enforced before every call. Assignment 5's working solution.
It ships in Assignment 6's starter as RepoMind's own.

tools/__init__.py's registry runs PolicyHook before every tool call (Assignment 3's
hook point), outside the model: the model never sees policy/autonomy.yaml and cannot
argue with it. The hook fails closed: when it raises, the registry denies the call.

For each call, in this order (checks/FORMATS.md, section 13):
  1. A stopped run (bin/stop): refuse, and on the first refusal write the stop's
     `effective` line.
  2. Place the call: classify(action, facts) gives its class and column, from the
     facts the harness computed (Tracker.facts), never from the model.
  3. Prohibited: refuse, in every reviewer mode; no answer can turn it into a yes
     (Lecture 5, slide 16: deny rules hold in every mode).
  4. A boundary the user stated (policy/rules.jsonl, written by policy/boundary.py):
     refuse a call whose paths cross it.
  5. Part D: a comment without the disclosure line is refused.
  6. Requires approval: ask the reviewer (harness/reviewer.py) with the screen's
     request, and log the decision. Approved, the call runs; declined, it is
     refused; no answer before the timeout, it is refused and the run holds.
  7. Independent: the call runs, and nobody is asked.

Every refusal is a line in logs/hook.jsonl; every decision a line in
logs/approvals.jsonl. bin/replay_policy places the recorded day with classify(),
this file's own code.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import yaml

from harness import ROOT
from harness.clock import now
from harness.formats import ACTIONS, COLUMNS
from harness.reviewer import Reviewer
from harness.roles import action_of, arg

POLICY = ROOT / "policy" / "autonomy.yaml"
HUMAN_ACTIVE_MINUTES = 60
_lock = threading.Lock()
_held: set[str] = set()          # runs whose gated call went unanswered: the way ends them held


def policy(path: Path | None = None) -> dict:
    return yaml.safe_load(Path(path or POLICY).read_text())


def classify(action: str, facts: dict, placed: dict | None = None) -> tuple[str, str]:
    """(action class, column) for one call: the circumstance from its facts, then the
    column the policy gives that class. A class the policy does not place is
    prohibited: fail closed."""
    facts = facts or {}
    if action == "post_comment":
        minutes = facts.get("minutes_since_human_comment")
        if minutes is not None and minutes <= HUMAN_ACTIVE_MINUTES:
            klass = "post_comment/human_active"
        elif facts.get("issue_opened_by_agent"):
            klass = "post_comment/agent_opened"
        else:
            klass = "post_comment/quiet"
    elif action == "push_commit":
        klass = "push_commit/protected" if facts.get("branch_protected") else "push_commit/unprotected"
    else:
        klass = action
    placed = placed or policy()
    column = next((c for c in COLUMNS if klass in (placed.get(c) or [])), "prohibited")
    return klass, column


def disclosure(placed: dict | None = None) -> str:
    return str((placed or policy()).get("disclosure") or "").strip()


def discloses(body: str, line: str) -> bool:
    """The disclosure line, after the comment's first two lines (label and file)."""
    rest = str(body or "").splitlines()[2:]
    return bool(line) and any(r.strip() == line for r in rest)


def held(run_id: str) -> bool:
    with _lock:
        return run_id in _held


def hold(run_id: str) -> None:
    with _lock:
        _held.add(run_id)


def log(name: str, line: dict) -> None:
    path = ROOT / "logs" / name
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(line, default=str) + "\n")


def last_tests(ctx) -> str:
    """This run's last test result, from its call record, for the screen: a fact the harness has."""
    path = getattr(ctx.calls, "path", None)
    if not path or not Path(path).exists():
        return "not run in this run"
    from harness.roles import tool_for
    found = "not run in this run"
    for line in Path(path).read_text().splitlines():
        call = json.loads(line)
        if call.get("tool") == tool_for("run_tests") and call.get("outcome") == "ok":
            try:
                result = json.loads(call.get("result") or "{}")
                found = ("passed" if result.get("passed") else f"FAILED: {', '.join(result.get('failed') or [])}")
            except ValueError:
                found = "a result that could not be read"
    return found


class PolicyHook:
    """hook(name, args) -> None to allow, or a reason to refuse (tools/__init__.py, step 3)."""

    __name__ = "policy"

    def __init__(self, ctx, reviewer: Reviewer | None = None):
        self.ctx = ctx
        self.placed = policy()
        self.reviewer = reviewer or Reviewer.from_env()

    def __call__(self, name: str, args: dict) -> str | None:
        from policy import boundary, stop

        ctx = self.ctx
        action = action_of(name)
        if action is None or action not in ACTIONS:
            return self.refuse(None, None, None, "unknown", args, f"{name} plays no action the policy places")
        facts = ctx.tracker.facts(ctx.run_id, action, args, ctx.issue)
        klass, column = classify(action, facts, self.placed)
        if stop.requested(ctx.run_id):
            stop.effective(ctx.run_id, action)
            return self.refuse(action, klass, None, "stopped", args, f"run {ctx.run_id} was stopped (bin/stop)")
        if column == "prohibited":
            return self.refuse(action, klass, column, "prohibited", args,
                               f"{klass} is prohibited by RepoMind's autonomy policy; no reviewer can approve it")
        crossed = boundary.crossed(ctx.run_id, facts.get("paths") or [])
        if crossed:
            return self.refuse(action, klass, None, "boundary", args,
                               f"{crossed['path']} is outside this run's boundary, stated as: {crossed['message']}")
        line = disclosure(self.placed)
        if action == "post_comment" and not discloses(args.get(arg("comment", "body")), line):
            return self.refuse(action, klass, None, "disclosure", args,
                               "a comment must say, after its first two lines, that an automated agent wrote it: "
                               f"add the line {line!r}")
        if column == "requires_approval":
            return self.ask(action, klass, facts, args)
        return None

    def ask(self, action: str, klass: str, facts: dict, args: dict) -> str | None:
        ctx = self.ctx
        request = {"run_id": ctx.run_id, "action": action, "action_class": klass, "args": args, "facts": facts,
                   "kind": "approval", "issue": ctx.issue, "tests": last_tests(ctx)}
        timeout = float((self.placed.get("timeouts") or {}).get("approval_s", 1800))
        from policy import stop
        answer = self.reviewer.ask(request, timeout, until=lambda: stop.requested(ctx.run_id))
        log("approvals.jsonl", {"at": now(), "run_id": ctx.run_id, "action": action, "action_class": klass,
                                "facts": facts, "kind": "approval",
                                "decision": answer["decision"] if answer else "none",
                                "seconds": answer["seconds"] if answer else None,
                                "reviewer": answer["reviewer"] if answer else self.reviewer.kind,
                                "mode": self.reviewer.mode})
        if answer is None and stop.requested(ctx.run_id):      # a stop withdrew the request
            stop.effective(ctx.run_id, action)
            return self.refuse(action, klass, None, "stopped", args, f"run {ctx.run_id} was stopped (bin/stop)")
        if answer is None:
            hold(ctx.run_id)
            return self.refuse(action, klass, "requires_approval", "no_answer", args,
                               f"{klass} needs a reviewer's approval, and none came within {timeout:.0f} s; the run holds")
        if answer["decision"] != "approve":
            return self.refuse(action, klass, "requires_approval", "declined", args,
                               f"the reviewer declined this {klass}")
        return None

    def refuse(self, action, klass, column, reason: str, args: dict, why: str) -> str:
        log("hook.jsonl", {"at": now(), "run_id": self.ctx.run_id, "action": action, "action_class": klass,
                           "column": column, "reason": reason, "args": args})
        return why
