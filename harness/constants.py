"""Assignment 6: the five things a comparison holds constant (slide 59).

The runner writes them into every run_start line as `constants` (checks/FORMATS.md,
section 14.2), so that two arms can be shown to differ only in their design:

    model         the model's ID, from settings.yaml (a scripted model's own name)
    schemas_sha   a hash of the tool definitions the registry sends, in its order
    budget        the run's token budget, recorded beside them as `budget`
    checks_sha    a hash of the grounded check: eval/check_task.py, eval/check_triage.py
                  and the task set's answers
    reviewer      the reviewer mode (REVIEWER)
    task_ids      the IDs of the task set the command ran over

The budget is the one "almost never held": it is recorded on its own, per run,
because a batch's budget is five times a single task's.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from harness import ROOT

CHECK_SCRIPTS = ("eval/check_task.py", "eval/check_triage.py")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def schemas_sha(schemas: list[dict]) -> str:
    return sha(json.dumps(schemas, sort_keys=True).encode())


def checks_sha(tasks, root: Path = ROOT) -> str:
    h = hashlib.sha256()
    for rel in CHECK_SCRIPTS:
        path = Path(root) / rel
        h.update(rel.encode() + b"\0" + (path.read_bytes() if path.exists() else b"") + b"\0")
    for task in sorted(tasks, key=lambda t: t.id):
        h.update(json.dumps([task.id, {str(k): v for k, v in sorted(task.answers.items())}],
                            sort_keys=True).encode())
    return h.hexdigest()[:16]


def constants(model: str, schemas: list[dict], tasks, reviewer: str, root: Path = ROOT) -> dict:
    return {"model": model, "schemas_sha": schemas_sha(schemas), "checks_sha": checks_sha(tasks, root),
            "reviewer": reviewer, "task_ids": sorted(t.id for t in tasks)}
