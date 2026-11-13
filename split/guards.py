"""Runtime and replay guards for the Assignment 6 split."""
from __future__ import annotations

from pathlib import PurePosixPath
from harness.formats import LABELS, normalize_path, parse_triage_comment


class WaitGraph:
    def __init__(self):
        self.edges: dict[str, set[str]] = {}

    def wait(self, waiter: str, on: str, what: str = "") -> list[str] | None:
        self.edges.setdefault(waiter, set()).add(on)
        path = self._path(on, waiter, set())
        return [waiter, *path[:-1]] if path else None

    def _path(self, node: str, target: str, visited: set[str]) -> list[str] | None:
        if node == target:
            return [node]
        if node in visited:
            return None
        visited.add(node)
        for following in sorted(self.edges.get(node, ())):
            path = self._path(following, target, visited)
            if path:
                return [node, *path]
        return None

    def victim(self, cycle: list[str]) -> str:
        workers = [agent for agent in cycle if agent != "coordinator"]
        if not workers:
            raise ValueError("no worker in wait cycle")
        return sorted(workers)[-1]

    def done(self, waiter: str, on: str) -> None:
        self.edges.get(waiter, set()).discard(on)


class SharedState:
    def __init__(self, initial: dict[str, str]):
        self._values = {path: (content, 0) for path, content in initial.items()}

    def read(self, agent: str, path: str) -> tuple[str, int]:
        return self._values[path]

    def write(self, agent: str, path: str, content: str, version: int) -> bool:
        current, actual = self._values[path]
        if actual != version:
            return False
        self._values[path] = content, actual + 1
        return True

    def content(self, path: str) -> str:
        return self._values[path][0]


def check_combined(task, state: dict) -> list[str]:
    """Check task-wide publication invariants without using the answer key."""
    violations = []
    for issue in task.issues:
        row = state.get(issue, state.get(str(issue)))
        if not isinstance(row, dict):
            violations.append(f"#{issue}: missing end state")
            continue
        comments, labels, prs = (row.get(key) or [] for key in ("comments", "labels", "prs"))
        if len(comments) != 1:
            violations.append(f"#{issue}: expected one comment, got {len(comments)}")
            continue
        label, file = parse_triage_comment(comments[0])
        if label not in LABELS or not file:
            violations.append(f"#{issue}: invalid label or file line")
            continue
        file = normalize_path(file)
        if file != "none" and (file.startswith("/") or ".." in PurePosixPath(file).parts):
            violations.append(f"#{issue}: unsafe file path")
        if labels != [label]:
            violations.append(f"#{issue}: labels {labels!r} differ from comment {label!r}")
        if file == "none":
            if prs:
                violations.append(f"#{issue}: PR exists for file:none")
        elif len(prs) != 1:
            violations.append(f"#{issue}: expected one open PR, got {len(prs)}")
        elif not isinstance(prs[0], dict) or not any(
            file in str(prs[0].get(key, "")) or PurePosixPath(file).name in str(prs[0].get(key, ""))
            for key in ("title", "body")
        ):
            violations.append(f"#{issue}: PR does not name {file}")
    return violations
