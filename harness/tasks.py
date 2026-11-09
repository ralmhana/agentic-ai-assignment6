"""Assignment 6: the task set (checks/FORMATS.md, section 14.1).

A task is RepoMind's daily task on one issue (kind single) or on a batch of five
unrelated issues in one run (kind batch). Each task file in fixtures/tasks6/ names
its issues and their known answers:

    id: batch-a
    kind: batch
    issues: [4410, 4412, 4414, 4420, 4423]
    answers:
      4410: {label: bug, file: src/config.ts}
      ...

`run.py --tasks fixtures/tasks6` runs a way over every task in the folder. Without
--tasks, each issue that --set or --issues names is a task of its own, with the ID
dev-<n> on a development issue and issue-<n> on any other, so Assignments 1 to 5's
commands still run. A task's token budget is the per-issue budget times its number
of issues: run.py --budget B gives a batch 5*B.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from harness import ROOT
from harness.formats import LABELS, TASK_KINDS, normalize_path

BATCH_SIZE = 5


@dataclass(frozen=True)
class Task:
    id: str
    kind: str                       # single | batch
    issues: tuple[int, ...]
    answers: dict = field(default_factory=dict, compare=False, hash=False)   # issue -> {label, file}
    path: Path | None = field(default=None, compare=False, hash=False)

    @property
    def issue(self) -> int | None:
        """The task's one issue, for a single task; None for a batch."""
        return self.issues[0] if self.kind == "single" else None

    def budget(self, per_issue: int | None) -> int | None:
        """The task's token budget: per_issue times its number of issues; None for none."""
        return None if per_issue is None else int(per_issue) * len(self.issues)


def _answer(value) -> dict:
    label, file = str(value.get("label", "")).strip().lower(), value.get("file")
    if label not in LABELS:
        raise ValueError(f"an answer's label is one of {LABELS}, not {label!r}")
    return {"label": label, "file": normalize_path("none" if file is None else str(file))}


def load_task(path: Path | str) -> Task:
    path = Path(path)
    data = yaml.safe_load(path.read_text()) or {}
    kind, issues = data.get("kind"), [int(n) for n in data.get("issues") or []]
    if kind not in TASK_KINDS:
        raise ValueError(f"{path.name}: kind is one of {TASK_KINDS}, not {kind!r}")
    if kind == "single" and len(issues) != 1 or kind == "batch" and len(issues) != BATCH_SIZE:
        raise ValueError(f"{path.name}: a single task has one issue and a batch {BATCH_SIZE}, not {len(issues)}")
    answers = {int(k): _answer(v) for k, v in (data.get("answers") or {}).items()}
    if set(answers) != set(issues):
        raise ValueError(f"{path.name}: every issue needs its answer, and only its issues have one")
    return Task(str(data["id"]), kind, tuple(issues), answers, path)


def load_tasks(where: Path | str) -> list[Task]:
    """Every task in a folder (its *.yaml files, by ID), or the one task a file holds."""
    where = Path(where)
    if not where.is_absolute():
        where = ROOT / where
    paths = sorted(where.glob("*.yaml")) if where.is_dir() else [where]
    if not paths:
        raise SystemExit(f"no task files in {where}")
    tasks = sorted((load_task(p) for p in paths), key=lambda t: t.id)
    ids = [t.id for t in tasks]
    if len(set(ids)) != len(ids):
        raise SystemExit(f"two task files in {where} share an ID")
    return tasks


def known_answers(root: Path = ROOT) -> dict[int, dict]:
    """fixtures/answers.yaml's answers, for a task made from one issue."""
    path = Path(root) / "fixtures" / "answers.yaml"
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    out = {}
    for part in (data or {}).values():
        for k, v in (part or {}).items():
            out[int(k)] = _answer(v)
    return out


def issue_tasks(issues: list[int], root: Path = ROOT) -> list[Task]:
    """One single task per issue: dev-<n> on a development issue, issue-<n> on any other."""
    from harness.formats import RECORDED_ISSUES
    answers = known_answers(root)
    return [Task(f"dev-{n}" if n in RECORDED_ISSUES else f"issue-{n}", "single", (int(n),),
                 {int(n): answers[int(n)]} if int(n) in answers else {}) for n in issues]


def task_from_start(start: dict) -> Task:
    """The task a run_start line records, for a resume (answers are not needed to run)."""
    issues = tuple(int(n) for n in (start.get("issues") or [start.get("issue")]))
    return Task(str(start.get("task") or f"issue-{issues[0]}"), start.get("kind") or "single", issues)


def end_state(tracker, run_id: str, task: Task) -> dict:
    """The task's end state as one run left it, read from the tracker (section 14.6):
    for each issue, the run's comments' bodies, the labels still on it, and its open
    pull requests' titles and bodies. Your check of the combined result reads this,
    so the same check runs on a live run and on fixtures/planted6/."""
    prs = tracker.prs(run_id, state="open")
    return {int(n): {"comments": [c["body"] for c in tracker.comments(run_id=run_id, issue=n)],
                     "labels": [row["label"] for row in tracker.labels(run_id, issue=n)],
                     "prs": [{"title": p["title"], "body": p["body"]} for p in prs if int(p["issue"]) == int(n)]}
            for n in task.issues}
