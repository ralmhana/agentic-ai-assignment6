#!/usr/bin/env python3
"""Assignment 6 checker. Run it with `make check-06`, on main.

It reads only the environment. Three of its checks replay recorded runs into your
guards (split/guards.py), taken from your lab-06-split-final tag and run in a
scratch copy, in a process of their own; they never touch your runs. The others
read what your runs left: runs/, the tracker's database and its archives,
results/runs_06.jsonl, your contract's schema from the tag, git's history of main,
and reports/LAB_06.json. It never asks a model anything and never trusts a model's
words: a pass is recomputed from the tracker, a spend from the run_end lines.

Assignment 6 is scored out of 100. The checker awards the automated 80; staff read
the report and the decision record for the other 20. It also prints integrity
flags, which carry no points and go to staff. Every format it reads is defined in
checks/FORMATS.md, section 14.

    python checks/check_06.py                # on main: the guards from the tag lab-06-split-final
    python checks/check_06.py --here         # on lab-06-split: the guards from the working tree
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness import LAB  # noqa: E402
from harness.backends import REAL_BACKENDS  # noqa: E402
from harness.clock import parse  # noqa: E402
from harness.formats import (ANOMALIES, ARMS, CONTRACT_FIELDS, CONTRACT_STATUSES, GATE_VERDICTS,  # noqa: E402
                             MAST_CATEGORIES, TOPOLOGIES)
from harness.roles import arg, role_of  # noqa: E402
from harness.runner import is_free, is_trace  # noqa: E402
from harness.schema import errors as schema_errors  # noqa: E402
from harness.tasks import load_tasks  # noqa: E402
from harness.trace import read_trace  # noqa: E402

TASK_DIR = "fixtures/tasks6"
TAG = "lab-06-split-final"
SWEEPS = 3
REPLAY_TIMEOUT_S = 60
SPEND_TOLERANCE = 0.25       # S-plus's mean spend against M's, on each kind of task
MATCH_TOLERANCE = 0.01       # an S-plus run's budget against M's mean on its task; tokens by agent
SPLIT_CODE = ("ways/split.py", "ways/splus.py", "split/", "eval/results_06.py")
MAIN_MAY_CHANGE = ("decisions/", "reports/", "runs/", "results/", "tracker/", "logs/", "CHANGES.md")
MODEL_KEYS = ("provider", "model", "base_url", "api_key_env")
# The course's files your runs and these checks depend on, hashed: a change to one is an integrity flag.
HARNESS_SHA = {
    "run.py": "710c94c7eef692a7",
    "harness/runner.py": "c77c8da3b7ed9398",
    "harness/tasks.py": "c7fd3d631ab4c7f5",
    "harness/constants.py": "4ac6ab3b61e89561",
    "harness/trace.py": "7324d3dd3ca69973",
    "harness/client.py": "d406659a650922be",
    "harness/tracker.py": "72133335f7155ddc",
    "harness/formats.py": "079fdaa16bc71d25",
    "harness/schema.py": "7be7934785acea74",
    "harness/scripted.py": "4d8967d9981caadf",
    "harness/roles.py": "bf30eb5b76543c23",
    "eval/check_task.py": "fe77ab6cc1b66d17",
    "eval/check_triage.py": "8fd8d513d8b2e16b",
    "ways/agent.py": "e7acbbfd3eff4fcf",
    "prompts/agent.md": "60525022dd2f7ba1",
    "agent/loop.py": "37821b60586d9d57",
    "agent/bounds.yaml": "949e7b61c1cefe34",
    "fixtures/tasks6/one-4402.yaml": "1e5e204925e50e2d",
    "fixtures/tasks6/one-4403.yaml": "b61d6f2faa7faab5",
    "fixtures/tasks6/one-4405.yaml": "b778d0ee1f5b7bd5",
    "fixtures/tasks6/one-4406.yaml": "89bfc50c8bda9c7b",
    "fixtures/tasks6/one-4409.yaml": "3162f69ca3ae0720",
    "fixtures/tasks6/one-4413.yaml": "4766e699d678cce0",
    "fixtures/tasks6/batch-a.yaml": "8145f8d69396ed1a",
    "fixtures/tasks6/batch-b.yaml": "bc4f0f9bd1e50d71",
    "fixtures/traces6/deadlock.jsonl": "4f3204b5c1dd6de0",
    "fixtures/traces6/no_deadlock.jsonl": "3c546aeb4d23c8b3",
    "fixtures/traces6/lost_update.jsonl": "ef855c68f681c32c",
    "fixtures/planted6/wrong.json": "126a1cf56807f50b",
    "fixtures/planted6/right.json": "0fb1fa2c52db4a45",
}


@dataclass
class Section:
    name: str
    possible: float
    earned: float = 0.0
    notes: list[str] = field(default_factory=list)
    manual: bool = False

    def note(self, text: str) -> None:
        self.notes.append(text)

    def award(self, points: float, ok: bool, failed: str) -> bool:
        if ok:
            self.earned += points
        else:
            self.note(failed)
        return ok


def raised(what: str) -> str:
    return f"{what} raised:\n" + traceback.format_exc(limit=3)


def sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def jsonl(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    out = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def git(*args: str, check: bool = False) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout if done.returncode == 0 else ""


# -- the environment: your runs, the tracker's databases ---------------------------------------------

@dataclass
class Run:
    run_id: str
    start: dict
    records: list[dict]

    @property
    def way(self) -> str:
        return self.start.get("way")

    @property
    def arm(self) -> str | None:
        return ARMS.get(self.way)

    @property
    def task(self) -> str:
        return self.start.get("task")

    @property
    def kind(self) -> str:
        return self.start.get("kind")

    @property
    def sweep(self):
        return self.start.get("sweep")

    @property
    def end(self) -> dict | None:
        return self.records[-1] if self.records and self.records[-1].get("type") == "run_end" else None

    @property
    def finished(self) -> bool:
        ends = [r.get("terminal_reason") for r in self.records if r.get("type") == "end"]
        return self.end is not None and not {"quota", "rate_limited"} & set(ends)

    @property
    def tokens(self) -> int:
        return int(((self.end or {}).get("totals") or {}).get("total_tokens") or 0)

    @property
    def wall_s(self) -> float:
        return float((self.end or {}).get("elapsed_s") or 0.0)

    def lines(self, kind: str) -> list[dict]:
        return [r for r in self.records if r.get("type") == kind]


def load_runs(task_ids: set[str], root: Path = ROOT) -> tuple[list[Run], int]:
    """Assignment 6's finished-or-not runs on the task set, on any backend that is not scripted."""
    runs, scripted = [], 0
    for path in sorted((root / "runs").glob("*.jsonl")):
        if not is_trace(path):
            continue
        try:
            records = read_trace(path)
        except json.JSONDecodeError:
            continue
        start = records[0] if records and records[0].get("type") == "run_start" else None
        if not start or start.get("lab") != LAB or start.get("task") not in task_ids:
            continue
        if is_free(start.get("backend") or ""):
            scripted += 1
            continue
        runs.append(Run(start.get("run_id") or path.stem, start, records))
    return runs, scripted


class Remote:
    """The tracker's database and its archives, read as one tracker, for the grounded check."""

    TABLES = ("comments", "prs", "labels")

    def __init__(self, root: Path = ROOT):
        self.rows: dict[str, dict[str, list[dict]]] = {t: {} for t in self.TABLES}
        self.files = [p for p in [root / "tracker" / "tracker.db", *sorted((root / "tracker" / "archive").glob("*.db"))]
                      if p.exists()]
        for path in self.files:
            db = sqlite3.connect(path)
            db.row_factory = sqlite3.Row
            try:
                for table in self.TABLES:
                    try:
                        for row in db.execute(f"SELECT * FROM {table} ORDER BY id"):
                            self.rows[table].setdefault(row["run_id"], []).append(dict(row))
                    except sqlite3.OperationalError:
                        continue
            finally:
                db.close()

    # the three reads eval/check_task.py makes, over every database
    def comments(self, run_id: str, issue: int | None = None) -> list[dict]:
        return [r for r in self.rows["comments"].get(run_id, []) if issue is None or int(r["issue"]) == int(issue)]

    def labels(self, run_id: str, issue: int | None = None, active: bool = True) -> list[dict]:
        return [r for r in self.rows["labels"].get(run_id, [])
                if (issue is None or int(r["issue"]) == int(issue)) and (not active or r.get("removed_at") is None)]

    def prs(self, run_id: str, branch: str | None = None, state: str | None = "open") -> list[dict]:
        return [r for r in self.rows["prs"].get(run_id, [])
                if (branch is None or r["branch"] == branch) and (state is None or r.get("state") == state)]


def grounded(remote: Remote, run: Run, tasks: dict) -> dict:
    from eval.check_task import check_task
    return check_task(run.run_id, tasks[run.task], tracker=remote)


# -- the split's code, from the tag ------------------------------------------------------------------

def _inside(member: tarfile.TarInfo, dest: str) -> tarfile.TarInfo | None:
    """tarfile's data filter, but a member it refuses (a link to an absolute path, say a
    committed .venv) is left out rather than ending the check."""
    try:
        return tarfile.data_filter(member, dest)
    except tarfile.FilterError:
        return None


class SplitTree:
    """Your lab-06-split-final tag, unpacked in a scratch directory (or, with --here, this working tree)."""

    def __init__(self, tmp: Path, here: bool):
        self.root = tmp / "split"
        self.source = None
        if here:
            shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns(".git", ".venv", "runs", "tracker",
                                                                           "__pycache__", "*.pyc"))
            self.source = "this working tree (--here)"
            return
        data = subprocess.run(["git", "archive", "--format=tar", TAG], cwd=ROOT, capture_output=True)
        if data.returncode != 0:
            raise FileNotFoundError(f"no tag {TAG}: tag the last commit of lab-06-split and push it "
                                    f"(on lab-06-split itself, run `python checks/check_06.py --here`)")
        self.root.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(data.stdout)) as tar:
            tar.extractall(self.root, filter=_inside) if hasattr(tarfile, "data_filter") else tar.extractall(self.root)
        self.source = f"the tag {TAG}"

    def schema(self) -> dict | None:
        path = self.root / "split" / "contract.schema.json"
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def replay(self) -> dict:
        """The three replays, in a process of their own, on the tag's split/guards.py."""
        env = {k: v for k, v in os.environ.items()}
        env["PYTHONPATH"] = str(self.root)
        done = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--replay", str(self.root), str(ROOT)],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=REPLAY_TIMEOUT_S)
        try:
            return json.loads(done.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            return {"error": (done.stderr or done.stdout or "no output").strip()[-1500:]}


# -- the replays, run in their own process: python check_06.py --replay <tree> <course root> ------------

def replays(tree: Path, course: Path) -> dict:
    sys.path.insert(0, str(tree))
    out: dict = {}
    try:
        import importlib
        guards = importlib.import_module("split.guards")
    except Exception:
        return {"error": "split/guards.py could not be imported:\n" + traceback.format_exc(limit=3)}
    fixtures = course / "fixtures"

    # deadlock: slide 38
    try:
        lines = [r for r in read_trace(fixtures / "traces6" / "deadlock.jsonl") if r.get("type") == "wait"]
        graph = guards.WaitGraph()
        found = None
        for line in lines:
            cycle = graph.wait(line["waiter"], line["on"], line.get("what", ""))
            if cycle:
                found = {"turn": line.get("turn"), "cycle": [str(a) for a in cycle],
                         "victim": str(graph.victim(list(cycle)))}
                break
        out["deadlock"] = found
        graph = guards.WaitGraph()
        false = []
        for line in [r for r in read_trace(fixtures / "traces6" / "no_deadlock.jsonl") if r.get("type") == "wait"]:
            cycle = graph.wait(line["waiter"], line["on"], line.get("what", ""))
            if cycle:
                false.append([str(a) for a in cycle])
        out["no_deadlock"] = false
    except Exception:
        out["deadlock_error"] = traceback.format_exc(limit=3)

    # lost update: Activity 4, Alternate A
    try:
        records = read_trace(fixtures / "traces6" / "lost_update.jsonl")
        initial = records[0]["initial"]
        path = next(iter(initial))
        state = guards.SharedState(dict(initial))
        seen: dict[str, int] = {}
        writes = []
        contents = {}
        for line in sorted((r for r in records if r.get("type") == "tool_call" and r.get("name") in
                            ("read_file", "write_file")), key=lambda r: r["at"]):
            agent = line["agent"]
            if line["name"] == "read_file":
                _, version = state.read(agent, line["input"]["path"])
                seen[agent] = version
            else:
                ok = state.write(agent, line["input"]["path"], line["input"]["content"], seen[agent])
                writes.append([agent, bool(ok)])
                contents[agent] = line["input"]["content"]
        held = state.content(path)
        out["lost_update"] = {"writes": writes, "keeps_a": held == contents.get("worker-a")}
        text, version = state.read("worker-b", path)
        lint = text.replace("{timeout: 120000}", "{ timeout: 120000 }")
        again = state.write("worker-b", path, lint, version)
        out["lost_update"]["reread_written"] = bool(again) and state.content(path) == lint
    except Exception:
        out["lost_update_error"] = traceback.format_exc(limit=3)

    # the combined result: fixtures/planted6
    try:
        from harness.tasks import Task
        results = {}
        for name in ("wrong", "right"):
            data = json.loads((fixtures / "planted6" / f"{name}.json").read_text())
            t = data["task"]
            task = Task(t["id"], t["kind"], tuple(int(n) for n in t["issues"]), {})
            state = {int(k): v for k, v in data["end_state"].items()}
            results[name] = [str(v) for v in (guards.check_combined(task, state) or [])]
        out["combined"] = results
    except Exception:
        out["combined_error"] = traceback.format_exc(limit=3)
    return out


# -- the checks ----------------------------------------------------------------------------------------

def main_ref() -> str:
    return "main" if git("rev-parse", "--verify", "--quiet", "main").strip() else "HEAD"


def check_nothing_merged() -> Section:
    sec = Section("Nothing merged", 8)
    ref = main_ref()
    roots = git("rev-list", "--max-parents=0", ref).split()
    if not roots:
        sec.note("no git history: this row reads main's history against your first commit")
        return sec
    first = roots[-1]
    if not git("rev-parse", "--verify", "--quiet", TAG).strip():
        sec.note(f"no tag {TAG} yet: there is no split to have kept off main")
        return sec
    files = git("ls-tree", "-r", "--name-only", ref).splitlines()
    split_code = sorted({f for f in files for p in SPLIT_CODE if f == p or (p.endswith("/") and f.startswith(p))})
    sec.award(4, not split_code, f"main holds split code: {', '.join(split_code[:6])}")
    changed = [f for f in git("diff", "--name-only", first, ref).splitlines() if f]
    outside = []
    for f in changed:
        if f.startswith(MAIN_MAY_CHANGE) or f in MAIN_MAY_CHANGE:
            continue
        if f in ("settings.yaml", "pricing.yaml"):
            diff = git("diff", "-U0", first, ref, "--", f)
            touched = [d[1:].strip() for d in diff.splitlines()
                       if d[:1] in "+-" and not d.startswith(("+++", "---")) and d[1:].strip()
                       and not d[1:].strip().startswith("#")]
            if f == "settings.yaml":
                bad = [d for d in touched if d.split(":", 1)[0].strip() not in MODEL_KEYS]
            else:
                bad = [d for d in diff.splitlines() if d.startswith("-") and not d.startswith("---") and d[1:].strip()]
            if bad:
                outside.append(f"{f} (beyond your model's lines: {bad[0][:60]})")
            continue
        outside.append(f)
    sec.award(4, not outside, "main changed outside decisions/, reports/, runs/, results/, tracker/, CHANGES.md and "
                              f"your model's lines: {', '.join(outside[:6])}")
    return sec


def check_prediction(runs: list[Run]) -> Section:
    sec = Section("Prediction first", 6)
    ref, rel = main_ref(), "reports/PREDICTIONS_06.md"
    added = [line.split() for line in git("log", ref, "--diff-filter=A", "--format=%H %cI", "--", rel).splitlines()
             if line.strip()]
    if not added:
        sec.note(f"{rel} was never committed on main")
        return sec
    commits = git("log", ref, "--format=%H", "--", rel).split()
    from datetime import datetime
    when = datetime.fromisoformat(added[-1][1])
    split_starts = [parse(r.start["started_at"]) for r in runs if r.way == "split" and r.start.get("started_at")]
    if not split_starts:
        sec.note("no split runs on the task set yet, so nothing to come after the prediction")
        return sec
    first_run = min(split_starts)
    ok = when is not None and when < first_run
    sec.award(3, ok, f"the prediction was committed at {added[-1][1]}, after the first split run started "
                     f"({first_run.isoformat()})")
    sec.award(3, ok and len(commits) == 1, f"{rel} changed in {len(commits) - 1} later commit(s) on main")
    return sec


def worker_facts(run: Run, worker: str, before: int | None = None) -> tuple[int, set[str]]:
    """The worker's calls to the registry's tools (its return tool is not one), before
    the record at index `before`, and the queries and paths among them."""
    records = run.records[:before] if before is not None else run.records
    calls = [r for r in records if r.get("type") == "tool_call" and r.get("agent") == worker
             and role_of(r.get("name") or "")]
    searched = set()
    for c in calls:
        role = role_of(c.get("name") or "")
        inp = c.get("input") or {}
        if role == "search":
            value = inp.get(arg("search", "query"))
        elif role == "read_file":
            value = inp.get(arg("read_file", "path"))
        else:
            continue
        if value is not None:
            searched.add(str(value))
    return len(calls), searched


def check_contract(m_runs: list[Run], tree: SplitTree | None) -> Section:
    sec = Section("Return contract", 10)
    schema = tree.schema() if tree else None
    if schema is None:
        sec.note("split/contract.schema.json could not be read from the split's code")
        return sec
    if not m_runs:
        sec.note("no finished split runs on the task set")
        return sec
    agree, facts, every = [], [], []
    for run in m_runs:
        returns = [(i, r) for i, r in enumerate(run.records) if r.get("type") == "worker_return"]
        if not returns:
            every.append(run.run_id)
        for at, r in returns:
            contract = r.get("contract")
            errs = schema_errors(contract, schema)
            missing = [f for f in CONTRACT_FIELDS if not isinstance(contract, dict) or f not in contract]
            really = not errs and not missing and contract.get("status") in CONTRACT_STATUSES
            if bool(r.get("valid")) != really:
                agree.append(f"{run.run_id} {r.get('worker')}: marked {'valid' if r.get('valid') else 'invalid'}, "
                             f"and {'it fits' if really else (errs + missing)[:1]}")
            if really and r.get("valid"):
                calls, searched = worker_facts(run, str(r.get("worker")), at)
                said = {str(s) for s in contract.get("searched") or []}
                if contract.get("calls_used") != calls or said != searched:
                    facts.append(f"{run.run_id} {r.get('worker')}: calls_used {contract.get('calls_used')} against "
                                 f"{calls} tool calls; searched {sorted(said)[:3]} against {sorted(searched)[:3]}")
    sec.award(4, not agree, "a return's valid flag disagrees with your schema: " + "; ".join(agree[:3]))
    sec.award(4, not facts, "a valid return's calls or searched list is not the worker's own: " + "; ".join(facts[:3]))
    sec.award(2, not every, f"{len(every)} split runs recorded no worker_return: {', '.join(every[:3])}")
    return sec


def check_deadlock(result: dict) -> Section:
    sec = Section("Deadlock caught", 8)
    if "error" in result or "deadlock_error" in result:
        sec.note(result.get("error") or result.get("deadlock_error"))
        return sec
    found = result.get("deadlock")
    workers = {"patch-worker", "test-worker"}
    ok = bool(found) and found["turn"] is not None and int(found["turn"]) <= 2 and workers <= set(found["cycle"]) \
        and found["victim"] in workers
    sec.award(6, ok, f"the recorded deadlock: {found or 'no cycle was ever returned'}" if not ok else "")
    sec.award(2, not result.get("no_deadlock"),
              f"a cycle was returned where the waits never form one: {result.get('no_deadlock')}")
    return sec


def check_lost_update(result: dict) -> Section:
    sec = Section("Lost update refused", 8)
    if "error" in result or "lost_update_error" in result:
        sec.note(result.get("error") or result.get("lost_update_error"))
        return sec
    lu = result.get("lost_update") or {}
    ok = lu.get("writes") == [["worker-a", True], ["worker-b", False]] and lu.get("keeps_a")
    sec.award(6, bool(ok), f"replayed in time order, the writes came back {lu.get('writes')}, and the file "
                           f"{'kept' if lu.get('keeps_a') else 'did not keep'} Worker A's fix")
    sec.award(2, bool(lu.get("reread_written")), "Worker B, reading again and writing with the new version, "
                                                 "was refused or the file does not hold its write")
    return sec


def check_combined(result: dict) -> Section:
    sec = Section("Combined result", 8)
    if "error" in result or "combined_error" in result:
        sec.note(result.get("error") or result.get("combined_error"))
        return sec
    c = result.get("combined") or {}
    sec.award(5, bool(c.get("wrong")), "your check passes the planted end state, whose combined result is wrong")
    sec.award(3, c.get("right") == [], f"your check fails the correct end state: {c.get('right')}")
    return sec


def check_one_trace(m_runs: list[Run]) -> Section:
    sec = Section("One trace", 6)
    if not m_runs:
        sec.note("no finished split runs on the task set")
        return sec
    unnamed, sums = [], []
    for run in m_runs:
        lines = run.lines("model_call") + run.lines("tool_call")
        named = [r for r in run.records if isinstance(r.get("agent"), str)]      # every line an agent wrote
        agents = {r["agent"] for r in named}
        bad = [r for r in lines if not isinstance(r.get("agent"), str) or "parent" not in r]
        roots = {r["agent"] for r in named if r.get("parent") is None}
        orphans = {r.get("parent") for r in named if r.get("parent") is not None} - agents
        if bad or not roots or orphans:
            unnamed.append(f"{run.run_id}: {len(bad)} lines without agent and parent"
                           + (f"; parents never seen {sorted(map(str, orphans))[:2]}" if orphans else "")
                           + ("; no coordinator (parent none)" if not roots else ""))
        by_agent: dict[str, int] = {}
        for r in run.lines("model_call"):
            u = r.get("usage") or {}
            by_agent[str(r.get("agent"))] = by_agent.get(str(r.get("agent")), 0) + int(u.get("prompt_tokens") or 0) \
                + int(u.get("output_tokens") or 0)
        total = run.tokens
        if total and abs(sum(by_agent.values()) - total) > MATCH_TOLERANCE * total:
            sums.append(f"{run.run_id}: agents' tokens {sum(by_agent.values()):,} against run_end's {total:,}")
    sec.award(3, not unnamed, "; ".join(unnamed[:3]))
    sec.award(3, not sums, "; ".join(sums[:3]))
    return sec


def mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def check_budget(by_arm: dict[str, list[Run]], tasks: dict) -> Section:
    sec = Section("Budget", 10)
    s, m, sp = by_arm["S"], by_arm["M"], by_arm["S_plus"]
    differ = []
    for tid in tasks:
        ceilings = {r.start.get("ceiling") for r in s + m if r.task == tid}
        if len(ceilings) > 1:
            differ.append(f"{tid}: {sorted(map(str, ceilings))}")
    sec.award(3, bool(s and m) and not differ, "arms S and M do not carry one ceiling per task: "
              + ("; ".join(differ[:3]) if differ else "one of the arms has no runs"))
    off = []
    for run in sp:
        earlier = [r.tokens for r in m if r.task == run.task and r.start.get("started_at", "") < run.start.get("started_at", "")]
        want = mean(earlier)
        got = run.start.get("budget")
        if run.start.get("matched_to") != "split" or not want or not got or abs(got - want) > MATCH_TOLERANCE * want:
            off.append(f"{run.run_id}: budget {got}, arm M's mean before it {round(want)}")
    sec.award(3, bool(sp) and not off, "an S-plus run's budget is not arm M's mean spend on its task: "
              + ("; ".join(off[:3]) if off else "no S-plus runs"))
    gaps = []
    for kind in ("single", "batch"):
        mm, ss = mean(r.tokens for r in m if r.kind == kind), mean(r.tokens for r in sp if r.kind == kind)
        s_mean = mean(r.tokens for r in s if r.kind == kind)
        if not mm or not ss:
            gaps.append(f"{kind}: no runs to compare")
        elif ss > (1 + SPEND_TOLERANCE) * mm or (mm > s_mean and ss < (1 - SPEND_TOLERANCE) * mm):
            gaps.append(f"{kind}: S-plus {round(ss):,} against M {round(mm):,}")     # under it only where M spent more than S
    sec.award(2, not gaps, "arm S-plus's mean spend is more than 25% over arm M's, or, where arm M spent more than "
              "arm S, more than 25% under it: " + "; ".join(gaps))
    want = SWEEPS * len(tasks)
    short = [f"{arm} {len(runs)}" for arm, runs in by_arm.items() if len(runs) != want]
    sec.award(2, not short, f"each arm needs {want} finished runs on the task set: {', '.join(short)}")
    return sec


def check_constants(by_arm: dict[str, list[Run]], report: dict) -> Section:
    sec = Section("Constants recorded", 6)
    every = [r for runs in by_arm.values() for r in runs]
    seen = {json.dumps(r.start.get("constants"), sort_keys=True) for r in every}
    one = len(seen) == 1 and every
    sec.award(4, bool(one), f"the runs carry {len(seen)} different sets of constants" if every else "no runs")
    if one:
        recorded = json.loads(next(iter(seen)))
        sec.award(2, report.get("constants") == recorded,
                  f"reports/LAB_06.json's constants are not the runs' ({json.dumps(recorded)[:160]})")
    else:
        sec.note("reports/LAB_06.json's constants are compared once the runs agree")
    return sec


def summarize(runs: list[Run], passed: dict[str, bool]) -> dict:
    out = {}
    for kind in ("single", "batch"):
        mine = [r for r in runs if r.kind == kind]
        per_task: dict[str, int] = {}
        sweeps: dict = {}
        for r in mine:
            per_task[r.task] = per_task.get(r.task, 0) + int(passed[r.run_id])
            sweeps[r.sweep] = sweeps.get(r.sweep, 0) + int(passed[r.run_id])
        tasks = sorted({r.task for r in mine})
        out[kind] = {"runs": len(mine), "passes": sum(int(passed[r.run_id]) for r in mine), "per_task": per_task,
                     "sweep_min": min(sweeps.values()) if sweeps else 0, "sweep_max": max(sweeps.values()) if sweeps else 0,
                     "all_three": sum(1 for t in tasks if per_task.get(t, 0) >= SWEEPS),
                     "mean_tokens": round(mean(r.tokens for r in mine)),
                     "mean_wall_s": round(mean(r.wall_s for r in mine), 1)}
    return out


def check_results(by_arm: dict[str, list[Run]], tasks: dict, remote: Remote, report: dict) -> tuple[Section, dict]:
    sec = Section("Results recompute", 10)
    every = [r for runs in by_arm.values() for r in runs]
    checked = {r.run_id: grounded(remote, r, tasks) for r in every}
    passed = {k: v["passed"] for k, v in checked.items()}
    lines = {row.get("run_id"): row for row in jsonl(ROOT / "results" / "runs_06.jsonl")}
    missing = [r.run_id for r in every if r.run_id not in lines]
    sec.award(2, bool(every) and not missing, f"results/runs_06.jsonl lacks {len(missing)} finished runs: "
              f"{', '.join(missing[:3])}" if every else "no finished runs on the task set")
    wrong = []
    for r in every:
        row = lines.get(r.run_id)
        if row is None:
            continue
        parts = {str(k): v for k, v in (row.get("parts") or {}).items()}
        want = {str(k): v for k, v in checked[r.run_id]["parts"].items()}
        if row.get("passed") != passed[r.run_id] or parts != want or row.get("arm") != r.arm:
            wrong.append(f"{r.run_id}: says {row.get('passed')}, the tracker {passed[r.run_id]}")
    sec.award(4, bool(lines) and not wrong, "results/runs_06.jsonl disagrees with the grounded check: "
              + "; ".join(wrong[:3]) if wrong or not lines else "")
    computed = {arm: summarize(runs, passed) for arm, runs in by_arm.items()}
    stated = (report.get("arms") or {}) if isinstance(report.get("arms"), dict) else {}
    off = []
    for arm, kinds in computed.items():
        for kind, want in kinds.items():
            got = ((stated.get(arm) or {}).get(kind) or {})
            for key in ("runs", "passes"):
                if got.get(key) != want[key]:
                    off.append(f"{arm} {kind} {key}: {got.get(key)} against {want[key]}")
            if not want["mean_tokens"] or abs((got.get("mean_tokens") or 0) - want["mean_tokens"]) > \
                    MATCH_TOLERANCE * want["mean_tokens"]:
                off.append(f"{arm} {kind} mean_tokens: {got.get('mean_tokens')} against {want['mean_tokens']}")
    sec.award(4, not off, "reports/LAB_06.json's arms do not recompute: " + "; ".join(off[:4]))
    return sec, computed


def measured(report: dict, computed: dict) -> list[str]:
    """What the runs measured, recomputed: for staff reading the report beside it."""
    notes = []
    for arm in ("S", "M", "S_plus"):
        for kind in ("single", "batch"):
            c = (computed.get(arm) or {}).get(kind) or {}
            if c.get("runs"):
                notes.append(f"{arm:<6} {kind:<6} passes {c['passes']}/{c['runs']} (sweeps {c['sweep_min']} to "
                             f"{c['sweep_max']}), mean {c['mean_tokens']:,} tokens, {c['mean_wall_s']} s")
    for kind in ("single", "batch"):
        s, m = ((computed.get("S") or {}).get(kind) or {}), ((computed.get("M") or {}).get(kind) or {})
        if s.get("mean_tokens") and m.get("mean_tokens"):
            notes.append(f"multiplier, {kind}: {m['mean_tokens'] / s['mean_tokens']:.2f} recomputed; "
                         f"{(report.get('multiplier') or {}).get(kind)} reported")
    return notes


def staff_notes(report: dict, computed: dict) -> list[str]:
    """What staff should look at: fields the report gives in a form section 14.8 does not name."""
    notes = []
    gates = report.get("gates") or {}
    for kind in ("daily", "batch"):
        v = gates.get(kind)
        if not (isinstance(v, list) and len(v) == 4 and all(x in GATE_VERDICTS for x in v)):
            notes.append(f"gates.{kind} is not four of {GATE_VERDICTS}: {v}")
    for f in report.get("failures") or []:
        if f.get("anomaly") not in ANOMALIES or f.get("mast") not in MAST_CATEGORIES:
            notes.append(f"a failure's anomaly or MAST category is not one of the names: {f}")
    decision = report.get("decision") or {}
    if any(decision.get(k) not in TOPOLOGIES for k in ("single", "batch")):
        notes.append(f"decision.single and decision.batch are each one of {TOPOLOGIES}: {decision}")
    if not (ROOT / "decisions" / "0006-topology.md").exists():
        notes.append("decisions/0006-topology.md is missing on main")
    return notes


def integrity_flags(runs: list[Run]) -> list[str]:
    flags = []
    others = sorted({r.start.get("backend") for r in runs if r.start.get("backend") not in REAL_BACKENDS})
    if others:
        flags.append(f"runs scored here came from a backend that is not a vendor's: {', '.join(map(str, others))}")
    for rel, wanted in HARNESS_SHA.items():
        if wanted and sha(ROOT / rel) != wanted:
            flags.append(f"`{rel}` differs from the course's copy: the runs, the arms or these checks depend on it")
    models = {r.start.get("model") for r in runs}
    if len(models) > 1:
        flags.append(f"the runs name {len(models)} models: {', '.join(sorted(map(str, models)))}")
    return flags


def main(argv: list[str]) -> int:
    if argv[:1] == ["--replay"]:
        print(json.dumps(replays(Path(argv[1]), Path(argv[2]))))
        return 0
    here = "--here" in argv
    report_path = ROOT / "reports" / "LAB_06.json"
    try:
        report = json.loads(report_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"reports/LAB_06.json could not be read ({exc}); checking what can be checked without it.\n")
        report = {}
    if not isinstance(report, dict):
        report = {}
    tasks = {t.id: t for t in load_tasks(ROOT / TASK_DIR)}
    runs, scripted = load_runs(set(tasks))
    finished = [r for r in runs if r.finished and r.arm]
    by_arm = {arm: [r for r in finished if r.arm == arm] for arm in ("S", "M", "S_plus")}
    remote = Remote()
    sections, computed = [], {}
    with tempfile.TemporaryDirectory() as tmpdir:
        tree, result = None, {}
        try:
            tree = SplitTree(Path(tmpdir), here)
            result = tree.replay()
        except FileNotFoundError as exc:
            result = {"error": str(exc)}
        except subprocess.TimeoutExpired:
            result = {"error": f"the replays did not finish within {REPLAY_TIMEOUT_S} s"}
        except Exception:
            result = {"error": raised("reading the split's code")}
        checks = [
            (check_nothing_merged, "Nothing merged", 8),
            (lambda: check_prediction(runs), "Prediction first", 6),
            (lambda: check_contract(by_arm["M"], tree), "Return contract", 10),
            (lambda: check_deadlock(result), "Deadlock caught", 8),
            (lambda: check_lost_update(result), "Lost update refused", 8),
            (lambda: check_combined(result), "Combined result", 8),
            (lambda: check_one_trace(by_arm["M"]), "One trace", 6),
            (lambda: check_budget(by_arm, tasks), "Budget", 10),
            (lambda: check_constants(by_arm, report), "Constants recorded", 6),
        ]
        for check, name, pts in checks:
            try:
                sections.append(check())
            except Exception:
                sections.append(Section(name, pts, notes=[raised("this check")]))
        try:
            sec, computed = check_results(by_arm, tasks, remote, report)
            sections.append(sec)
        except Exception:
            sections.append(Section("Results recompute", 10, notes=[raised("this check")]))
        source = tree.source if tree else "nothing: the split's code could not be read"
    sections.append(Section("Read and decided", 20, manual=True,
                            notes=["read by staff from reports/LAB_06.md and decisions/0006-topology.md"]))

    backends = sorted({str(r.start.get("backend")) for r in runs})
    print(f"Assignment 6 check · runs read from runs/ · backends seen: {', '.join(backends) or 'none'}")
    print(f"  {len(finished)} finished runs on the task set (S {len(by_arm['S'])}, M {len(by_arm['M'])}, "
          f"S-plus {len(by_arm['S_plus'])}); tracker databases read: {len(remote.files)}; the guards and the "
          f"schema from {source}")
    if scripted:
        print(f"  {scripted} runs on a scripted model are left out: they test your code, and score nothing")
    print()
    auto_earned = auto_possible = 0.0
    for sec in sections:
        score = "staff" if sec.manual else f"{round(sec.earned, 2):>5g} / {sec.possible:g}"
        print(f"{sec.name:<28} {score}")
        for note in sec.notes:
            if not note:
                continue
            for i, line in enumerate(str(note).splitlines()):
                print(f"{'    - ' if i == 0 else '      '}{line}")
        if not sec.manual:
            auto_earned += sec.earned
            auto_possible += sec.possible
    print(f"\nAutomated: {round(auto_earned, 2):g} / {auto_possible:g}   (plus up to 20 from staff for the report "
          "and the decision record)")
    for note in measured(report, computed):
        print(f"  measured: {note}")
    for note in staff_notes(report, computed):
        print(f"  for staff: {note}")
    flags = integrity_flags(runs)
    print("\nIntegrity flags (no points; staff review): " + ("none" if not flags else ""))
    for flag in flags:
        print(f"    - Integrity flag: {flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
