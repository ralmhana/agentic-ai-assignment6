"""Assignment 5: messages from a user to a run, delivered between steps.

A person can tell a run something while it works: a boundary such as "stay out of
the database layer", or any other message. They send it here, and your loop drains
the inbox before every model call (checks/FORMATS.md, section 13.3):

    python -m harness.inbox send --issue 4192 "Keep the comment short."        # the next run on 4192
    python -m harness.inbox send --run <run_id> "BOUNDARY: deny path=src/db/**" # a run that is live
    python -m harness.inbox send --issue 4192 --before-call 4 "BOUNDARY: deny path=src/db/**"

    from harness.inbox import drain
    for message in drain(ctx):          # before every model call
        message["text"]                 # what the user wrote

A message goes to one run, once: the run named, or else the first run on the issue
named that drains it. With --before-call N it waits until the run is about to make
its Nth model call. drain() returns the messages due, oldest first, and marks them
delivered; a message is never delivered twice. Which of them are boundaries, and
what a boundary does, is your code's to decide: a boundary reads

    BOUNDARY: deny path=<glob>          (harness.formats.BOUNDARY matches it)

The inbox is two files in runs/: inbox.jsonl, every message sent, and
inbox.delivered.jsonl, every delivery.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import uuid
from pathlib import Path

from harness import ROOT
from harness.clock import now

_lock = threading.Lock()


def _paths(runs_dir: Path) -> tuple[Path, Path]:
    return runs_dir / "inbox.jsonl", runs_dir / "inbox.delivered.jsonl"


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def send(text: str, *, issue: int | None = None, run_id: str | None = None, before_call: int = 1,
         runs_dir: Path | None = None) -> dict:
    """Queue one message for a run, or for the next run on an issue."""
    if (issue is None) == (run_id is None):
        raise ValueError("send a message to one run (run_id) or to the next run on one issue (issue)")
    if not str(text).strip():
        raise ValueError("an empty message")
    sent, _ = _paths(Path(runs_dir or ROOT / "runs"))
    message = {"id": uuid.uuid4().hex[:10], "issue": issue, "run_id": run_id, "before_call": max(1, int(before_call)),
               "text": str(text), "sent_at": now()}
    with _lock:
        sent.parent.mkdir(parents=True, exist_ok=True)
        with sent.open("a") as fh:
            fh.write(json.dumps(message) + "\n")
    return message


def drain(ctx) -> list[dict]:
    """The messages due to this run before its next model call, oldest first, each
    delivered once. Call it before every model call."""
    runs_dir = Path(getattr(ctx, "runs_dir", None) or Path(ctx.root) / "runs")
    sent_path, delivered_path = _paths(runs_dir)
    next_call = int(getattr(ctx.client, "calls", 0)) + 1
    with _lock:
        sent = _read(sent_path)
        if not sent:
            return []
        delivered = {d["id"] for d in _read(delivered_path)}
        due = [m for m in sent if m["id"] not in delivered and next_call >= m.get("before_call", 1)
               and (m.get("run_id") == ctx.run_id if m.get("run_id") else m.get("issue") == ctx.issue_number)]
        if not due:
            return []
        at = now()
        with delivered_path.open("a") as fh:
            for m in due:
                fh.write(json.dumps({"id": m["id"], "run_id": ctx.run_id, "call": next_call, "at": at}) + "\n")
    return [{**m, "delivered_at": at, "call": next_call} for m in due]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("send", help="queue a message")
    s.add_argument("text")
    to = s.add_mutually_exclusive_group(required=True)
    to.add_argument("--issue", type=int, help="the next run on this issue")
    to.add_argument("--run", help="this run_id, while it is live")
    s.add_argument("--before-call", type=int, default=1, help="deliver it before the run's Nth model call")
    a = p.parse_args(argv)
    m = send(a.text, issue=a.issue, run_id=a.run, before_call=a.before_call)
    print(f"queued {m['id']} for " + (f"run {a.run}" if a.run else f"the next run on issue {a.issue}")
          + (f", before its model call {a.before_call}" if a.before_call > 1 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
