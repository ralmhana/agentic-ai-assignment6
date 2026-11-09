"""The checkpointer: one run's checkpoints, keyed by its run_id, in SQLite.
Assignment 4's working solution, which Assignment 5 builds on.

The interface is checks/FORMATS.md, section 12.4. A sync save is committed, with
SQLite's synchronous=FULL, before save() returns: on disk before the next call
starts. An async save is written by a background thread, so a crash in the gap
loses it. An exit save waits in memory until flush(), at the end of the run, so a
crash loses all of them. RepoMind's runs write, so they run sync (slide 12).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from harness import ROOT
from harness.formats import CHECKPOINT_FIELDS, DURABILITY_MODES

DEFAULT = ROOT / "state" / "checkpoints.db"
SCHEMA = """CREATE TABLE IF NOT EXISTS checkpoints (
    run_id TEXT NOT NULL, seq INTEGER NOT NULL, step TEXT, mode TEXT NOT NULL,
    saved_at TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (run_id, seq))"""
_lock = threading.Lock()


class Checkpointer:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or DEFAULT)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._pending: list[tuple] = []    # exit-mode saves, not yet written
        with self._db() as db:
            db.execute(SCHEMA)

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA synchronous=FULL")
        return db

    def _insert(self, run_id: str, step, mode: str, body: str) -> None:
        with _lock:
            db = self._db()
            try:
                seq = db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM checkpoints WHERE run_id = ?",
                                 (run_id,)).fetchone()[0]
                db.execute("INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?)",
                           (run_id, seq, None if step is None else str(step), mode,
                            time.strftime("%Y-%m-%dT%H:%M:%S"), body))
                db.commit()
            finally:
                db.close()

    def save(self, run_id: str, checkpoint: dict, *, step, mode: str = "sync") -> None:
        if mode not in DURABILITY_MODES:
            raise ValueError(f"mode is one of {DURABILITY_MODES}, not {mode!r}")
        extra = set(checkpoint) - set(CHECKPOINT_FIELDS)
        missing = set(CHECKPOINT_FIELDS) - set(checkpoint)
        if missing or (extra and extra != {"conversation"}):
            raise ValueError(f"a checkpoint holds exactly {CHECKPOINT_FIELDS}; missing {sorted(missing)}, "
                             f"extra {sorted(extra)}")
        body = json.dumps(checkpoint, sort_keys=True)   # anything that does not serialize fails here
        if mode == "sync":
            self._insert(run_id, step, mode, body)
        elif mode == "async":
            threading.Thread(target=self._insert, args=(run_id, step, mode, body), daemon=True).start()
        else:
            self._pending.append((run_id, step, mode, body))

    def flush(self) -> None:
        """Write the exit-mode saves: call it when the run ends."""
        for item in self._pending:
            self._insert(*item)
        self._pending.clear()

    def _bodies(self, run_id: str) -> list[str]:
        with self._db() as db:
            return [row[0] for row in db.execute("SELECT body FROM checkpoints WHERE run_id = ? ORDER BY seq",
                                                 (run_id,))]

    def last(self, run_id: str) -> dict | None:
        bodies = self._bodies(run_id)
        return json.loads(bodies[-1]) if bodies else None

    def all(self, run_id: str) -> list[dict]:
        return [json.loads(b) for b in self._bodies(run_id)]

    def runs(self) -> list[str]:
        with self._db() as db:
            return [row[0] for row in db.execute("SELECT DISTINCT run_id FROM checkpoints ORDER BY run_id")]

    def size(self, run_id: str) -> int:
        """Part E: the bytes one run's checkpoints take together, as saved."""
        return sum(len(b.encode()) for b in self._bodies(run_id))
