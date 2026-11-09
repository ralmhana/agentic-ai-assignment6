"""Assignment 6's harness: tasks, budgets, the five constants, and a run's agents.

They spend no tokens: every run uses ScriptedWorkers, in a scratch copy of the
repository's runs and tracker.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from harness import LAB, ROOT
from harness.client import AgentClient, BudgetExceeded, ModelClient
from harness.pricing import PriceSheet
from harness.runner import finished_tasks, matched_budgets, run_sweeps
from harness.scripted import ScriptedWorkers
from harness.tasks import Task, end_state, issue_tasks, load_tasks
from harness.trace import TraceWriter, read_trace
from harness.tracker import Tracker

SCRIPTED = "harness.scripted:ScriptedWorkers"


class Scratch:
    """A copy of the repository with empty runs and tracker, for runs that leave no trace here."""

    def __enter__(self) -> Path:
        self.tmp = Path(tempfile.mkdtemp(prefix="lab06-test-"))
        root = self.tmp / "repo"
        shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", ".venv", "runs", "tracker", "results",
                                                                  "logs", "__pycache__", "*.pyc"))
        (root / "runs").mkdir()
        (root / "tracker").mkdir()
        settings = (root / "settings.yaml").read_text().replace("provider: null", "provider: anthropic")
        (root / "settings.yaml").write_text(settings.replace("model: null", "model: test-model"))
        return root

    def __exit__(self, *exc) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


def quiet(*args, **kwargs) -> None:
    pass


class TaskTests(unittest.TestCase):
    def test_the_task_set(self):
        tasks = load_tasks(ROOT / "fixtures" / "tasks6")
        self.assertEqual(len(tasks), 8)
        self.assertEqual(sorted(t.kind for t in tasks).count("batch"), 2)
        for t in tasks:
            self.assertEqual(set(t.answers), set(t.issues))
            self.assertEqual(len(t.issues), 5 if t.kind == "batch" else 1)
        batch = next(t for t in tasks if t.kind == "batch")
        self.assertEqual(batch.budget(1000), 5000)
        self.assertIsNone(batch.issue)
        self.assertIsNone(batch.budget(None))

    def test_an_issue_is_a_task_of_its_own(self):
        dev, other = issue_tasks([4191, 4402])
        self.assertEqual((dev.id, other.id), ("dev-4191", "issue-4402"))
        self.assertEqual(dev.kind, "single")
        self.assertEqual(dev.issue, 4191)


class RunTests(unittest.TestCase):
    """Every run in this assignment answers approvals with scripted:approve-all, as the handout sets it."""

    def setUp(self):
        self.saved = os.environ.get("REVIEWER")
        os.environ["REVIEWER"] = "scripted:approve-all"

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("REVIEWER", None)
        else:
            os.environ["REVIEWER"] = self.saved

    def test_a_batch_run_records_its_task_budget_and_constants(self):
        with Scratch() as root:
            batch = next(t for t in load_tasks(root / "fixtures" / "tasks6") if t.id == "batch-a")
            rows = run_sweeps("agent", [batch], range(1, 2), SCRIPTED, jobs=1, root=root, budget=200000, log=quiet)
            self.assertEqual(len(rows), 1)
            start = read_trace(root / "runs" / f"{rows[0]['run_id']}.jsonl")[0]
            self.assertEqual(start["lab"], LAB)
            self.assertEqual((start["task"], start["kind"], start["issues"]), ("batch-a", "batch", list(batch.issues)))
            self.assertEqual((start["budget"], start["ceiling"]), (1000000, 1000000))
            self.assertIsNone(start["matched_to"])
            self.assertEqual(set(start["constants"]), {"model", "schemas_sha", "checks_sha", "reviewer", "task_ids"})
            self.assertEqual(start["constants"]["task_ids"], ["batch-a"])
            self.assertTrue(start["started_at"].endswith("Z"))
            comments = Tracker(root, flaky=False, readback_fail=False).comments(rows[0]["run_id"])
            self.assertEqual(sorted(c["issue"] for c in comments), sorted(batch.issues))
            state = end_state(Tracker(root, flaky=False, readback_fail=False), rows[0]["run_id"], batch)
            self.assertEqual(sorted(state), sorted(batch.issues))
            self.assertEqual(set(state[batch.issues[0]]), {"comments", "labels", "prs"})

    def test_match_gives_each_task_the_mean_spend_of_another_way(self):
        with Scratch() as root:
            task = next(t for t in load_tasks(root / "fixtures" / "tasks6") if t.id == "one-4402")
            rows = run_sweeps("agent", [task], range(1, 3), SCRIPTED, jobs=1, root=root, budget=100000, log=quiet)
            spent = round(sum(r["total_tokens"] for r in rows) / len(rows))
            self.assertEqual(matched_budgets("agent", [task], SCRIPTED, root / "runs")["one-4402"], (spent, 100000))
            with self.assertRaises(SystemExit):
                matched_budgets("split", [task], SCRIPTED, root / "runs")
            matched = run_sweeps("agent", [task], range(1, 2), SCRIPTED, jobs=1, root=root, match="agent", log=quiet)
            start = read_trace(root / "runs" / f"{matched[0]['run_id']}.jsonl")[0]
            self.assertEqual((start["budget"], start["ceiling"], start["matched_to"]), (spent, 100000, "agent"))


class RedoTests(unittest.TestCase):
    def test_only_a_task_sweep_finished_on_this_backend_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            def write(run_id, task, sweep, end="completed", backend="anthropic", way="split"):
                lines = [{"type": "run_start", "run_id": run_id, "lab": LAB, "way": way, "task": task, "sweep": sweep,
                          "backend": backend, "critique": "off", "notes": "off"},
                         {"type": "end", "terminal_reason": end}, {"type": "run_end"}]
                (runs / f"{run_id}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
            write("a", "batch-a", 1)
            write("b", "batch-a", 2, end="rate_limited")
            write("c", "one-4402", 1, backend="openai-compatible")
            write("d", "one-4402", 1, way="agent")
            self.assertEqual(finished_tasks(runs, "split", "off", "off", "anthropic"), {(1, "batch-a")})


class AgentTests(unittest.TestCase):
    def test_an_agents_lines_name_it_and_its_end_never_ends_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = TraceWriter(Path(tmp) / "t.jsonl", "r1", {"lab": LAB})
            lead = trace.agent("coordinator")
            worker = trace.agent("worker-1", parent="coordinator")
            lead.event("wait", waiter="coordinator", on="worker-1", what="a finding", turn=0)
            worker.end("turn_limit", "12 model calls")
            self.assertFalse(trace.ended)
            self.assertTrue(worker.ended)
            with self.assertRaises(ValueError):
                trace.event("agent_end", terminal_reason="completed", detail="")
            trace.run_end({"total_tokens": 0}, None)
            lines = read_trace(Path(tmp) / "t.jsonl")
            wait = next(r for r in lines if r["type"] == "wait")
            self.assertEqual((wait["agent"], wait["parent"]), ("coordinator", None))
            end = next(r for r in lines if r["type"] == "agent_end")
            self.assertEqual((end["agent"], end["parent"], end["terminal_reason"]), ("worker-1", "coordinator", "turn_limit"))
            self.assertEqual([r["terminal_reason"] for r in lines if r["type"] == "end"], ["completed"])

    def test_an_agents_client_keeps_its_own_totals_under_the_runs_ceiling(self):
        root = ModelClient(ScriptedWorkers(), PriceSheet(ROOT / "pricing.yaml"), session_ceiling=10**9)
        a, b = AgentClient(root, "a"), AgentClient(root, "b")
        message = [{"role": "user", "content": "Triage issue #4402."}]
        a.create(messages=message)
        a.create(messages=message)
        b.create(messages=message)
        self.assertEqual(a.calls, 2)
        self.assertEqual(b.calls, 1)
        self.assertEqual(a.total_tokens + b.total_tokens, root.total_tokens)
        root.session_ceiling = root.total_tokens
        with self.assertRaises(BudgetExceeded):
            b.create(messages=message)


if __name__ == "__main__":
    unittest.main()
