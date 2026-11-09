"""A boundary a user states mid-run, kept as a rule the hook reads. Assignment 5's
working solution.

The loop drains the inbox before every model call (ways/planned.py). A message that
reads `BOUNDARY: deny path=<glob>` is parsed here, by the harness and never by the
model, and written to policy/rules.jsonl for its run; every other message goes on to
the model. A boundary held only as text in the context lasts as long as the context
does: a compaction can drop the message, and the limit with it (Lecture 5, slide 17).
A rule in this file outlives every compaction.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from harness import ROOT
from harness.clock import now
from harness.formats import BOUNDARY

RULES = ROOT / "policy" / "rules.jsonl"
_lock = threading.Lock()


def parse(text: str) -> str | None:
    """The glob a boundary message denies, or None for any other message."""
    found = BOUNDARY.match(str(text or ""))
    return found.group(1) if found else None


def record(run_id: str, message: dict) -> dict | None:
    """Write a boundary message to the rule file; None for a message that is not one."""
    glob = parse(message.get("text"))
    if glob is None:
        return None
    rule = {"run_id": run_id, "effect": "deny", "path": glob,
            "stated_at": message.get("delivered_at") or now(), "message": message.get("text")}
    with _lock:
        RULES.parent.mkdir(parents=True, exist_ok=True)
        with RULES.open("a") as fh:
            fh.write(json.dumps(rule) + "\n")
    return rule


def rules(run_id: str) -> list[dict]:
    if not RULES.exists():
        return []
    out = []
    for line in RULES.read_text().splitlines():
        if line.strip():
            rule = json.loads(line)
            if rule.get("run_id") == run_id and rule.get("effect") == "deny":
                out.append(rule)
    return out


def matches(path: str, glob: str) -> bool:
    """A path against a glob: ** spans directories, * stays within one."""
    pattern = ""
    i = 0
    while i < len(glob):
        if glob.startswith("**", i):
            pattern += ".*"
            i += 2
            if glob.startswith("/", i):
                pattern += "/?"
                i += 1
        elif glob[i] == "*":
            pattern += "[^/]*"
            i += 1
        elif glob[i] == "?":
            pattern += "[^/]"
            i += 1
        else:
            pattern += re.escape(glob[i])
            i += 1
    return re.fullmatch(pattern, str(path).strip().lstrip("./")) is not None


def crossed(run_id: str, paths: list[str]) -> dict | None:
    """The first of this run's rules a path crosses, or None."""
    for rule in rules(run_id):
        if any(matches(p, rule["path"]) for p in paths):
            return rule
    return None
