"""The memory store: shared by every run, keyed by repository and issue, in SQLite.
Assignment 4's working solution, which Assignment 5 builds on.

The interface is checks/FORMATS.md, section 12.5. Every record carries its kind
and its provenance: source, written_at, origin and confirmed. A contradicted record
is superseded, never edited or appended beside: the new record names the old in
`supersedes`, and the old one stays, inactive (slide 25). An issue's text is never
stored as a semantic fact (slide 26): write() refuses it.

REPOMIND_STORE=empty gives every Store() a new, empty store in a temporary
directory, so each run starts from nothing even when five share a process (run.py
--runs 5): Part D's second set of five runs, and Part F's runs that must not have
the store. The checker never sets it.
"""

from __future__ import annotations

import os
import re
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from harness import ROOT

DEFAULT = ROOT / "state" / "store.db"
REPOSITORY = "ledgerline"
KINDS = ("episodic", "semantic", "procedural")
ORIGINS = ("derived", "ingested")
SOURCE = re.compile(r"^(user|repo|memory|issue:\d+)$")
FIELDS = ("id", "repository", "issue", "kind", "text", "source", "written_at", "origin", "confirmed", "active",
          "supersedes", "stated_by")
SCHEMA = """CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY, repository TEXT NOT NULL, issue INTEGER, kind TEXT NOT NULL, text TEXT NOT NULL,
    source TEXT NOT NULL, written_at TEXT NOT NULL, origin TEXT NOT NULL, confirmed INTEGER NOT NULL,
    active INTEGER NOT NULL, supersedes TEXT, stated_by TEXT)"""
_lock = threading.Lock()
def default_path() -> Path:
    """The real store; under REPOMIND_STORE=empty, a new, empty one each time."""
    if os.environ.get("REPOMIND_STORE") == "empty":
        return Path(tempfile.mkdtemp(prefix="repomind-empty-store-")) / "store.db"
    return DEFAULT


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Store:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or default_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute(SCHEMA)

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _row(row) -> dict:
        out = dict(row)
        out["confirmed"], out["active"] = bool(out["confirmed"]), bool(out["active"])
        return out

    @staticmethod
    def _check(record: dict) -> None:
        problems = []
        if record.get("kind") not in KINDS:
            problems.append(f"kind is one of {KINDS}")
        if not SOURCE.match(str(record.get("source") or "")):
            problems.append("source is user, repo, memory or issue:<n>")
        if record.get("origin") not in ORIGINS:
            problems.append(f"origin is one of {ORIGINS}")
        if not isinstance(record.get("confirmed"), bool):
            problems.append("confirmed is true or false")
        if not str(record.get("text") or "").strip():
            problems.append("text is the memory, in words")
        if str(record.get("source")).startswith("issue:") and record.get("kind") == "semantic":
            problems.append("an issue's text is never stored as a semantic fact: it is a claim anyone can write")
        if problems:
            raise ValueError("; ".join(problems))

    def _insert(self, db, record: dict, supersedes=None) -> str:
        n = db.execute("SELECT COUNT(*) FROM records").fetchone()[0] + 1
        rid = f"m{n:04d}"
        db.execute(f"INSERT INTO records ({', '.join(FIELDS)}) VALUES ({', '.join('?' * len(FIELDS))})",
                   (rid, record.get("repository") or REPOSITORY, record.get("issue"), record["kind"],
                    record["text"], record["source"], record.get("written_at") or now(), record["origin"],
                    int(record["confirmed"]), 1, supersedes, record.get("stated_by")))
        return rid

    def write(self, record: dict) -> str:
        self._check(record)
        with _lock, self._db() as db:
            return self._insert(db, record)

    def supersede(self, old_id, record: dict) -> str:
        self._check(record)
        with _lock, self._db() as db:
            if db.execute("SELECT 1 FROM records WHERE id = ? AND active = 1", (str(old_id),)).fetchone() is None:
                raise KeyError(f"no active record {old_id!r} to supersede")
            db.execute("UPDATE records SET active = 0 WHERE id = ?", (str(old_id),))
            return self._insert(db, record, supersedes=str(old_id))

    def active(self, repository: str, issue: int | None = None) -> list[dict]:
        with self._db() as db:
            if issue is None:
                rows = db.execute("SELECT * FROM records WHERE repository = ? AND active = 1 ORDER BY id",
                                  (repository,))
            else:
                rows = db.execute("SELECT * FROM records WHERE repository = ? AND active = 1 "
                                  "AND (issue IS NULL OR issue = ?) ORDER BY id", (repository, int(issue)))
            return [self._row(r) for r in rows]

    def records(self) -> list[dict]:
        with self._db() as db:
            return [self._row(r) for r in db.execute("SELECT * FROM records ORDER BY id")]
