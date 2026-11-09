"""The mock issue tracker, and the mock remote that holds pull requests, labels,
closed issues, pushes and merges.

Issues are Markdown files in fixtures/issues/ (evaluation), fixtures/issues/dev/
(development), and from Assignment 5 fixtures/issues/day/ and day2/ (the two day
queues) and fixtures/issues/moments/ (the three moments), each with a small
front-matter header. An issue can carry its discussion: the comments people wrote
on it, under a "## Discussion" heading, one "### author · date" entry each
(checks/FORMATS.md, section 12.7). issue() returns them as `discussion`.
Comments, pull requests (PRs) and the rest live in a SQLite database,
tracker/tracker.db (checks/FORMATS.md, sections 11.5 and 13.6, give its tables).

Three rules hold for every write and every read:

- **Every write is stamped with the run_id of the run that made it**, by the
  harness, not the model. That stamp is what makes a run attributable.
- **Every read is scoped to one run.** A run sees only its own comments, PRs,
  labels, closes, pushes and merges, so a check before a write in run 2 never finds
  run 1's. The model never sees a comment a run wrote: read_issue returns the issue
  and its fixture discussion.
- **A write may carry an idempotency key**, and the remote accepts each key once:
  a unique constraint on the key column. A second write with a key the remote has
  seen writes nothing and returns the first write's row, marked "replayed": true.

Assignment 5 adds:

- **The remote's own rule, branch protection on main** (PROTECTED): a push to main
  is rejected by the remote, as a repository setting would reject it, whatever
  your policy says. It is not your policy: the rejected attempt is still a write
  attempt, and the log keeps it.
- **The write log** (log()): one line per write attempt the remote receives, every
  kind, with its run_id, its outcome and its time to the millisecond
  (harness.clock), and one line per compensation. The checker reads what reached
  the remote, and when, from here.
- **Three compensating endpoints**, remove_label(), close_pr() and reopen_issue():
  each offsets one earlier write, and each is logged. They are not tools: the model
  cannot call them, and your bin/rollback can. There is no way to delete a comment
  or to undo a push or a merge, on purpose.
- **Issue metadata** (metadata()): whether RepoMind itself opened the issue, and
  when a person last commented on its thread. read_issue never returns it, so the
  model cannot see it; your hook can read it. And facts(): the circumstance of one
  call, the same fields the recorded day's lines carry (section 13.2).

The tracker can lie, when a switch says so (harness/switches.py):

- FLAKY_WRITES=1: a write attempt times out about six times in ten. About five of
  those six had committed before the connection dropped; the other one never
  reached the tracker. Either way the caller gets TrackerTimeout, with the same
  words, and cannot tell which happened.
- READBACK_FAIL=1: once a write in a run has timed out, every read of that run's
  writes raises ReadbackUnavailable.

The tracker logs every write attempt it receives in its `attempts` table, and what
happened to it. That log is the tracker's, for counting and for the checker; your
harness must not read it to decide anything.

`make reset` archives the database to tracker/archive/ and starts empty; nothing is
ever deleted, and the checker reads the archives too.

    python -m harness.tracker reset    # archive tracker.db and start empty
"""

from __future__ import annotations

import json
import random
import re
import shutil
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from harness import ROOT
from harness import switches
from harness.clock import now, parse

_lock = threading.Lock()

# FLAKY_WRITES: the share of write attempts that time out, by when the connection drops.
FLAKY_RATES = {"before_commit": 0.1, "after_commit": 0.5}
TIMEOUT_MESSAGE = "the tracker did not answer in time"   # simulated: no real wait

# Assignment 5: the remote's branches. main and develop always exist; a PR's branch
# exists once the PR is opened. A push to a protected branch is rejected by the remote.
BASE = "develop"
PROTECTED = ("main",)
STANDING_BRANCHES = ("main", "develop")

# Issue folders, and the sets run.py --set names.
ISSUE_SETS = {"eval": "", "dev": "dev", "day": "day", "day2": "day2", "moments": "moments"}
# Front-matter fields that are metadata: the hook may read them, read_issue never returns them.
METADATA = ("opened_by_agent", "human_comment_minutes_ago")

SCHEMA = """
CREATE TABLE IF NOT EXISTS comments (
    id        INTEGER PRIMARY KEY,
    run_id    TEXT NOT NULL,
    issue     INTEGER NOT NULL,
    body      TEXT NOT NULL,
    key       TEXT UNIQUE,
    posted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prs (
    id        INTEGER PRIMARY KEY,
    run_id    TEXT NOT NULL,
    issue     INTEGER NOT NULL,
    branch    TEXT NOT NULL,
    title     TEXT NOT NULL,
    body      TEXT NOT NULL,
    draft     INTEGER NOT NULL DEFAULT 1,
    state     TEXT NOT NULL DEFAULT 'open',
    key       TEXT UNIQUE,
    opened_at TEXT NOT NULL,
    base      TEXT NOT NULL DEFAULT 'develop',
    closed_at TEXT,
    merged_at TEXT
);
CREATE TABLE IF NOT EXISTS attempts (
    id        INTEGER PRIMARY KEY,
    run_id    TEXT NOT NULL,
    kind      TEXT NOT NULL,
    issue     INTEGER NOT NULL,
    key       TEXT,
    outcome   TEXT NOT NULL,
    row_id    INTEGER,
    at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS labels (
    id         INTEGER PRIMARY KEY,
    run_id     TEXT NOT NULL,
    issue      INTEGER NOT NULL,
    label      TEXT NOT NULL,
    key        TEXT UNIQUE,
    added_at   TEXT NOT NULL,
    removed_at TEXT
);
CREATE TABLE IF NOT EXISTS closes (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT NOT NULL,
    issue       INTEGER NOT NULL,
    reason      TEXT NOT NULL,
    key         TEXT UNIQUE,
    closed_at   TEXT NOT NULL,
    reopened_at TEXT
);
CREATE TABLE IF NOT EXISTS pushes (
    id        INTEGER PRIMARY KEY,
    run_id    TEXT NOT NULL,
    issue     INTEGER NOT NULL,
    branch    TEXT NOT NULL,
    message   TEXT NOT NULL,
    files     TEXT NOT NULL,
    key       TEXT UNIQUE,
    pushed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS merges (
    id        INTEGER PRIMARY KEY,
    run_id    TEXT NOT NULL,
    issue     INTEGER NOT NULL,
    pr        INTEGER NOT NULL,
    key       TEXT UNIQUE,
    merged_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS log (
    id      INTEGER PRIMARY KEY,
    run_id  TEXT NOT NULL,
    action  TEXT NOT NULL,
    issue   INTEGER,
    target  TEXT,
    outcome TEXT NOT NULL,
    key     TEXT,
    detail  TEXT,
    at      TEXT NOT NULL
);
"""

# What the attempts table's outcome column says.
OUTCOMES = ("written", "replayed", "timeout_after_commit", "timeout_before_commit")
# What the write log's outcome column says: the four above, a write the remote's own
# rule refused, and a compensation applied.
LOG_OUTCOMES = OUTCOMES + ("rejected", "compensated")
# Each kind of write: its table, and the action the log names it by (Lecture 5's names).
KINDS = {"comment": ("comments", "post_comment"), "pr": ("prs", "open_pr"), "label": ("labels", "apply_label"),
         "close": ("closes", "close_issue"), "push": ("pushes", "push_commit"), "merge": ("merges", "merge_pr")}
TABLES = ("comments", "prs", "attempts", "labels", "closes", "pushes", "merges", "log")


DISCUSSION = "## Discussion"
_ENTRY = re.compile(r"^###\s+(?P<author>[^\s(·]+)(?:\s*\((?P<role>[^)]*)\))?\s*·\s*(?P<date>\S+)\s*$", re.MULTILINE)


def parse_discussion(text: str) -> list[dict]:
    """An issue's discussion: [{author, role, date, body}], oldest first. `role` is what
    the fixture says in brackets after the name, such as maintainer, or None."""
    entries = list(_ENTRY.finditer(text))
    out = []
    for i, m in enumerate(entries):
        end = entries[i + 1].start() if i + 1 < len(entries) else len(text)
        out.append({"author": m["author"], "role": m["role"], "date": m["date"],
                    "body": text[m.end():end].strip()})
    return out


class IssueNotFound(KeyError):
    pass


class TrackerTimeout(TimeoutError):
    """A write timed out. It may or may not have happened: nothing in the error says which."""


class ReadbackUnavailable(ConnectionError):
    """READBACK_FAIL: a read of this run's writes failed, after one of its writes timed out."""


class RemoteRefused(ValueError):
    """The remote's own rule refused a write: a push to a protected branch, a push to a
    branch that does not exist, a merge of a pull request that is not open. Nothing
    was written; the attempt is in the log as rejected."""


class Tracker:
    def __init__(self, root: Path | None = None, state_dir: Path | None = None, *,
                 flaky: bool | None = None, readback_fail: bool | None = None,
                 faults: list[str | None] | None = None, seed: int | None = None):
        """`flaky` and `readback_fail` default to the switches. `faults`, for tests and
        the checker, decides write attempts in order instead of chance: each entry is
        None (the write goes through), "before_commit" or "after_commit"; once the
        list is used up, writes go through (or, with `flaky`, take their chance)."""
        self.root = Path(root or ROOT)
        self.issue_dir = self.root / "fixtures" / "issues"
        self.state_dir = Path(state_dir or self.root / "tracker")
        self.db_path = self.state_dir / "tracker.db"
        on = switches.current()
        self.flaky = on["flaky_writes"] if flaky is None else flaky
        self.readback_fail = on["readback_fail"] if readback_fail is None else readback_fail
        self.faults = list(faults) if faults is not None else None
        self._rng = random.Random(seed)
        self._timed_out: set[str] = set()   # runs with a write that timed out (READBACK_FAIL)
        self.on_commit = None                # the runner's: called (run_id, kind) once a write commits
        self._first_read: dict[int, str] = {}   # metadata's minutes-ago count back from each issue's first read

    # -- issues -------------------------------------------------------------------
    def _issue_path(self, number: int) -> Path:
        for folder in ISSUE_SETS.values():
            candidate = (self.issue_dir / folder if folder else self.issue_dir) / f"{number}.md"
            if candidate.exists():
                return candidate
        raise IssueNotFound(number)

    def _front(self, number: int) -> tuple[dict, str]:
        text = self._issue_path(int(number)).read_text()
        _, header, body = text.split("---", 2)
        return yaml.safe_load(header) or {}, body

    def issue(self, number: int) -> dict:
        """The issue as read_issue may show it: never its metadata."""
        meta, body = self._front(number)
        body, _, rest = body.partition(DISCUSSION)
        shown = {k: v for k, v in meta.items() if k not in METADATA}
        return {**shown, "body": body.strip(), "discussion": parse_discussion(rest)}

    def metadata(self, number: int) -> dict:
        """Assignment 5: what your hook may know about an issue and the model may not.

        opened_by_agent               True when RepoMind itself opened the issue
        last_human_comment_at         when a person last commented on its thread, or None
        minutes_since_human_comment   minutes from then to now, or None

        The front matter's human_comment_minutes_ago counts back from the first time
        this tracker read the issue's metadata, so a thread is as active as the fixture
        says when a run starts on it, however long a day queue takes."""
        meta, _ = self._front(number)
        ago = meta.get("human_comment_minutes_ago")
        last = None
        if isinstance(ago, (int, float)) and not isinstance(ago, bool):
            with _lock:
                anchor = self._first_read.setdefault(int(number), now())
            last = (parse(anchor) - timedelta(minutes=float(ago))).isoformat(
                timespec="milliseconds").replace("+00:00", "Z")
        minutes = None if last is None else round(
            (datetime.now(timezone.utc) - parse(last)).total_seconds() / 60, 1)
        return {"issue": int(number), "opened_by_agent": bool(meta.get("opened_by_agent")),
                "last_human_comment_at": last, "minutes_since_human_comment": minutes}

    def issue_numbers(self, which: str = "eval") -> list[int]:
        if which not in ISSUE_SETS:
            raise ValueError(f"no issue set {which!r}: one of {', '.join(ISSUE_SETS)}")
        folder = self.issue_dir / ISSUE_SETS[which] if ISSUE_SETS[which] else self.issue_dir
        return sorted(int(p.stem) for p in folder.glob("*.md"))

    # -- the database ---------------------------------------------------------------
    @contextmanager
    def _connect(self):
        """One connection, committed and closed when the block ends."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.executescript(SCHEMA)
            yield db
            db.commit()
        finally:
            db.close()

    def _fault(self) -> str | None:
        with _lock:
            if self.faults:
                return self.faults.pop(0)
            if not self.flaky:
                return None
            roll = self._rng.random()
        if roll < FLAKY_RATES["before_commit"]:
            return "before_commit"
        if roll < FLAKY_RATES["before_commit"] + FLAKY_RATES["after_commit"]:
            return "after_commit"
        return None

    @staticmethod
    def _log(db, run_id: str, action: str, issue, target, outcome: str, key=None, detail: str = "") -> None:
        db.execute("INSERT INTO log (run_id, action, issue, target, outcome, key, detail, at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (run_id, action, issue, target, outcome, key, detail, now()))

    def _write(self, run_id: str, kind: str, issue: int, key: str | None, insert, target=None) -> dict:
        """One write attempt: the fault, the key's unique constraint, the attempts log
        and the write log."""
        table, action = KINDS[kind]
        fault = self._fault()
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with _lock, self._connect() as db:
            if fault == "before_commit":
                db.execute("INSERT INTO attempts (run_id, kind, issue, key, outcome, row_id, at) "
                           "VALUES (?, ?, ?, ?, ?, NULL, ?)", (run_id, kind, issue, key, "timeout_before_commit", stamp))
                self._log(db, run_id, action, issue, target, "timeout_before_commit", key)
                row = None
            else:
                existing = (db.execute(f"SELECT * FROM {table} WHERE key = ?", (key,)).fetchone()
                            if key is not None else None)
                if existing is not None:
                    row, outcome = {**dict(existing), "replayed": True}, "replayed"
                else:
                    row, outcome = {**insert(db, stamp), "replayed": False}, "written"
                if fault == "after_commit":
                    outcome = "timeout_after_commit"
                db.execute("INSERT INTO attempts (run_id, kind, issue, key, outcome, row_id, at) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?)", (run_id, kind, issue, key, outcome, row["id"], stamp))
                named = target if target is not None else f"{'pr' if kind == 'pr' else 'comment'}-{row['id']}"
                self._log(db, run_id, action, issue, named, outcome, key)
        if fault != "before_commit" and self.on_commit is not None:
            self.on_commit(run_id, kind)    # the write is committed; run.py --die-during-step stops here
        if fault is not None:
            self._timed_out.add(run_id)
            raise TrackerTimeout(TIMEOUT_MESSAGE)
        return row

    def _refuse(self, run_id: str, kind: str, issue, target, key, why: str):
        with _lock, self._connect() as db:
            self._log(db, run_id, KINDS[kind][1], issue, target, "rejected", key, why)
        raise RemoteRefused(why)

    def _readable(self, run_id: str) -> None:
        if not run_id:
            raise TypeError("every read is scoped to one run: pass its run_id")
        if self.readback_fail and run_id in self._timed_out:
            raise ReadbackUnavailable("the tracker could not be read; try again later")

    def _rows(self, sql: str, args: tuple) -> list[dict]:
        if not self.db_path.exists():
            return []
        with self._connect() as db:
            return [dict(r) for r in db.execute(sql, args).fetchall()]

    def by_key(self, run_id: str, kind: str, key: str) -> dict | None:
        """This run's write of this kind (comment, pr, label, close, push, merge) made
        with this key, or None. The registry's check before every attempt."""
        self._readable(run_id)
        rows = self._rows(f"SELECT * FROM {KINDS[kind][0]} WHERE run_id = ? AND key = ?", (run_id, key))
        return rows[0] if rows else None

    # -- comments -----------------------------------------------------------------
    def post_comment(self, run_id: str, number: int, body: str, key: str | None = None) -> dict:
        self._issue_path(int(number))  # refuse comments on issues that do not exist

        def insert(db, stamp):
            cur = db.execute("INSERT INTO comments (run_id, issue, body, key, posted_at) VALUES (?, ?, ?, ?, ?)",
                             (run_id, int(number), body, key, stamp))
            return {"id": cur.lastrowid, "run_id": run_id, "issue": int(number), "body": body, "key": key,
                    "posted_at": stamp}
        return self._write(run_id, "comment", int(number), key, insert)

    def comments(self, run_id: str, issue: int | None = None) -> list[dict]:
        """This run's comments, oldest first; on one issue if `issue` is given."""
        self._readable(run_id)
        if issue is None:
            return self._rows("SELECT * FROM comments WHERE run_id = ? ORDER BY id", (run_id,))
        return self._rows("SELECT * FROM comments WHERE run_id = ? AND issue = ? ORDER BY id", (run_id, int(issue)))

    def comment_by_key(self, run_id: str, key: str) -> dict | None:
        """This run's comment written with this key, or None."""
        return self.by_key(run_id, "comment", key)

    # -- pull requests ----------------------------------------------------------------
    def open_pr(self, run_id: str, number: int, branch: str, title: str, body: str,
                key: str | None = None) -> dict:
        """Open a draft PR from `branch` for issue `number`, into develop. The mock remote
        needs no commits."""
        self._issue_path(int(number))
        if not str(branch).strip() or not str(title).strip():
            raise ValueError("a pull request needs a branch and a title")

        def insert(db, stamp):
            cur = db.execute("INSERT INTO prs (run_id, issue, branch, title, body, key, opened_at, base) "
                             "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (run_id, int(number), branch, title, body, key, stamp, BASE))
            return {"id": cur.lastrowid, "run_id": run_id, "issue": int(number), "branch": branch, "title": title,
                    "body": body, "draft": 1, "state": "open", "key": key, "opened_at": stamp, "base": BASE}
        return self._write(run_id, "pr", int(number), key, insert)

    def prs(self, run_id: str, branch: str | None = None, state: str | None = "open") -> list[dict]:
        """This run's PRs, oldest first: open ones unless `state` says otherwise (None for all)."""
        self._readable(run_id)
        sql, args = "SELECT * FROM prs WHERE run_id = ?", [run_id]
        if branch is not None:
            sql, args = sql + " AND branch = ?", args + [branch]
        if state is not None:
            sql, args = sql + " AND state = ?", args + [state]
        return self._rows(sql + " ORDER BY id", tuple(args))

    def pr_by_key(self, run_id: str, key: str) -> dict | None:
        """This run's PR opened with this key, or None."""
        return self.by_key(run_id, "pr", key)

    def pr(self, run_id: str, number: int) -> dict | None:
        """This run's PR number `number` (the id in pr-<id>), whatever its state, or None."""
        self._readable(run_id)
        rows = self._rows("SELECT * FROM prs WHERE run_id = ? AND id = ?", (run_id, int(number)))
        return rows[0] if rows else None

    # -- Assignment 5: labels, closes, pushes, merges ------------------------------------
    def apply_label(self, run_id: str, number: int, label: str, key: str | None = None) -> dict:
        """Add one label to one issue."""
        self._issue_path(int(number))
        if not str(label).strip():
            raise ValueError("a label needs a name")

        def insert(db, stamp):
            at = now()
            cur = db.execute("INSERT INTO labels (run_id, issue, label, key, added_at) VALUES (?, ?, ?, ?, ?)",
                             (run_id, int(number), label, key, at))
            return {"id": cur.lastrowid, "run_id": run_id, "issue": int(number), "label": label, "key": key,
                    "added_at": at, "removed_at": None}
        return self._write(run_id, "label", int(number), key, insert, target=label)

    def labels(self, run_id: str, issue: int | None = None, active: bool = True) -> list[dict]:
        """This run's labels, oldest first: the ones still on the issue unless active=False."""
        self._readable(run_id)
        sql, args = "SELECT * FROM labels WHERE run_id = ?", [run_id]
        if issue is not None:
            sql, args = sql + " AND issue = ?", args + [int(issue)]
        if active:
            sql += " AND removed_at IS NULL"
        return self._rows(sql + " ORDER BY id", tuple(args))

    def close_issue(self, run_id: str, number: int, reason: str, key: str | None = None) -> dict:
        """Close one issue, with the reason stated."""
        self._issue_path(int(number))

        def insert(db, stamp):
            at = now()
            cur = db.execute("INSERT INTO closes (run_id, issue, reason, key, closed_at) VALUES (?, ?, ?, ?, ?)",
                             (run_id, int(number), reason, key, at))
            return {"id": cur.lastrowid, "run_id": run_id, "issue": int(number), "reason": reason, "key": key,
                    "closed_at": at, "reopened_at": None}
        return self._write(run_id, "close", int(number), key, insert, target=f"issue-{int(number)}")

    def closes(self, run_id: str, active: bool = True) -> list[dict]:
        """This run's closes: the ones not reopened unless active=False."""
        self._readable(run_id)
        return self._rows("SELECT * FROM closes WHERE run_id = ?" + (" AND reopened_at IS NULL" if active else "")
                          + " ORDER BY id", (run_id,))

    def branches(self, run_id: str) -> list[str]:
        """The branches this run can push to or name: main, develop, and its PRs' branches."""
        return list(STANDING_BRANCHES) + [p["branch"] for p in self.prs(run_id, state=None)]

    def push_commit(self, run_id: str, issue: int, branch: str, message: str, files: list[str],
                    key: str | None = None) -> dict:
        """Commit to an existing branch. The remote rejects a push to a protected branch
        (main) and to a branch that does not exist, and logs the attempt as rejected."""
        if branch in PROTECTED:
            self._refuse(run_id, "push", issue, branch, key,
                         f"branch protection: {branch} accepts no direct pushes (a repository setting)")
        if branch not in self.branches(run_id):
            self._refuse(run_id, "push", issue, branch, key, f"no branch {branch!r} on the remote")

        def insert(db, stamp):
            at = now()
            cur = db.execute("INSERT INTO pushes (run_id, issue, branch, message, files, key, pushed_at) "
                             "VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (run_id, int(issue or 0), branch, message, json.dumps(list(files)), key, at))
            return {"id": cur.lastrowid, "run_id": run_id, "issue": int(issue or 0), "branch": branch,
                    "message": message, "files": list(files), "key": key, "pushed_at": at}
        return self._write(run_id, "push", int(issue or 0), key, insert, target=branch)

    def pushes(self, run_id: str) -> list[dict]:
        self._readable(run_id)
        return self._rows("SELECT * FROM pushes WHERE run_id = ? ORDER BY id", (run_id,))

    def merge_pr(self, run_id: str, number: int, key: str | None = None) -> dict:
        """Merge one of this run's open pull requests into its base."""
        found = self.pr(run_id, number)
        if found is None or found["state"] != "open":
            self._refuse(run_id, "merge", found["issue"] if found else None, f"pr-{number}", key,
                         f"pr-{number} is not an open pull request of this run")

        def insert(db, stamp):
            at = now()
            cur = db.execute("INSERT INTO merges (run_id, issue, pr, key, merged_at) VALUES (?, ?, ?, ?, ?)",
                             (run_id, found["issue"], int(number), key, at))
            db.execute("UPDATE prs SET state = 'merged', merged_at = ? WHERE id = ?", (at, int(number)))
            return {"id": cur.lastrowid, "run_id": run_id, "issue": found["issue"], "pr": int(number), "key": key,
                    "merged_at": at, "base": found["base"]}
        return self._write(run_id, "merge", found["issue"], key, insert, target=f"pr-{number}")

    # -- Assignment 5: the three compensating endpoints. Not tools: harness code only ----------
    def remove_label(self, run_id: str, label_id: int) -> dict:
        """Offset one label this run added: it comes off the issue. The row stays, with removed_at."""
        return self._compensate(run_id, "labels", label_id, "removed_at", "remove_label",
                                lambda r: r["label"], lambda r: r["removed_at"] is None)

    def close_pr(self, run_id: str, pr_id: int) -> dict:
        """Offset one PR this run opened: it is closed, unmerged. A merged PR cannot be closed."""
        return self._compensate(run_id, "prs", pr_id, "closed_at", "close_pr",
                                lambda r: f"pr-{r['id']}", lambda r: r["state"] == "open", state="closed")

    def reopen_issue(self, run_id: str, close_id: int) -> dict:
        """Offset one close this run made: the issue is open again."""
        return self._compensate(run_id, "closes", close_id, "reopened_at", "reopen_issue",
                                lambda r: f"issue-{r['issue']}", lambda r: r["reopened_at"] is None)

    def _compensate(self, run_id, table, row_id, column, action, target, undoable, state=None) -> dict:
        self._readable(run_id)
        with _lock, self._connect() as db:
            row = db.execute(f"SELECT * FROM {table} WHERE run_id = ? AND id = ?", (run_id, int(row_id))).fetchone()
            if row is None:
                raise RemoteRefused(f"{action}: run {run_id} has no {table[:-1]} {row_id}")
            row = dict(row)
            if not undoable(row):
                raise RemoteRefused(f"{action}: {target(row)} cannot be offset now (already offset, or merged)")
            at = now()
            db.execute(f"UPDATE {table} SET {column} = ?" + (", state = ?" if state else "") + " WHERE id = ?",
                       (at, state, int(row_id)) if state else (at, int(row_id)))
            self._log(db, run_id, action, row.get("issue"), target(row), "compensated", row.get("key"))
            return {**row, column: at, **({"state": state} if state else {})}

    # -- Assignment 5: one call's facts --------------------------------------------------------
    def facts(self, run_id: str, action: str, args: dict, issue: int | None = None) -> dict:
        """The circumstance of one call, as the recorded day's lines carry it
        (checks/FORMATS.md, section 13.2). `action` is Lecture 5's name (post_comment,
        not your tool's); `args` are the call's arguments; `issue` is the run's issue,
        for a call whose arguments name none. Every field is present; None where it
        does not apply."""
        from harness.facts import facts
        return facts(self, run_id, action, args, issue)

    # -- the whole database, for the runner and the checkers --------------------------
    def table(self, name: str) -> list[dict]:
        """Every row of one table, every run's. Not for your harness: for bin/rollback use
        log(run_id), and for everything else this run's own reads."""
        if name not in TABLES:
            raise ValueError(f"no table {name!r}")
        return self._rows(f"SELECT * FROM {name} ORDER BY id", ())

    def log(self, run_id: str | None = None) -> list[dict]:
        """The write log, oldest first: this run's lines, or every run's with None."""
        if run_id is None:
            return self.table("log")
        return self._rows("SELECT * FROM log WHERE run_id = ? ORDER BY id", (run_id,))

    def remove_runs(self, run_ids: set[str]) -> dict[str, list[dict]]:
        """Delete these runs' rows from every table and return them (run.py --discard)."""
        out: dict[str, list[dict]] = {}
        if not self.db_path.exists() or not run_ids:
            return out
        marks = ",".join("?" * len(run_ids))
        with _lock, self._connect() as db:
            for name in TABLES:
                rows = db.execute(f"SELECT * FROM {name} WHERE run_id IN ({marks})", tuple(run_ids)).fetchall()
                out[name] = [dict(r) for r in rows]
                db.execute(f"DELETE FROM {name} WHERE run_id IN ({marks})", tuple(run_ids))
        return out

    def reset(self) -> Path | None:
        """Archive the database and start empty. Returns the archive path."""
        if not self.db_path.exists():
            return None
        archive = self.state_dir / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        target = archive / f"tracker-{time.strftime('%Y%m%d-%H%M%S')}.db"
        shutil.move(str(self.db_path), target)
        return target


if __name__ == "__main__":
    if sys.argv[1:] == ["reset"]:
        moved = Tracker().reset()
        print(f"tracker reset; the old database archived to {moved}" if moved else "tracker already empty")
    else:
        print(__doc__)
