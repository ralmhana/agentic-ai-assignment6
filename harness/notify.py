"""Assignment 5: the notification sink, logs/notifications.jsonl.

A stop button works only if someone knows there is a run to stop (Lecture 5,
slide 40). The sink stands in for wherever your team would be told: a chat
channel, a pager, a dashboard. Your code sends; the sink writes one line per
notification, with the time (harness.clock), and prints it to the terminal
(checks/FORMATS.md, section 13.5):

    from harness.notify import notify
    notify("live", ctx.run_id, f"RepoMind is running on issue {ctx.issue_number}; stop it with bin/stop {ctx.run_id}")

`kind` is a plain word of your choosing; the checker reads the "live" ones. Extra
keyword arguments go on the line as fields.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from harness import ROOT
from harness.clock import now

_lock = threading.Lock()


def notify(kind: str, run_id: str, text: str, *, root: Path | None = None, quiet: bool = False, **fields) -> dict:
    if not isinstance(kind, str) or not kind.isidentifier():
        raise ValueError(f"a notification's kind is a plain word such as 'live', not {kind!r}")
    clash = {"at", "kind", "run_id", "text"} & set(fields)
    if clash:
        raise ValueError(f"fields may not be named {sorted(clash)}")
    line = {"at": now(), "kind": kind, "run_id": run_id, "text": str(text), **fields}
    path = Path(root or ROOT) / "logs" / "notifications.jsonl"
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(line, default=str) + "\n")
    if not quiet:
        print(f"[notify {kind}] {run_id}: {text}", file=sys.stderr, flush=True)
    return line


def read(root: Path | None = None) -> list[dict]:
    path = Path(root or ROOT) / "logs" / "notifications.jsonl"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
