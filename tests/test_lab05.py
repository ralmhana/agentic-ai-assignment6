"""The harness's Assignment 5 additions: the mock remote's new writes, branch
protection, the write log and the compensating endpoints; issue metadata and a
call's facts; the reviewer's modes; the inbox; the notification sink; the clock;
run_tests; and the runner's resume of a held or stopped run. They spend no tokens
and keep passing once your policy is written."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from harness import LAB, ROOT
from harness.clock import now, parse, seconds_between
from harness.facts import FIELDS
from harness.formats import ACTIONS, BOUNDARY, RESUMABLE, TERMINAL_REASONS
from harness.inbox import drain, send
from harness.notify import notify, read
from harness.reviewer import Reviewer
from harness.roles import action_of, tool_for_action
from harness.runner import resume_run
from harness.scripted import BoundaryProbe, MomentA, role_call, triage_steps
from harness.trace import TraceWriter
from harness.tracker import RemoteRefused, Tracker


def tracker(tmp: str) -> Tracker:
    return Tracker(ROOT, state_dir=Path(tmp) / "tracker", flaky=False, readback_fail=False)


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = tracker(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_write_is_in_the_log_with_its_time(self):
        self.t.apply_label("r1", 4301, "bug", key="k1")
        pr = self.t.open_pr("r1", 4301, "repomind/issue-4301", "t", "b", key="k2")
        self.t.push_commit("r1", 4301, "repomind/issue-4301", "m", ["src/export/csv.ts"], key="k3")
        self.t.post_comment("r1", 4301, "label: bug\nfile: none", key="k4")
        log = self.t.log("r1")
        self.assertEqual([w["action"] for w in log], ["apply_label", "open_pr", "push_commit", "post_comment"])
        self.assertTrue(all(w["outcome"] == "written" and parse(w["at"]) for w in log))
        self.assertEqual([log[1]["target"], log[3]["target"]], [f"pr-{pr['id']}", "comment-1"])

    def test_a_key_is_accepted_once(self):
        first = self.t.apply_label("r1", 4301, "bug", key="same")
        again = self.t.apply_label("r1", 4301, "bug", key="same")
        self.assertTrue(again["replayed"])
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(len(self.t.labels("r1")), 1)
        self.assertEqual(self.t.by_key("r1", "label", "same")["id"], first["id"])

    def test_branch_protection_rejects_a_push_to_main_and_logs_it(self):
        with self.assertRaises(RemoteRefused):
            self.t.push_commit("r1", 4301, "main", "m", ["README.md"])
        self.assertEqual([(w["action"], w["outcome"]) for w in self.t.log("r1")], [("push_commit", "rejected")])
        with self.assertRaises(RemoteRefused):
            self.t.push_commit("r1", 4301, "repomind/issue-4301", "m", ["README.md"])   # no such branch yet
        self.assertEqual(self.t.pushes("r1"), [])

    def test_a_merge_is_of_this_runs_open_pull_request(self):
        pr = self.t.open_pr("r1", 4301, "repomind/issue-4301", "t", "b")
        with self.assertRaises(RemoteRefused):
            self.t.merge_pr("r2", pr["id"])
        merged = self.t.merge_pr("r1", pr["id"], key="m1")
        self.assertEqual(merged["base"], "develop")
        self.assertEqual(self.t.pr("r1", pr["id"])["state"], "merged")
        with self.assertRaises(RemoteRefused):
            self.t.merge_pr("r1", pr["id"])

    def test_three_compensations_and_none_for_a_comment(self):
        label = self.t.apply_label("r1", 4301, "bug")
        pr = self.t.open_pr("r1", 4301, "repomind/issue-4301", "t", "b")
        closed = self.t.close_issue("r1", 4301, "Duplicate of issue-4302.")
        self.t.reopen_issue("r1", closed["id"])
        self.t.close_pr("r1", pr["id"])
        self.t.remove_label("r1", label["id"])
        self.assertEqual(self.t.labels("r1"), [])
        self.assertEqual(self.t.prs("r1"), [])
        self.assertEqual(self.t.closes("r1"), [])
        self.assertEqual([w["action"] for w in self.t.log("r1")][-3:], ["reopen_issue", "close_pr", "remove_label"])
        with self.assertRaises(RemoteRefused):
            self.t.remove_label("r1", label["id"])          # offset once
        self.assertFalse(any(hasattr(self.t, name) for name in ("delete_comment", "revert_push", "unmerge_pr")))

    def test_metadata_is_hidden_from_the_issue_and_shown_to_the_hook(self):
        self.assertNotIn("opened_by_agent", self.t.issue(4301))
        self.assertNotIn("human_comment_minutes_ago", self.t.issue(4302))
        self.assertTrue(self.t.metadata(4301)["opened_by_agent"])
        self.assertAlmostEqual(self.t.metadata(4302)["minutes_since_human_comment"], 20, delta=1)
        first = self.t.metadata(4302)["last_human_comment_at"]
        time.sleep(0.05)
        self.assertEqual(self.t.metadata(4302)["last_human_comment_at"], first)   # counted from the first read
        self.assertIsNone(self.t.metadata(4303)["minutes_since_human_comment"])

    def test_a_calls_facts(self):
        comment = self.t.facts("r1", "post_comment", role_call("comment", number=4302, body="x")[1])
        self.assertEqual(set(comment), set(FIELDS))
        self.assertEqual(comment["issue"], 4302)
        self.assertFalse(comment["issue_opened_by_agent"])
        push = self.t.facts("r1", "push_commit", role_call("push_commit", branch="main", message="m",
                                                           files=["README.md"])[1], 4301)
        self.assertTrue(push["branch_protected"])
        self.assertEqual(push["paths"], ["README.md"])
        read = self.t.facts("r1", "read_file", role_call("read_file", path="src/db/client.ts")[1], 4303)
        self.assertEqual(read["paths"], ["src/db/client.ts"])

    def test_run_tests_reports_the_recorded_result(self):
        from tools import RunContext, default_tools
        self.t.open_pr("r1", 4501, "repomind/issue-4501", "t", "b")
        tools = default_tools(RunContext(run_id="r1", tracker=self.t, repo_root=ROOT / "fixtures" / "repo", issue=4501))
        on_branch = json.loads(tools.call(tool_for_action("run_tests"),
                                          role_call("run_tests", ref="repomind/issue-4501")[1]).content)
        on_main = json.loads(tools.call(tool_for_action("run_tests"), role_call("run_tests", ref="main")[1]).content)
        self.assertFalse(on_branch["passed"])
        self.assertEqual(on_branch["failed"], ["toDelimited > puts date first (3.2.0 column order)"])
        self.assertTrue(on_main["passed"])
        self.assertEqual(on_main["tests"], 38)


class ActionTests(unittest.TestCase):
    def test_ten_actions_and_their_tools(self):
        self.assertEqual(len(ACTIONS), 10)
        self.assertEqual(action_of(tool_for_action("post_comment")), "post_comment")
        self.assertEqual(action_of("code_search"), "search_repo")

    def test_held_and_stopped_are_resumable_endings(self):
        self.assertTrue(set(RESUMABLE) <= set(TERMINAL_REASONS))
        self.assertTrue(BOUNDARY.match("BOUNDARY: deny path=src/db/**"))
        self.assertIsNone(BOUNDARY.match("please stay out of src/db"))

    def test_the_moments_plans(self):
        a = [s["tool"] for s in MomentA().plan({}, 4501)]
        self.assertEqual(a[-3:], [tool_for_action("run_tests"), tool_for_action("push_commit"),
                                  tool_for_action("post_comment")])
        reads = [s for s in BoundaryProbe().plan({}, 4303) if s["tool"] == tool_for_action("read_file")]
        self.assertEqual(len(reads), 3)
        self.assertEqual(len(triage_steps(4192)), 6)


class ReviewerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.request = {"run_id": "r1", "action": "open_pr", "action_class": "open_pr", "args": {}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_scripted_modes(self):
        self.assertEqual(Reviewer("scripted:approve-all", self.root).ask(self.request, 5)["decision"], "approve")
        self.assertEqual(Reviewer("scripted:deny-all", self.root).ask(self.request, 5)["decision"], "deny")
        started = time.monotonic()
        self.assertIsNone(Reviewer("scripted:none", self.root).ask(self.request, 600))
        self.assertLess(time.monotonic() - started, 1)
        logged = [json.loads(x) for x in (self.root / "logs" / "reviewer.jsonl").read_text().splitlines()]
        self.assertEqual([x["answer"] for x in logged], ["approve", "deny", "none"])

    def test_replay_matches_class_then_action_then_kind_then_any(self):
        path = self.root / "decisions.jsonl"
        path.write_text("\n".join(json.dumps(x) for x in [
            {"kind": "escalation", "decision": "none"},
            {"action_class": "*", "decision": "approve", "repeat": True},
            {"action_class": "open_pr", "decision": "deny"}]) + "\n")
        reviewer = Reviewer(f"scripted:replay:{path}", self.root)
        self.assertEqual(reviewer.ask(self.request, 5)["decision"], "deny")
        self.assertEqual(reviewer.ask(self.request, 5)["decision"], "approve")      # the class's line is used up
        self.assertIsNone(reviewer.ask({**self.request, "kind": "escalation"}, 5))

    def test_a_request_needs_its_fields(self):
        with self.assertRaises(ValueError):
            Reviewer("scripted:approve-all", self.root).ask({"run_id": "r1"}, 5)

    def test_human_mode_waits_for_bin_review(self):
        reviewer = Reviewer("human", self.root)
        got = {}
        waiting = threading.Thread(target=lambda: got.update(answer=reviewer.ask(self.request, 10)))
        waiting.start()
        for _ in range(40):
            if reviewer.pending():
                break
            time.sleep(0.05)
        pending = reviewer.pending()
        self.assertEqual(len(pending), 1)
        shown = now()
        time.sleep(0.05)
        reviewer.decide(pending[0]["request_id"], "approve", shown)
        waiting.join(5)
        self.assertEqual(got["answer"]["decision"], "approve")
        self.assertEqual(got["answer"]["reviewer"], "human")
        self.assertGreater(got["answer"]["seconds"], 0)
        self.assertEqual(reviewer.pending(), [])

    def test_human_mode_withdraws_at_the_timeout(self):
        reviewer = Reviewer("human", self.root)
        self.assertIsNone(reviewer.ask(self.request, 0.3))
        self.assertEqual(reviewer.pending(), [])

    def test_until_ends_a_wait_early(self):
        reviewer = Reviewer("human", self.root)
        started = time.monotonic()
        self.assertIsNone(reviewer.ask(self.request, 600, until=lambda: time.monotonic() - started > 0.3))
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(reviewer.pending(), [])


class InboxAndSinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runs = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def ctx(self, run_id: str, issue: int, calls: int):
        return SimpleNamespace(run_id=run_id, issue_number=issue, runs_dir=self.runs, root=self.runs,
                               client=SimpleNamespace(calls=calls))

    def test_a_message_is_delivered_once_when_due(self):
        send("BOUNDARY: deny path=src/db/**", issue=4303, before_call=4, runs_dir=self.runs)
        self.assertEqual(drain(self.ctx("r1", 4303, 2)), [])            # its third call: not yet
        got = drain(self.ctx("r1", 4303, 3))                             # about to make its fourth
        self.assertEqual([m["text"] for m in got], ["BOUNDARY: deny path=src/db/**"])
        self.assertEqual(drain(self.ctx("r1", 4303, 5)), [])
        self.assertEqual(drain(self.ctx("r2", 4303, 5)), [])            # once, to one run

    def test_a_message_to_a_run(self):
        send("keep it short", run_id="r9", runs_dir=self.runs)
        self.assertEqual(drain(self.ctx("r1", 4192, 0)), [])
        self.assertEqual(len(drain(self.ctx("r9", 4192, 0))), 1)

    def test_the_notification_sink(self):
        line = notify("live", "r1", "running", root=self.runs, quiet=True, issue=4192)
        self.assertEqual(read(self.runs), [line])
        with self.assertRaises(ValueError):
            notify("live now", "r1", "x", root=self.runs, quiet=True)

    def test_the_clock(self):
        a = now()
        self.assertRegex(a, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertEqual(seconds_between("2026-10-30T10:00:00.000Z", "2026-10-30T10:00:01.250Z"), 1.25)


class ResumeTests(unittest.TestCase):
    """run.py --resume reopens a run that ended held or stopped, and refuses a finished one."""

    def write(self, root: Path, run_id: str, ending: str) -> None:
        trace = TraceWriter(root / "runs" / f"{run_id}.jsonl", run_id, {
            "lab": LAB, "way": "direct", "issue": 4192, "sweep": 1, "backend": "harness.scripted:ScriptedTriage",
            "critique": "off", "notes": "off", "switches": {}})
        trace.end(ending, detail="test")
        trace.run_end({"total_tokens": 0}, None)

    def test_held_and_stopped_resume_and_completed_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("settings.yaml", "pricing.yaml"):
                (root / name).write_text((ROOT / name).read_text())
            (root / "runs").mkdir()
            for run_id, ending in (("held-run", "held"), ("stopped-run", "stopped"), ("done-run", "completed")):
                self.write(root, run_id, ending)
            with mock.patch("harness.runner._run_way", return_value={"run_id": "x", "total_tokens": 0,
                                                                     "cost_usd": 0.0, "error": None}):
                for run_id in ("held-run", "stopped-run"):
                    row = resume_run(run_id, root=root, log=lambda *a: None)
                    self.assertEqual(row["error"], None)
                with self.assertRaises(SystemExit):
                    resume_run("done-run", root=root, log=lambda *a: None)


if __name__ == "__main__":
    unittest.main()
