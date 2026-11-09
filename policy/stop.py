"""The stop button's flag, and logs/stops.jsonl. Assignment 5's working solution.
It ships in Assignment 6's starter as RepoMind's own.

bin/stop writes `requested`; the hook refuses every later call of the run and writes
`effective` at the first refusal; the way, seeing the refusal, saves a checkpoint and
ends the run `stopped`; `python run.py --resume <run_id>` lifts the stop (`lifted`)
and replays from the checkpoint with Lecture 3's keys, so a write the stop found
finished is found, not repeated.

The stop takes effect at the next call: the call already running finishes, which is
the condition this stop meets only partly (Lecture 5, slide 40, "fast").
"""

from __future__ import annotations

import json
import threading

from harness import ROOT
from harness.clock import now

STOPS = ROOT / "logs" / "stops.jsonl"
_lock = threading.Lock()


def _lines() -> list[dict]:
    if not STOPS.exists():
        return []
    return [json.loads(x) for x in STOPS.read_text().splitlines() if x.strip()]


def _write(line: dict) -> None:
    with _lock:
        STOPS.parent.mkdir(parents=True, exist_ok=True)
        with STOPS.open("a") as fh:
            fh.write(json.dumps(line) + "\n")


def state(run_id: str) -> str | None:
    """The run's last stop event: requested, effective, lifted, or None."""
    events = [x["event"] for x in _lines() if x.get("run_id") == run_id]
    return events[-1] if events else None


def requested(run_id: str) -> bool:
    return state(run_id) in ("requested", "effective")


def request(run_id: str) -> dict:
    line = {"run_id": run_id, "event": "requested", "at": now()}
    _write(line)
    return line


def effective(run_id: str, action: str) -> None:
    """The first refusal after a request: when the stop took effect."""
    if state(run_id) == "requested":
        _write({"run_id": run_id, "event": "effective", "at": now(), "action": action})


def lift(run_id: str) -> bool:
    if not requested(run_id):
        return False
    _write({"run_id": run_id, "event": "lifted", "at": now()})
    return True
