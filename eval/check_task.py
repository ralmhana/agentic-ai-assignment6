"""Assignment 6: the grounded check of one run on one task (checks/FORMATS.md, section 14.7).

It reads the tracker, never a model's words. For each of the task's issues, the run
passes that issue when it left:

  - exactly one comment on it, whose label and file lines match the known answer;
  - that label applied to the issue, and no other label still on it;
  - one open draft pull request for it whose title or body names the file, when the
    answer's file is not none, and none when it is.

A task passes when every one of its issues does: a single task's one, a batch's five.

    from eval.check_task import check_task
    from harness.tasks import load_task
    result = check_task(run_id, load_task("fixtures/tasks6/batch-a.yaml"))
    result["passed"], result["parts"]        # True or False; {issue: True or False}
"""

from __future__ import annotations

from pathlib import PurePosixPath

from harness.formats import normalize_path, parse_triage_comment
from harness.tracker import Tracker


def _names(text: str, file: str) -> bool:
    text = (text or "").lower()
    return file.lower() in text or PurePosixPath(file).name.lower() in text


def check_issue(tracker: Tracker, run_id: str, issue: int, answer: dict) -> dict:
    """One issue of one run: passed, and what was wrong if it did not."""
    why = []
    want_label, want_file = answer["label"], normalize_path(answer["file"]) or "none"
    comments = tracker.comments(run_id=run_id, issue=issue)
    label = file = None
    if len(comments) != 1:
        why.append(f"{len(comments)} comments, not one")
    else:
        label, file = parse_triage_comment(comments[0]["body"])
        if label != want_label:
            why.append(f"the comment's label is {label!r}, not {want_label!r}")
        if file != want_file:
            why.append(f"the comment's file is {file!r}, not {want_file!r}")
    applied = sorted({row["label"].strip().lower() for row in tracker.labels(run_id, issue=issue)})
    if applied != [want_label]:
        why.append(f"labels on the issue {applied}, not [{want_label!r}]")
    prs = [p for p in tracker.prs(run_id, state="open") if int(p["issue"]) == int(issue)]
    if want_file == "none":
        if prs:
            why.append(f"{len(prs)} pull requests, where the file is none")
    elif len(prs) != 1:
        why.append(f"{len(prs)} open pull requests, not one")
    elif not _names(f"{prs[0]['title']}\n{prs[0]['body']}", want_file):
        why.append(f"the pull request does not name {want_file}")
    return {"issue": int(issue), "passed": not why, "why": why, "label": label, "file": file,
            "prs": len(prs), "comments": len(comments)}


def check_task(run_id: str, task, tracker: Tracker | None = None) -> dict:
    """One run on one task: passed when every issue passed; parts by issue."""
    tracker = tracker or Tracker(flaky=False, readback_fail=False)
    details = [check_issue(tracker, run_id, n, task.answers[n]) for n in task.issues]
    return {"run_id": run_id, "task": task.id, "kind": task.kind, "passed": all(d["passed"] for d in details),
            "parts": {d["issue"]: d["passed"] for d in details}, "details": details}
