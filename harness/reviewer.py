"""Assignment 5: the reviewer, who answers when your policy asks.

A call your policy gates, and an escalation, wait for an answer from the reviewer
set by the REVIEWER variable on each run (checks/FORMATS.md, section 13.4):

    REVIEWER=scripted:approve-all      every ask is approved at once
    REVIEWER=scripted:deny-all         every ask is denied at once
    REVIEWER=scripted:none             nobody answers: ask() returns None at once, as if
                                       your timeout had passed (the default, when unset)
    REVIEWER=scripted:replay:FILE      the decisions in FILE, a JSON-lines file, in order:
                                       each ask takes the first unused line whose
                                       action_class matches, or else whose action, or
                                       else whose kind, or a line whose action_class is
                                       "*"; a line with "repeat": true is never used up;
                                       none left, None
    REVIEWER=human                     you, at bin/review, in a second terminal

Bulk runs never wait for a person: every run uses a scripted reviewer except where
the assignment asks you to time yourself.

Your hook asks; the reviewer answers:

    from harness.reviewer import Reviewer
    reviewer = Reviewer.from_env()
    answer = reviewer.ask({"run_id": ..., "action": "post_comment",
                           "action_class": "post_comment/human_active",
                           "args": {...}, "facts": {...}}, timeout_s=1800)
    if answer is None:                     # no answer before the timeout: never a yes
        ...
    elif answer["decision"] == "approve":
        ...

`until`, a function of no arguments, ends a wait early when it returns True: the
request is withdrawn from bin/review's queue and ask() returns None. A stop that
arrives while a person is deciding uses it.

A request needs run_id, action (Lecture 5's name), action_class and args; it may
carry facts, kind ("approval", the default, or "escalation"), packet (an
escalation's), and anything else your screen shows. An answer is a dict:
decision ("approve" or "deny"), mode (the REVIEWER value), reviewer ("human" or
"scripted"), request_id, shown_at and decided_at (harness.clock times) and
seconds, from when bin/review showed it to the decision (0 for a script).

Every ask, and what came back, is also written by the harness to
logs/reviewer.jsonl. That log is the harness's: your own decisions log,
logs/approvals.jsonl, is yours to write (Part B).

In human mode, ask() puts the request in logs/review/pending/ and waits there,
polling, until bin/review writes the answer to logs/review/decided/, or until the
timeout, when the request is withdrawn and ask() returns None.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from harness import ROOT
from harness.clock import now, seconds_between

DEFAULT = "scripted:none"
SCRIPTED = ("scripted:approve-all", "scripted:deny-all", "scripted:none")
REQUIRED = ("run_id", "action", "action_class", "args")
KINDS = ("approval", "escalation")
POLL_S = 0.25
_lock = threading.Lock()
_used: dict[str, set[int]] = {}      # replay files: the line numbers already answered, in this process


class ReviewerError(ValueError):
    pass


def mode_from_env() -> str:
    mode = (os.environ.get("REVIEWER") or "").strip() or DEFAULT
    if mode in SCRIPTED or mode == "human" or mode.startswith("scripted:replay:"):
        return mode
    raise SystemExit(f"REVIEWER={mode!r}: one of {', '.join(SCRIPTED)}, scripted:replay:FILE, or human")


class Reviewer:
    def __init__(self, mode: str | None = None, root: Path | None = None):
        self.mode = mode or mode_from_env()
        self.root = Path(root or ROOT)
        self.logs = self.root / "logs"

    @classmethod
    def from_env(cls, root: Path | None = None) -> "Reviewer":
        return cls(mode_from_env(), root)

    @property
    def kind(self) -> str:
        """'human' or 'scripted': what your approvals log records as the reviewer."""
        return "human" if self.mode == "human" else "scripted"

    # -- the one entry point ---------------------------------------------------------------
    def ask(self, request: dict, timeout_s: float, until=None) -> dict | None:
        missing = [k for k in REQUIRED if k not in (request or {})]
        if missing:
            raise ReviewerError(f"a request needs {missing} (checks/FORMATS.md, section 13.4)")
        if request.get("kind", "approval") not in KINDS:
            raise ReviewerError(f"kind is one of {KINDS}, not {request.get('kind')!r}")
        request_id = request.get("request_id") or uuid.uuid4().hex[:12]
        asked_at = now()
        if self.mode == "human":
            answer = self._human({**request, "request_id": request_id}, asked_at, float(timeout_s), until)
        elif self.mode == "scripted:none":
            answer = None
        elif self.mode.startswith("scripted:replay:"):
            decision = self._replayed(request)
            answer = None if decision is None else self._scripted(request_id, decision)
        else:
            answer = self._scripted(request_id, "approve" if self.mode == "scripted:approve-all" else "deny")
        self._log(request, request_id, asked_at, answer)
        return answer

    def _scripted(self, request_id: str, decision: str) -> dict:
        at = now()
        return {"request_id": request_id, "decision": decision, "mode": self.mode, "reviewer": "scripted",
                "shown_at": at, "decided_at": at, "seconds": 0.0}

    def _replayed(self, request: dict) -> str | None:
        path = Path(self.mode[len("scripted:replay:"):])
        path = path if path.is_absolute() else self.root / path
        lines = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        asked = {**request, "kind": request.get("kind", "approval")}
        with _lock:
            used = _used.setdefault(str(path), set())
            for match in ("action_class", "action", "kind", "*"):
                for i, line in enumerate(lines):
                    if i in used or line.get("decision") not in ("approve", "deny", "none"):
                        continue
                    if match == "*":
                        hit = line.get("action_class") == "*"
                    elif match == "kind":
                        hit = "action_class" not in line and "action" not in line and line.get("kind") == asked["kind"]
                    else:
                        hit = line.get(match) not in (None, "*") and line.get(match) == asked.get(match)
                    if hit:
                        if not line.get("repeat"):
                            used.add(i)
                        return None if line["decision"] == "none" else line["decision"]
        return None

    # -- human mode: the queue bin/review reads ------------------------------------------------
    def _dirs(self) -> tuple[Path, Path, Path]:
        base = self.logs / "review"
        dirs = (base / "pending", base / "decided", base / "done")
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
        return dirs

    def _human(self, request: dict, asked_at: str, timeout_s: float, until=None) -> dict | None:
        pending, decided, done = self._dirs()
        rid = request["request_id"]
        (pending / f"{rid}.json").write_text(json.dumps({**request, "asked_at": asked_at}, default=str, indent=1))
        deadline = time.monotonic() + timeout_s
        answer_path = decided / f"{rid}.json"
        while time.monotonic() < deadline and not (callable(until) and until()):
            if answer_path.exists():
                try:
                    got = json.loads(answer_path.read_text())
                except json.JSONDecodeError:
                    time.sleep(POLL_S)
                    continue
                for path in ((pending / f"{rid}.json"), answer_path):
                    if path.exists():
                        path.rename(done / f"{rid}.{'request' if path.parent == pending else 'answer'}.json")
                return {"request_id": rid, "decision": got["decision"], "mode": "human", "reviewer": "human",
                        "shown_at": got["shown_at"], "decided_at": got["decided_at"],
                        "seconds": seconds_between(got["shown_at"], got["decided_at"])}
            time.sleep(POLL_S)
        stale = pending / f"{rid}.json"
        if stale.exists():
            stale.rename(done / f"{rid}.expired.json")
        return None

    def pending(self) -> list[dict]:
        """bin/review's queue: the requests waiting for a person, oldest first."""
        pending, _, _ = self._dirs()
        out = []
        for path in sorted(pending.glob("*.json"), key=lambda p: p.stat().st_mtime):
            try:
                out.append(json.loads(path.read_text()))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    def decide(self, request_id: str, decision: str, shown_at: str, decided_at: str | None = None) -> None:
        """bin/review's answer to one request."""
        if decision not in ("approve", "deny"):
            raise ReviewerError(f"a decision is approve or deny, not {decision!r}")
        _, decided, _ = self._dirs()
        tmp = decided / f".{request_id}.tmp"
        tmp.write_text(json.dumps({"decision": decision, "shown_at": shown_at, "decided_at": decided_at or now()}))
        tmp.rename(decided / f"{request_id}.json")

    # -- the harness's own log ------------------------------------------------------------------
    def _log(self, request: dict, request_id: str, asked_at: str, answer: dict | None) -> None:
        line = {"at": now(), "asked_at": asked_at, "request_id": request_id, "run_id": request.get("run_id"),
                "kind": request.get("kind", "approval"), "action": request.get("action"),
                "action_class": request.get("action_class"), "mode": self.mode,
                "answer": answer["decision"] if answer else "none",
                "seconds": answer["seconds"] if answer else None}
        with _lock:
            self.logs.mkdir(parents=True, exist_ok=True)
            with (self.logs / "reviewer.jsonl").open("a") as fh:
                fh.write(json.dumps(line) + "\n")
