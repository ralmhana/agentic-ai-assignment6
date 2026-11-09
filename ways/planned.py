"""Assignment 5's working solution, over Assignment 4's planned way.
It ships in Assignment 6's starter as RepoMind's own.

Assignment 5 adds the Control & Policy layer (checks/FORMATS.md, section 13). The
policy itself is enforced in the registry's pre-call hook (policy/hook.py), never
here and never in a prompt. This way adds what the hook cannot do alone:
  - The inbox, before every model call. The client is wrapped (Drained) so that
    every call, the planner's, a fill's, a revision's, a critique's and a
    compaction's, first drains the run's messages. A boundary is written to
    policy/rules.jsonl (policy/boundary.py), where the hook reads it; every message,
    the boundary's own text included, joins the history as the user's words, where a
    compaction can drop it and the rule still holds.
  - A live notification, before the run's first write: logs/notifications.jsonl
    says the run is live and how to stop it (Lecture 5, slide 40, "watched").
  - The stop and the hold. A call the hook refused because the run was stopped
    (bin/stop) ends the run stopped, and one it refused because nobody answered a
    gated call ends it held; either way after a checkpoint, with the refused step
    still to run. A resume lifts the stop and asks again.
  - The escalation (policy/escalation.py): the harness sets four named signals, and
    before the next irreversible or gated write a raised signal sends a packet to
    the reviewer and holds. Approved, the step runs; denied, it is skipped; no
    answer, the run ends held. A resume recomputes the signals from the
    checkpoint's results, so it asks again what was never answered.
  - An empty search is not a finding: a search step that found no source file
    leaves a not_determined event, and the checkpoint's revision retries it within
    MAX_REVISIONS (moment B).
  - Part D: every comment's body carries the policy's disclosure line after its
    label and file lines; the hook refuses one that does not.

Assignment 4's own account of the way follows.

Assignment 4 adds three things here (checks/FORMATS.md, section 12):
  - State that survives a crash. The run saves a checkpoint (state/checkpointer.py)
    after each file read, the expensive read, and immediately before each write,
    every one sync: the run writes, so it runs sync (Lecture 4, slide 12). A checkpoint holds
    the plan, each step's status, every completed call with its key and its result,
    the findings (the label and file, the comment's checked draft, the PR's
    arguments) and the current step. Never the conversation.
  - Resume, not restart. A run whose run_id has a checkpoint is a resume: it
    rebuilds the executor from the last checkpoint, skips every step done, reuses
    the recorded results as context, and replays a write from the arguments saved
    before it, so the key is the same and the registry's check before the attempt
    finds the write if it happened. A run with no checkpoint plans afresh.
  - Memory that survives a run (state/store.py). Before the first search, the
    active records for this repository and issue are read (a store_read line) and
    shown to every fill call, with their age and provenance; records whose source
    is an issue's text are left out, and the planner sees none. At the end of a
    run that posted its comment, the triage is written as one episodic record
    (state/write_policy.md): inserted, left as it is when it agrees, superseded when
    it does not.
  - Part F's three forgettings, set from the environment. PLANT_FACT is a rule a
    maintainer states to this run. It goes right after the request, where the model
    looks first, in every fill call; with PLANT_BURY=<characters> it goes instead in
    the middle of that much of Ledgerline's own files, as a plain line among them
    (attention). With
    REPOMIND_COMPACT_AT=<tokens> it is the first turn of the run's history, and the
    history is compacted past that size as in Assignment 2's ways/notes.py, into one
    sentence of tools and paths (prompts/compact_steps.md; compaction); --notes on
    keeps it in a note outside the history, the progress file, shown right after the
    request. A run told the fact that posts its comment
    stores it as the maintainer stated it, so the next run's store read brings it
    back (the session).

Below, Assignment 3's own account of the way.

Assignment 3's working solution, over Assignment 2's planned way: the same plan,
boundary, checkpoint and second pass, with Assignment 3's tools and the PR step.

Assignment 3 changes four things here:
  - Tools are found by role (harness.roles), never by name: the names are the
    team's own (tools/roles.yaml).
  - The plan ends with the PR and then the comment (Lecture 3, slide 41): the schema check
    wants exactly one comment step, the last, and exactly one PR step, right before
    it. A PR can be closed; a comment, once read, cannot be taken back. The comment
    is drafted, and passes the second pass, before the first write; the PR opens
    only when that draft names a file, and when it says none the step is skipped
    (status "skipped"), a condition the executor applies, not the model. The draft
    posts last.
  - The PR's issue and branch are the code's: repomind/issue-<n>, whatever the plan
    or the model wrote. The model fills only its title and body.
  - A write the registry cannot confirm (tools.Unverifiable, the third exit) ends
    the run escalated: a person on review duty decides.

The boundary: the executor runs the plan's steps in order and nothing else. Where a
step's arguments are "$fill", one model call fills them, offered that step's tool
alone; a call to any other tool is refused, traced as off_plan, and never runs.
Two tries without an on-plan call halt the run as escalated.

The planner's output is checked against agent/plan_schema.json (harness.schema)
before the four checks, and so is the rule about its comment step (above): a
vendor can accept "strict" and not enforce it, and a plan with no comment step
passes all four checks and posts nothing. A plan that breaks either is rejected
like one that fails a check.

The checkpoint, a check in code: after the first search step, and after any search
step a revision added or changed, until MAX_REVISIONS is spent, the search returned
at least one source file: a .ts or .tsx file under src/, not only documentation
(README.md, CHANGELOG.md, docs/) or translations (src/i18n/*.json). A revision never
changes a step that is done; it may change a failed step, which then runs again.

Part G's ways/notes.py extends this file without changing it: it subclasses
Executor and overrides its hooks, record() (after every step), context() (what
every executor call sees) and the class attribute critique, and asks its questions
once run() has returned, however the run ended.

The second pass, before the first write, in ctx.critique's mode: external runs
agent.critique.verify, code; self asks the model with agent.critique.self_critique.
A failing draft with a round left is rewritten by one call; a draft still failing
in the last round is held, and the run escalates having written nothing. One
comment, after the last round and the PR.
"""

from __future__ import annotations

import copy
import json
import os
import re
from datetime import datetime, timezone

from agent.critique import self_critique, verify
from agent.diff import step_args
from agent.plan import SCHEMA, make_plan, revise_plan
from agent.validator import validate
from harness.formats import FILL, format_triage_comment, parse_triage_comment, result_paths
from harness.inbox import drain
from harness.notify import notify
from harness.roles import ALL_ROLES, arg, tool_for
from harness.schema import errors as schema_errors
from state.checkpointer import Checkpointer
from state.store import REPOSITORY, Store
from policy import boundary, escalation, stop
from policy.hook import disclosure, held
from tools import Unverifiable

MAX_REPLANS = 2       # three planner calls in all; a fourth on the same request is the same coin, so a person looks
MAX_REVISIONS = 2     # a repair of the first search, and one more if the repair also finds nothing
MAX_ROUNDS = 2        # check, rewrite once, check again: Lecture 2, slide 43's limit, the same in both modes
MAX_FILL_TRIES = 2    # a step the model will not fill on plan, twice, halts the run
CHECKPOINT = "after_first_search"
SOURCE = re.compile(r"^src/(?!i18n/).+\.tsx?$")   # code, not documentation or translations
CONTEXT_CHARS = 6000  # of each earlier result, in a fill call
MODE = "sync"         # the run writes, so every save waits (Lecture 4, slide 12); one mode for the run
CONVERSATION = "CHECKPOINT_CONVERSATION"   # set to 1: also save each checkpoint with the conversation, elsewhere
CONVERSATION_DB = "state/checkpoints_with_conversation.db"
FACT = "PLANT_FACT"            # Part F: a rule a maintainer states to this run
BURY = "PLANT_BURY"            # Part F, attention: put the fact first, under this many characters of other text
COMPACT_AT = "REPOMIND_COMPACT_AT"   # Part F, compaction: compact the history past this many tokens
KEEP = 1                       # turns a compaction keeps as they were
SUMMARY = "## Summary of the earlier steps"


def role(name: str | None) -> str | None:
    """The role a step's tool plays, or None."""
    return next((r for r in ALL_ROLES if tool_for(r) == name), None)


def allows_null(spec: dict) -> bool:
    """Whether a property's schema takes null: "type": [..., "null"], or a null branch."""
    kind = spec.get("type")
    return ("null" in kind if isinstance(kind, list) else kind == "null") or any(
        isinstance(b, dict) and allows_null(b) for b in spec.get("anyOf") or spec.get("oneOf") or [])


class Recording:
    """Part E's measurement only (CHECKPOINT_CONVERSATION=1): the model client, keeping
    every message sent through it, so a checkpoint can be saved with the conversation."""

    def __init__(self, client, sink: list):
        self._client, self._sink = client, sink

    def create(self, **request):
        self._sink.extend(request.get("messages") or [])
        return self._client.create(**request)

    def __getattr__(self, name):
        return getattr(self._client, name)


class Drained:
    """The model client, draining the run's inbox before every call it makes."""

    def __init__(self, ctx, client, heard: list):
        self._ctx, self._client, self._heard = ctx, client, heard
        self.position = lambda: 0      # where in the history a message lands: set once the executor exists

    def create(self, **request):
        for message in drain(self._ctx):
            rule = boundary.record(self._ctx.run_id, message)
            if rule is not None:
                self._ctx.trace.event("boundary", path=rule["path"], message=message["text"])
            self._heard.append({"text": message["text"], "after": self.position()})
        return self._client.create(**request)

    def __getattr__(self, name):
        return getattr(self._client, name)


def run(ctx) -> None:
    conversation: list[dict] = []
    if os.environ.get(CONVERSATION) == "1":
        ctx.client = Recording(ctx.client, conversation)
    heard: list[dict] = []
    ctx.client = drained = Drained(ctx, ctx.client, heard)
    checkpointer = Checkpointer()
    last = checkpointer.last(ctx.run_id)
    if last is not None and stop.lift(ctx.run_id):
        ctx.trace.event("stop_lifted", by="resume")
    notify("live", ctx.run_id, f"RepoMind is running on issue {ctx.issue_number}; stop it with: bin/stop {ctx.run_id}",
           issue=ctx.issue_number)
    memory = recall(ctx)
    if last is not None:                          # a resume: rebuild from the last checkpoint, never re-plan
        executor = Executor(ctx, last["plan"], checkpointer=checkpointer, memory=memory, restore=last)
        ctx.trace.event("resumed_from", step=last.get("current_step"), saved=len(checkpointer.all(ctx.run_id)))
    else:
        plan = plan_until_valid(ctx)
        if plan is None:
            return
        ctx.trace.plan(1, plan)
        executor = Executor(ctx, plan, checkpointer=checkpointer, memory=memory)
    executor.conversation = conversation
    executor.heard = heard
    drained.position = lambda: len(executor.results)
    executor.run()
    remember(ctx, executor)


# -- Part F: a fact this run was told, and where it sits ------------------------------------------------
def told() -> str:
    return (os.environ.get(FACT) or "").strip()


def tokens(text: str) -> int:
    return -(-len(text) // 4)      # characters over four, rounded up, as in ways/notes.py


def buried(root, chars: int, block: str) -> str:
    """The attention case: Ledgerline's own files, in path order, `chars` characters of
    them, with `block` among them halfway through, as plain text."""
    repo = root / "fixtures" / "repo"
    files, size = [], 0
    for path in sorted(p for p in repo.rglob("*") if p.is_file()):
        files.append(f"### {path.relative_to(repo).as_posix()}\n{path.read_text(errors='ignore')}")
        size += len(files[-1])
        if size >= chars:
            break
    text = "\n\n".join(files)[:chars]
    middle = text.find("\n### ", len(text) // 2)
    middle = len(text) // 2 if middle < 0 else middle
    return f"## Ledgerline's files, for reference\n\n{text[:middle]}\n\n{block}\n{text[middle:]}"


# -- memory: read before the first search, written at the end of a run -------------------------------
def age(written_at: str) -> str:
    try:
        then = datetime.fromisoformat(str(written_at).replace("Z", "+00:00"))
    except ValueError:
        return "of unknown age"
    days = (datetime.now(timezone.utc) - then).days
    return "written today" if days < 1 else f"{days} days old"


def recall(ctx) -> list[dict]:
    """The active records for this repository and this issue, logged as a store_read
    line. Records carrying an issue's text never reach a prompt."""
    store = Store()
    records = store.active(REPOSITORY, ctx.issue_number)
    ctx.trace.event("store_read", issue=ctx.issue_number, records=[r["id"] for r in records],
                    store="empty" if os.environ.get("REPOMIND_STORE") == "empty" else str(store.path.name))
    return [r for r in records if not str(r.get("source", "")).startswith("issue:")]


def memory_block(records: list[dict]) -> str:
    if not records:
        return ""
    lines = [f"- [{r['kind']}; source {r['source']}; {r['origin']}; "
             f"{'confirmed' if r['confirmed'] else 'unconfirmed'}; {age(r['written_at'])}] {r['text'].strip()}"
             for r in records]
    return ("## What RepoMind remembers (its store: dated, with where each came from; a maintainer's stated "
            "rule applies, anything else is a lead to check)\n" + "\n".join(lines))


def remember(ctx, executor) -> None:
    """The write policy's one write (state/write_policy.md): when the run has posted
    its comment, its triage, as an episodic record RepoMind derived. One active
    record per issue: kept when the new triage agrees, superseded when it does not."""
    posted = next((r for r in executor.results if role(r["tool"]) == "comment" and r["status"] == "done"), None)
    if posted is None or executor.draft is None:
        return
    label, file = parse_triage_comment(str(executor.draft.get(arg("comment", "body"))))
    store = Store()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = f"On {now[:10]} RepoMind triaged issue {ctx.issue_number}: label {label}, file {file or 'none'}."
    record = {"repository": REPOSITORY, "issue": ctx.issue_number, "kind": "episodic", "text": text,
              "source": "memory", "written_at": now, "origin": "derived",
              "confirmed": ctx.critique == "external", "stated_by": None}
    earlier = [r for r in store.active(REPOSITORY, ctx.issue_number)
               if r["kind"] == "episodic" and r["source"] == "memory" and r.get("issue") == ctx.issue_number]
    if not earlier:
        store.write(record)
    elif f"label {label}, file {file or 'none'}." not in earlier[-1]["text"]:
        store.supersede(earlier[-1]["id"], record)
    fact = told()
    if fact and not any(r["text"] == fact for r in store.active(REPOSITORY)):   # Part F: stated, kept as stated
        store.write({"repository": REPOSITORY, "issue": None, "kind": "semantic", "text": fact, "source": "user",
                     "written_at": now, "origin": "ingested", "confirmed": True,
                     "stated_by": f"a Ledgerline maintainer, to run {ctx.run_id}"})


def schema_check(ctx, plan: dict, version: int) -> list[dict]:
    """The plan as the planner's tool returned it, against agent/plan_schema.json. A
    failure is written as a schema line, and comes back as failures for a re-plan."""
    problems = schema_errors({k: v for k, v in plan.items() if k != "meta"}, SCHEMA)
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    roles = [role(s.get("tool")) for s in steps]
    if roles.count("comment") != 1 or roles[-1] != "comment":
        problems.append(f"the comment step comes once, last; this plan's steps are {roles}")
    elif roles.count("open_pr") != 1:
        problems.append(f"the PR step comes exactly once, before the comment step; this plan's steps are {roles}")
    elif roles.count("apply_label") != 1 or roles.index("apply_label") > roles.index("open_pr"):
        problems.append(f"the label step comes exactly once, before the PR step; this plan's steps are {roles}")
    if problems:
        ctx.trace.event("schema", version=version, errors=problems[:20])
    return [{"step": None, "check": "schema", "error": e} for e in problems[:5]]


def plan_until_valid(ctx) -> dict | None:
    """The reject exit: re-plan up to MAX_REPLANS times, then escalate. Never execute a rejected plan."""
    failures = None
    for attempt in range(1, MAX_REPLANS + 2):
        plan = make_plan(ctx.client, ctx.issue_number, ctx.tools.schemas, trace=ctx.trace, failures=failures)
        broken = schema_check(ctx, plan, 1)
        if broken:                                # rejected before the four checks: it never runs
            failures = broken
            continue
        verdict = validate(plan)
        ctx.trace.event("validation", version=1, attempt=attempt, valid=verdict["valid"],
                        failures=verdict["failures"])
        if verdict["valid"]:
            return plan
        failures = verdict["failures"]
    ctx.trace.end("escalated", detail=f"no valid plan in {MAX_REPLANS + 1} attempts; last failures {failures}")
    return None


class Executor:
    critique = True   # the notes way turns the second pass off

    def __init__(self, ctx, plan: dict, *, checkpointer: Checkpointer | None = None,
                 memory: list[dict] | None = None, restore: dict | None = None):
        self.ctx = ctx
        self.plan = copy.deepcopy(plan)
        self.version = 1
        self.results: list[dict] = []    # step_results (checks/FORMATS.md, section 10.3), in the order steps ran
        self.outputs: dict[str, str] = {}  # each step's tool output, for later calls; never shown to the reviser
        self.calls = 0                   # execute and critique calls so far: the step number of the next lines
        self.revisions = 0
        self.revised: set[str] = set()   # ids of steps a revision added or changed: the checkpoint follows them
        self.ran: set[str] = set()       # ids of steps that ran and are not to run again
        self.checkpointer = checkpointer
        self.memory = memory or []
        self.completed: list[dict] = []  # completed_calls: every call that returned, with its key and result
        self.pr_args: dict | None = None
        self.conversation: list[dict] = []   # every message sent to the model, for Part E's measurement only
        self.compact_at = int(os.environ[COMPACT_AT]) if os.environ.get(COMPACT_AT) else None   # Part F
        self.summary: str | None = None  # the compaction's summary of the earliest turns, once there is one
        self.summarized = 0              # how many of the earliest turns it replaced
        self.heard: list[dict] = []      # Assignment 5: the user's messages, from the inbox
        self.signals: list[dict] = []    # Assignment 5: named signals the harness raised, {key, signal, why}
        self.answered: set[str] = set()  # signals a person has answered
        self.failures: dict[str, int] = {}   # refusals and failures per step: three is a signal
        self.disclosure = disclosure()
        if restore is not None:
            self.restore(restore)

    # -- state: saved after each file read and before each write, and restored on a resume -------
    def findings(self) -> dict:
        out = {"version": self.version, "revisions": self.revisions, "revised": sorted(self.revised)}
        if self.draft is not None:
            label, file = parse_triage_comment(str(self.draft.get(arg("comment", "body"))))
            out.update(label=label, file=file or "none", draft=self.draft)
        if self.pr_args is not None:
            out["pr"] = self.pr_args
        out["answered"] = sorted(self.answered)
        return out

    def save_state(self, step: dict, current=None) -> None:
        """One checkpoint, on disk before the next call starts, then its trace line."""
        if self.checkpointer is None:
            return
        state = {"plan": self.plan,
                 "step_status": {str(s.get("id")): s.get("status", "pending") for s in self.plan.get("steps") or []},
                 "completed_calls": self.completed, "findings": self.findings(), "current_step": current}
        self.checkpointer.save(self.ctx.run_id, state, step=step.get("id"), mode=MODE)
        if os.environ.get(CONVERSATION) == "1":
            Checkpointer(self.ctx.root / CONVERSATION_DB).save(
                self.ctx.run_id, {**state, "conversation": self.conversation}, step=step.get("id"), mode=MODE)
        self.ctx.trace.event("checkpoint", step=step.get("id"), mode=MODE)

    def restore(self, saved: dict) -> None:
        status = saved.get("step_status") or {}
        for s in self.plan.get("steps") or []:
            s["status"] = status.get(str(s.get("id")), s.get("status", "pending"))
        for call in saved.get("completed_calls") or []:
            entry = {k: call.get(k) for k in ("id", "tool", "status", "count", "paths", "error_code", "args")}
            entry["id"] = call.get("step")
            self.results.append(entry)
            self.outputs[str(call.get("step"))] = call.get("result") or ""
            self.completed.append(call)
        self.ran = {sid for sid, st in status.items() if st in ("done", "failed", "skipped")}
        found = saved.get("findings") or {}
        self.version = found.get("version", 1)
        self.revisions = found.get("revisions", 0)
        self.revised = set(found.get("revised") or [])
        if found.get("draft") is not None:
            self.draft = found["draft"]
            self.drafted_file = found.get("file") or "none"
        self.pr_args = found.get("pr")
        self.answered = set(found.get("answered") or [])
        for call in self.completed:                # the signals a crash or a hold left unanswered
            self.notice(call.get("step"), call.get("tool"), call.get("result") or "", call.get("status") == "failed")

    # -- Assignment 5: named signals, raised by the harness from what came back ------------------
    def raise_signal(self, key: str, signal: str, why: str) -> None:
        if not any(s["key"] == key for s in self.signals):
            self.signals.append({"key": key, "signal": signal, "why": why})

    def notice(self, step_id, tool, text: str, failed: bool) -> None:
        if role(tool) == "run_tests" and not failed:
            try:
                found = json.loads(text)
            except ValueError:
                found = None
            if not isinstance(found, dict) or "passed" not in found:
                self.raise_signal(f"uninterpretable:{step_id}", "uninterpretable_result",
                                  f"run_tests returned a result the harness cannot read: {text[:120]}")
            elif not found["passed"]:
                self.raise_signal(f"tests:{step_id}", "failed_verification",
                                  f"run_tests on {found.get('ref')} failed: {', '.join(found.get('failed') or [])}")
        if "did not fit its declared shape" in text:
            self.raise_signal(f"uninterpretable:{step_id}", "uninterpretable_result",
                              f"step {step_id}'s tool returned a result the harness cannot interpret")
        if failed:
            n = self.failures[str(step_id)] = self.failures.get(str(step_id), 0) + 1
            if n >= 3:
                self.raise_signal(f"blocked:{step_id}", "blocked_three_times", f"step {step_id} failed {n} times")

    def contradiction(self) -> None:
        """The draft against this issue's confirmed triage in the store (Assignment 4's).
        RepoMind's own unconfirmed triage is a lead, not a fact a draft can contradict."""
        label, file = parse_triage_comment(str(self.draft.get(arg("comment", "body"))))
        for r in self.memory:
            stored = re.search(r"label (\w+), file (\S+?)\.$", str(r.get("text") or ""))
            if r.get("kind") == "episodic" and r.get("issue") == self.ctx.issue_number and stored and r.get("confirmed") \
                    and (stored.group(1), stored.group(2)) != (label, file or "none"):
                self.raise_signal(f"memory:{r.get('id')}", "memory_contradiction",
                                  f"this run's draft says label {label}, file {file or 'none'}; RepoMind's stored "
                                  f"triage of this issue says label {stored.group(1)}, file {stored.group(2)}")

    def gate(self, step: dict) -> str:
        """Before an irreversible or gated write: "go", "skip", or "end" (the run has ended held)."""
        action = {"comment": "post_comment"}.get(role(step.get("tool")), role(step.get("tool")))
        pending = [s for s in self.signals if s["key"] not in self.answered]
        if action not in escalation.BEFORE or not pending:
            return "go"
        first = pending[0]
        answer = escalation.escalate(self, step, action, first["signal"], first["why"])
        if answer == "held":
            self.ctx.trace.end("held", detail=f"step {step.get('id')}: escalated ({first['signal']}), no answer yet")
            return "end"
        if answer == "stopped":
            self.halt(step, "stopped", f"stopped at step {step.get('id')} while its escalation waited")
            return "end"
        self.answered |= {s["key"] for s in pending}
        if answer == "approve":
            return "go"
        self.record(step, step_args(step), None, "declined")
        return "skip"

    def halt(self, step: dict, reason: str, detail: str) -> None:
        self.save_state(step, current=step.get("id"))
        self.ctx.trace.end(reason, detail=detail)

    # -- the plan, in order ------------------------------------------------------------
    def next_step(self) -> dict | None:
        return next((s for s in self.plan.get("steps") or [] if str(s.get("id")) not in self.ran), None)

    def run(self) -> None:
        while True:
            step = self.next_step()
            if step is None:
                return                            # the plan is finished; the runner writes completed
            if role(step.get("tool")) in ("apply_label", "open_pr", "comment") and self.draft is None:
                if not self.prepare(self.comment_step()):
                    return                        # held, or not filled: nothing was written
            decided = self.gate(step)             # Assignment 5: an escalation before the write
            if decided == "end":
                return
            if decided == "skip":
                continue
            if role(step.get("tool")) == "apply_label":
                if not self.label(step):
                    return
                continue
            if role(step.get("tool")) == "open_pr":
                if not self.pull_request(step):
                    return
                continue
            if role(step.get("tool")) == "comment":
                if not self.post(step):
                    return
                continue
            first = not any(role(r["tool"]) == "search" for r in self.results)
            result = self.run_step(step)
            if result is None:
                return                            # halted, and ended escalated
            if role(step.get("tool")) == "search" and (first or str(step.get("id")) in self.revised):
                found = any(SOURCE.match(p) for p in result.get("paths") or [])
                if not found:                     # an empty result is not a finding (moment B)
                    self.ctx.trace.event("not_determined", step=step.get("id"),
                                         question="which file is responsible: this search found no source file, "
                                                  "which is not evidence that none is")
                self.checkpoint(CHECKPOINT, found)

    # -- one step ------------------------------------------------------------------------
    def run_step(self, step: dict) -> dict | None:
        tool, args = step.get("tool"), step_args(step)
        if not tool:
            return self.record(step, args, None, "no_tool")
        args = self.filled(step, args)
        if args is None:
            return None
        result = self.call(step, tool, args)
        return None if result is None else self.record(step, args, result)

    def call(self, step: dict, tool: str, args: dict):
        """One tool call for a plan step; None when the registry could not confirm a
        write, and the run has ended escalated (the third exit)."""
        try:
            result = self.ctx.call_tool(self.calls, tool, args, plan_step=step.get("id"))
        except Unverifiable as exc:
            self.record(step, args, None, "unverifiable")
            self.ctx.trace.end("escalated", detail=f"step {step.get('id')}: {exc}; a person on review duty decides")
            return None
        if result.is_error and result.content.startswith("This call was not allowed"):
            if stop.requested(self.ctx.run_id):   # bin/stop: checkpoint, end stopped; a resume runs this step
                self.halt(step, "stopped", f"stopped at step {step.get('id')}; resume with python run.py --resume "
                                           f"{self.ctx.run_id}")
                return None
            if held(self.ctx.run_id):             # a gated call nobody answered: never a yes
                self.halt(step, "held", f"step {step.get('id')}: {result.content}")
                return None
        return result

    def filled(self, step: dict, args: dict) -> dict | None:
        to_fill = [k for k, v in args.items() if str(v).startswith(FILL)]   # "$fill", or "$fill: a note"
        if not to_fill:
            return args
        filled = self.fill(step, args, to_fill)
        if filled is None:
            self.record(step, args, None, "off_plan")
            self.ctx.trace.end("escalated", detail=f"step {step.get('id')}: no on-plan call in {MAX_FILL_TRIES} tries")
        return filled

    def fill(self, step: dict, args: dict, keys: list[str], *, system: str = "executor.md",
             purpose: str = "execute", note: str = "") -> dict | None:
        """One model call fills a step's "$fill" arguments, offered the step's tool alone. It
        keeps every argument the model gave that the schema knows, the ones the plan never
        mentioned included, and a null where the schema allows one (Part A's required and
        nullable fields); the plan's own values win."""
        schema = next((t for t in self.ctx.tools.schemas if t["name"] == step["tool"]), None)
        if schema is None:
            return None
        fixed = {k: v for k, v in args.items() if not str(v).startswith(FILL)}
        props = (schema.get("input_schema") or {}).get("properties") or {}
        nullable = {k for k, s in props.items() if isinstance(s, dict) and allows_null(s)}
        for _ in range(MAX_FILL_TRIES):
            self.calls += 1
            response = self.ctx.client.create(system=self.ctx.prompt(system), tools=[schema],
                                              messages=[{"role": "user", "content": self.fill_request(step, fixed, keys, note)}])
            self.ctx.trace.model_call(self.calls, response, purpose=purpose)
            for call in response.tool_calls:
                if call.name != step["tool"]:
                    self.refuse(step, call)       # the boundary: never run, always traced
                    continue
                filled = {**{k: v for k, v in call.input.items() if k in props}, **fixed}   # the plan's values win
                if any(k not in filled or filled[k] == "" or str(filled[k]).startswith(FILL)
                       or (filled[k] is None and k not in nullable)
                       for k in keys):
                    continue
                if role(step["tool"]) == "comment":
                    body = arg("comment", "body")
                    label, file = parse_triage_comment(str(filled[body]))
                    filled[body] = format_triage_comment(label or "bug", file, self.disclosure)
                return filled
        return None

    def refuse(self, step: dict, call) -> None:
        self.ctx.trace.event("off_plan", step=step.get("id"), tool=call.name, input=call.input, version=self.version)

    def history(self) -> list[str]:
        """What the run has gathered so far, one turn per step; with a compaction (Part F),
        the fact the run was told comes first, and a file read names its file, since a
        summary may drop the step that found it."""
        turns = []
        for r in self.results:
            named = f" ({(r.get('paths') or ['?'])[0]})" if self.compact_at is not None and role(r["tool"]) == "read_file" \
                else ""
            turns.append(f"## Step {r['id']}, {r['tool']}{named}, {r['status']}\n"
                         f"{self.outputs.get(str(r['id']), '')[:CONTEXT_CHARS]}")
        for message in reversed(self.heard):      # Assignment 5: the user's words, where they arrived
            turns.insert(min(message["after"], len(turns)), f"## A message from the user, during this run\n"
                                                             f"{message['text']}")
        if self.compact_at is not None and told():
            turns = [f"## A maintainer's note to this run\n{told()}"] + turns
        return turns

    def context(self) -> list[str]:
        """The history, for a fill or a critique: compacted past REPOMIND_COMPACT_AT tokens
        (Part F)."""
        turns = self.history()
        if self.compact_at is None:
            return turns
        turns = ([self.summary] if self.summary else []) + turns[self.summarized:]
        older = turns[:-KEEP]
        size = tokens("\n\n".join(turns))
        if size > self.compact_at and older and older != [self.summary]:
            self.calls += 1
            response = self.ctx.client.create(system=self.ctx.prompt("compact_steps.md"),
                                              messages=[{"role": "user", "content": "\n\n".join(older)}])
            self.ctx.trace.model_call(self.calls, response)
            self.summary = f"{SUMMARY}\n{response.text}"
            self.summarized = len(self.history()) - KEEP
            self.ctx.trace.event("compaction", threshold=self.compact_at, tokens=size, summarized=len(older), kept=KEEP)
            turns = [self.summary] + turns[-KEEP:]
        return turns

    def note(self) -> list[str]:
        """--notes on: the fact, kept in the progress file outside the history, in every call."""
        if self.ctx.notes != "on" or not told():
            return []
        self.ctx.progress_path.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.progress_path.write_text(json.dumps({
            "about": "Facts given to this run, kept outside its history so that no compaction drops them.",
            "facts": [{"stated_by": "a Ledgerline maintainer", "text": told()}],
            "steps_done": [r["id"] for r in self.results]}, indent=1) + "\n")
        kept = json.loads(self.ctx.progress_path.read_text())
        return ["## Your notes, kept outside the history\n" + "\n".join(
            f"- Stated by {f['stated_by']}: {f['text']}" for f in kept["facts"])]

    def fill_request(self, step: dict, fixed: dict, keys: list[str], note: str = "") -> str:
        parts = [f"Triage issue #{self.ctx.issue_number}. You are running step {step.get('id')} of a fixed "
                 f"plan: {step.get('action')}. Call {step['tool']} once. Fill in: {', '.join(keys)}. "
                 f"The plan fixes: {json.dumps(fixed)}."]
        if role(step["tool"]) == "comment":
            parts.append("The comment's first two lines must be:\nlabel: <bug | feature | question | docs>\n"
                         "file: <path relative to the repository root, or none>")
        if role(step["tool"]) == "open_pr":
            parts.append(f"The triage comment's draft names {self.drafted_file}. The pull request's title says what "
                         "the change fixes; its body names that file first, then proposes the change in prose.")
        notes = {k: str(v)[len(FILL):].lstrip(": ").strip() for k, v in step_args(step).items()
                 if str(v).startswith(FILL) and str(v).strip() != FILL}
        if notes:
            parts.append("The plan's notes on them: " + "; ".join(f"{k}: {v}" for k, v in notes.items()))
        if note:
            parts.append(note)
        block = memory_block(self.memory)
        first, among = [], []                     # Part F: where the fact this run was told sits
        if told() and self.compact_at is None:
            bury = int(os.environ.get(BURY) or 0)
            if bury:
                among = [buried(self.ctx.root, bury, told())]
            else:
                first = [f"## A maintainer's rule for this triage\n{told()}"]
        return "\n\n".join(parts + first + self.note() + ([block] if block else []) + among + self.context())

    def record(self, step: dict, args: dict, result, error: str | None = None) -> dict:
        tool = step.get("tool")
        text = result.content if result is not None else ""
        count, paths = None, []
        if result is not None and role(tool) in ("search", "read_file"):
            paths = result_paths(tool, args, text, result.is_error)
            count = len(paths) if role(tool) == "search" else None
        if error is None and result is not None and result.is_error:
            error = "not_found" if "no such file" in text else "tool_error"
        if error is None and role(tool) == "search" and not count:
            error = "no_matches"
        status = "skipped" if error == "skipped" else "failed" if error else "done"
        entry = {"id": step.get("id"), "tool": tool, "status": status, "count": count,
                 "paths": paths, "error_code": error, "args": args}
        self.results.append(entry)
        self.ran.add(str(step.get("id")))
        self.outputs[str(step.get("id"))] = text
        for s in self.plan.get("steps") or []:
            if str(s.get("id")) == str(step.get("id")):
                s["status"] = entry["status"]
        if result is not None or error:
            self.notice(step.get("id"), tool, text, status == "failed")
        if result is not None:
            self.completed.append({"step": step.get("id"), "tool": tool, "args": args, "key": result.key,
                                   "result": text[:CONTEXT_CHARS], "status": status, "count": count,
                                   "paths": paths, "error_code": error})
            if role(tool) == "read_file":
                self.save_state(step)             # after the expensive read, so a replay does not repeat it
        return entry

    # -- revision, at the checkpoint whose check failed --------------------------------------
    def checkpoint(self, name: str, ok: bool) -> bool:
        """True when a new version is now active."""
        if ok or self.revisions >= MAX_REVISIONS:
            return False
        self.revisions += 1
        proposed = revise_plan(self.ctx.client, self.plan, self.results, trace=self.ctx.trace)
        broken = schema_check(self.ctx, proposed, self.version + 1)
        verdict = {"valid": False, "failures": broken} if broken else validate(proposed)
        self.ctx.trace.event("revision", checkpoint=name, version=self.version + 1, valid=verdict["valid"],
                             failures=verdict["failures"])
        if not verdict["valid"]:
            return False                          # rejected: it never runs, and it counted against the bound
        before = {str(s.get("id")): {k: v for k, v in s.items() if k != "status"} for s in self.plan.get("steps") or []}
        changed = {str(s.get("id")) for s in proposed.get("steps") or []
                   if before.get(str(s.get("id"))) != {k: v for k, v in s.items() if k != "status"}}
        self.revised |= changed
        failed = {str(r["id"]) for r in self.results if r["status"] == "failed"}
        done = {str(r["id"]) for r in self.results if r["status"] == "done"}
        self.ran -= (changed & failed) - done      # a failed step the revision changed runs again
        self.version += 1
        self.plan = proposed
        self.ctx.trace.plan(self.version, proposed)
        return True

    # -- the comment's draft and the second pass, before the first write ---------------------------
    draft: dict | None = None        # the comment's arguments, checked, waiting to be posted last
    drafted_file: str | None = None

    def comment_step(self) -> dict:
        return next(s for s in self.plan.get("steps") or [] if role(s.get("tool")) == "comment")

    def prepare(self, step: dict) -> bool:
        """Draft the comment and run the second pass, before the PR or the comment is
        written. False when the run has ended, with nothing written."""
        draft = self.filled(step, step_args(step))
        if draft is None:
            return False
        final = self.second_pass(step, draft) if self.critique else draft
        if final is None:
            self.record(step, draft, None, "held")
            self.ctx.trace.end("escalated", detail=f"the draft still failed the second pass after {MAX_ROUNDS} rounds")
            return False
        self.draft = final
        self.drafted_file = parse_triage_comment(str(final.get(arg("comment", "body"))))[1] or "none"
        self.contradiction()
        return True

    def post(self, step: dict) -> bool:
        """Post the checked draft, the run's last write, behind a sync checkpoint. A
        resume posts the draft its checkpoint saved, never a new one. False when the
        run has ended."""
        step["status"] = "running"
        self.save_state(step, current=step.get("id"))
        result = self.call(step, step["tool"], self.draft)
        if result is None:
            return False
        self.record(step, self.draft, result)
        return True

    # -- the label, before the pull request (Assignment 5) -------------------------------------------
    def label(self, step: dict) -> bool:
        """Apply the label the comment's draft states. The issue and the label are fixed
        here, by code. False when the run has ended."""
        args = step_args(step)
        args[arg("apply_label", "number")] = f"issue-{self.ctx.issue_number}"
        args[arg("apply_label", "label")] = parse_triage_comment(str(self.draft.get(arg("comment", "body"))))[0] or "bug"
        step["status"] = "running"
        self.save_state(step, current=step.get("id"))
        result = self.call(step, step["tool"], args)
        if result is None:
            return False
        self.record(step, args, result)
        return True

    # -- the pull request, before the comment ---------------------------------------------------
    def pull_request(self, step: dict) -> bool:
        """Open the draft PR when the comment's draft names a file; skip the step when it
        says none. The issue and the branch are fixed here, by code. False when the run
        has ended."""
        if self.drafted_file in (None, "none"):
            self.record(step, step_args(step), None, "skipped")
            return True
        if self.pr_args is not None:              # a resume replays the saved arguments: the same key
            filled = self.pr_args
        else:
            number = self.ctx.issue_number
            args = step_args(step)
            args[arg("open_pr", "number")] = f"issue-{number}"
            args[arg("open_pr", "branch")] = f"repomind/issue-{number}"
            filled = self.filled(step, args)
            if filled is None:
                return False
            self.pr_args = filled
        step["status"] = "running"
        self.save_state(step, current=step.get("id"))
        result = self.call(step, step["tool"], filled)
        if result is None:
            return False
        self.record(step, filled, result)
        return True

    def evidence(self) -> dict:
        issue = next((self.outputs.get(str(r["id"]), "") for r in self.results if role(r["tool"]) == "read_issue"), "")
        return {"issue": issue, "results": self.context()}

    def second_pass(self, step: dict, args: dict) -> dict | None:
        mode = self.ctx.critique
        if mode not in ("self", "external"):
            return args
        body = arg("comment", "body")
        for round_ in range(1, MAX_ROUNDS + 1):
            draft = args[body]
            if mode == "external":
                verdict = verify(draft, self.ctx)
            else:
                self.calls += 1
                v = self_critique(self.ctx.client, draft, self.evidence(), self.ctx.trace, step=self.calls)
                verdict = {"passed": v["decision"] == "accept", "reasons": [v["reason"]] if v.get("reason") else []}
            reason = "; ".join(verdict["reasons"]) or None
            changed = False
            if not verdict["passed"] and round_ < MAX_ROUNDS:
                rewritten = self.rewrite(step, args, reason or "the critic asked for a revision")
                if rewritten is not None:
                    changed = rewritten[body] != draft
                    args = rewritten
            self.ctx.trace.event("critique", round=round_, mode=mode, result="pass" if verdict["passed"] else "fail",
                                 reason=reason, changed=changed, draft=draft)
            if verdict["passed"]:
                return args
        return None                               # still failing in the last round: held

    def rewrite(self, step: dict, args: dict, reason: str) -> dict | None:
        """One model call rewrites the draft with the reason, offered the comment tool alone."""
        body = arg("comment", "body")
        note = f"Rewrite the draft. The draft:\n\n{args[body]}\n\nWhy it must change: {reason}"
        return self.fill(step, {**args, body: FILL}, [body], system="rewrite.md", purpose="critique", note=note)
