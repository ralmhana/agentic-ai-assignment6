# FORMATS.md · what the checkers read

Every format a checker parses is defined here and nowhere else. If an assignment's
handout and this file ever disagree, this file wins; tell your instructor.

Sections 1 to 9 were written for Assignment 1 and still hold, with section 5 (the
tracker) rewritten for Assignment 3. Section 10 adds what Assignment 2 needs: the
plan, its trace lines, and the functions your planned way still provides. Section 11
adds what Assignment 3 needs: the definition files, the roles, the registry's
interface, the call record, the tracker's database, `make ping`'s record, the
scripted runs `make check-03` makes, and `reports/LAB_03.json`. Section 12 adds
what Assignment 4 needs: how a run is killed and resumed, the checkpoint and store
interfaces and their records, the two new events, the reopened issue and the memory
candidates, what `make check-04` reads, `reports/LAB_04.json`, and Part F's request
record and how the checker reads a forgetting. Section 13 adds what Assignment 5
needs: the actions and their classes, the autonomy policy file, the facts of a call
and the recorded day, the inbox and the rule file, the reviewer and the decisions
logs, the notification sink and the stops log, the mock remote's new tables and its
write log, the hook log, the escalation packet and the two new events, the moments,
what `make check-05` runs and reads, and `reports/LAB_05.json`. Section 14 adds what Assignment 6 needs:
the task set, the new `run_start` fields and the five constants, a run's agents and
their lines, the worker's return, the wait and stop records, the guards' interfaces
and their replays, `results/runs_06.jsonl`, `reports/LAB_06.json`, and what `make
check-06` reads.

## 1. The task, and the comment it produces

RepoMind reads an issue, finds the file most responsible, and posts **one**
comment whose first two lines are:

```
label: <bug | feature | question | docs>
file: <path relative to fixtures/repo, or none>
```

| Label | When | The file is |
|---|---|---|
| `bug` | something that should work does not | the file whose code is wrong |
| `feature` | a request for new behaviour | the file where the change would mainly go |
| `question` | the reporter asks how something works; nothing needs to change | `none` |
| `docs` | the documentation is wrong or missing | the document to fix |

Keys are case-insensitive; anything after the two lines is free text. The path is
read by `harness.formats.parse_triage_comment`: backticks, quotes and a leading
`./` or `fixtures/repo/` are ignored. Where your code posts the comment (the
direct call and the workflow), build it with `harness.formats.format_triage_comment`;
where the model posts it (the agent), the prompt must ask for exactly these two
lines. Read comments with `parse_triage_comment`, and you and the checker will
always agree on what a comment says.

Known answers are in `fixtures/answers.yaml`: six evaluation issues (4201 to
4206) and two development issues (4191, 4192).

## 2. The trace: `runs/<run_id>.jsonl`

One JSON object per line. Every line carries `run_id`, `type`, and `t` (seconds
since the run started). The runner writes the first and last lines; your code
writes the rest through `harness.trace.TraceWriter`.

| `type` | Written by | Fields |
|---|---|---|
| `run_start` | runner | `lab` (the assignment, `"04"` in this repository), `way`, `issue`, `sweep`, `backend`, `model`, `settings` (hash), `price_sheet` (read date), `critique` and `notes` (section 10.4), `switches` (section 11.9), `started` |
| `model_call` | you: `trace.model_call(step, response, purpose=None)` | `step`, `purpose` (section 10.4), `model` (the model that served it), `stop_reason`, `latency_s`, `usage` {`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `prompt_tokens`}, `cost_usd`, `tool_calls` [{`name`, `input`}], `text`, and, since Assignment 3, `tools` (section 11.10); since Assignment 4, `request` (section 12.10) |
| `tool_call` | you: `trace.tool_call(step, call, result)` in the loop, or `ctx.call_tool(step, name, input, plan_step=None)` from your own code, which calls the tool and traces it | `step`, `plan_step`, `name`, `input`, `is_error`, `latency_s`, `result_chars`, `result_excerpt`, `paths` (section 10.4) |
| `end` | you, in the loop: `trace.end(reason, detail)`; the runner writes one if you did not | `terminal_reason`, `detail` |
| `run_end` | runner | `elapsed_s`, `totals` {`model_calls`, `prompt_tokens`, `output_tokens`, `cache_read_tokens`, `total_tokens`, `cost_usd`, `unpriced_calls`, `models`}, `error` |
| `plan`, `off_plan`, `revision`, `critique`, `compaction`, `question` | you, in Assignment 2 | section 10.4 |

`prompt_tokens` is everything the model read on that call: uncached input plus
cache reads plus cache writes. `run_end.totals` comes from the metered client,
not from your trace, so a model call you forgot to trace shows up as a gap
between the two.

A **step** number is the model call a record belongs to: a tool call carries the
step of the most recent model call, or 0 before the first. In Part D's hybrid the agent's steps
restart at 1 when it takes over; nothing reads step numbers across a hand-off.

**Terminal reasons** (`harness.formats.TERMINAL_REASONS`): `model_stopped`,
`turn_limit`, `token_budget`, `wall_clock`, `tool_error`, `refusal`; `completed`,
written by the runner for a run no loop ended (the direct call, the workflow, and
a hybrid run that stayed in the workflow); and `crashed`, written by the runner
when your way raised (the error is in `run_end.error`). A hybrid run that reached
the agent ends with your loop's reason, which is how you count hand-offs.
Assignment 2 adds `escalated` (section 10.4), and two the runner writes: `quota`,
when the vendor's daily quota stops a run, and `rate_limited`, when a call is still
refused for rate limits (or, at Anthropic, overload) after every retry. Neither
counts as finished (section 9).

## 3. The loop contract

```python
run_loop(client, tools, system, user_message, bounds, trace) -> str   # agent/loop.py
```

- `client`: `harness.client.ModelClient`. `client.create(system=, messages=, tools=)`
  returns a `ModelResponse` with `.content` (append it unchanged), `.stop_reason`,
  `.tool_calls` (each has `.id`, `.name`, `.input`), `.text`, `.usage`,
  `.assistant_message()`. `client.total_tokens` is the run's running total.
- `tools`: anything with `.schemas` (a list of tool definitions) and
  `.call(name, input)`, which returns a `ToolResult` with `.content`, `.is_error`
  and `.latency_s`. The checker passes its own stub here.
- `bounds`: `agent.loop.Bounds(max_steps, max_tokens, wall_clock_s)`, loaded from
  `agent/bounds.yaml`. The checker passes its own bounds too.
- Tool results go back as one user turn of `harness.client.tool_result(call,
  content, is_error)` blocks.
- These formats are the same whatever your model's vendor: the backend
  translates them for its API.

What the checker asserts:

- **turn limit**: exactly `max_steps` `model_call` lines, then one `end` with
  `turn_limit`;
- **token budget**: one `end` with `token_budget`, and at most one call after
  `client.total_tokens` reached the budget;
- **wall clock**: one `end` with `wall_clock`, and the loop returns within one
  call of the limit.

A **step** is one model call. (Lecture 12 uses "turn" for everything between two
user messages; the course calls that an episode.)

## 4. The scripted model, and the published A (Assignment 1)

`harness.scripted.NeverStops` asks for its first offered tool on every call and
never ends its turn. Its token counts are estimates, one token per four
characters of the request's JSON. For the bounds check the checker gives it one
stub tool returning a fixed 1,600-character result.

With that stub, each step appends **A = 463** tokens (its tool call plus the
result, as the estimate counts them). The checker measures *F* as the prompt
tokens of the first call in its own run, and requires your cumulative prompt
tokens at the turn limit to be at most

```
(N × F + A × N × (N − 1) / 2) × 1.15
```

The 15% absorbs differences in how you wrap tool results.

For your report, *F* and *A* are your own. In Part A, before any run, estimate them
from your prompt and tool definitions. After Part B, replace the estimate with
values measured on your 60 evaluation agent runs: *F* is the mean, over those
runs, of the first call's `prompt_tokens`; *A* is the mean, over every pair of
consecutive calls in those runs, of the increase in `prompt_tokens`. The checker
checks only that your `cumulative_prompt_tokens` is the formula applied to your
own `F`, `A` and `N`, with `N` your `max_steps`.

## 5. The tracker: `tracker/tracker.db`

Since Assignment 3 the tracker is a SQLite database holding comments, pull
requests and its own log of write attempts (section 11.5 gives the tables). Every
write is stamped with the `run_id` of the run that made it, by the harness; the
model never sees or sets it. Every read is scoped to one run. The model never sees
a comment a run wrote: the issue-reading tool returns the issue and, from
Assignment 4, the discussion people wrote in its fixture (12.7). `make reset` archives the
database to `tracker/archive/` and starts empty; the runner never deletes a row, so
every run stays checkable. Commit `tracker/` with your runs.

## 6. The grounded check

```python
check(tracker, run_id, issue_number, answer) -> bool   # eval/check_triage.py
```

`answer` is `{"label": ..., "file": ...}` from `fixtures/answers.yaml`. The
checker calls your function on planted runs: a wrong comment whose run claims
success must return `False`; a right comment from a run that said nothing must
return `True`; a run with no comment must return `False`.

The checker's own rule, which your table must match: **a run passes when exactly
one comment carries its `run_id` on its issue, and that comment's label and file
both match the answer.**

## 7. `reports/LAB_01.json` (Assignment 1)

The template in `reports/` has every field. `results` has one entry per way:
`direct`, `workflow`, `agent` and `hybrid` (Part D). The checker compares these
exactly (counts) or within 1% (means):

| Field (per way, under `results`) | Definition |
|---|---|
| `runs` | finished runs of that way on the six evaluation issues (a run with a `run_end` line), excluding the scripted backend |
| `passes` | runs that pass by section 6's rule |
| `per_issue` | passes per issue, keyed by issue number as a string |
| `sweep_min`, `sweep_max` | passes within one sweep (one run per issue, grouped by `run_start.sweep`), lowest and highest over all sweeps |
| `all_ten` | a count (an integer, not a list): the number of issues with at least 10 runs, every one of which passed |
| `mean_prompt_tokens`, `mean_output_tokens` | mean over runs of the run's summed `model_call.usage` field |
| `mean_cost_usd` | mean over runs of the run's summed `model_call.cost_usd`, an unpriced call counting 0 |

Read by staff, not compared by the checker:

| Field | Definition |
|---|---|
| `mean_cached_tokens` | mean over runs of the run's summed `usage.cache_read_input_tokens`. Uncached prompt tokens are `mean_prompt_tokens` minus this. Nothing in the starter sets a cache breakpoint, so expect 0 |
| `p50_latency_s`, `p95_latency_s` | nearest-rank percentiles of `run_end.elapsed_s`, which includes any wait your vendor's rate limit imposed |
| `mean_tool_calls`, `max_tool_calls` | over runs, the number of `tool_call` records: every tool call, your code's and the model's |

Also required:

- `part0`: `model_calls` (distinct `message.id` values), `tool_calls`
  (`tool_use` blocks), `prompt_tokens` (input plus cache read plus cache write,
  summed over calls), `cache_read_tokens`, `cache_read_share`, `first_prompt`,
  `last_prompt`, `cumulative_over_first`. The checker recomputes six of them,
  `model_calls`, `tool_calls`, `prompt_tokens`, `cache_read_tokens`,
  `first_prompt` and `last_prompt`, from `fixtures/week01_recorded_run.jsonl`,
  each within 1%; staff read the two ratios.
- `worst_case` {`F`, `A`, `N`, `cumulative_prompt_tokens`}, where `N` is your
  `max_steps` and `cumulative_prompt_tokens` is `N·F + A·N(N−1)/2`.

`analysis`, read by staff alongside `reports/LAB_01.md`:

| Field | Definition |
|---|---|
| `ratio_agent_over_direct_tokens` | the agent's mean prompt plus output tokens per run, over the direct call's |
| `m_agent_over_workflow_cost` | *m*: the agent's `mean_cost_usd` over the workflow's |
| `f` | the share of the six evaluation issues where the workflow passes fewer than 5 of 10 runs and the agent 5 or more, a fraction between 0 and 1 |
| `blended_cost`, `all_agent_cost`, `workflow_cost` | *c* × [(1 − *f*) + *f* × *m*], *c* × *m*, and *c*, with *c* the workflow's `mean_cost_usd` |
| `path_entropy` | over the agent's evaluation runs, each run's tool names in order: `distinct_sequences`, the number of different sequences, and `top3_share`, the fraction of runs the three most common cover |
| `verdict` | `agent`, `workflow` or `hybrid`: your final verdict, after Part D |
| `hybrid_handoffs` | the number of hybrid runs that reached the agent (section 2) |

`part0.cache_read_share` and `part0.cumulative_over_first` are fractions and
ratios as plain numbers (0.973, not 97.3%).

## 8. `ARCHITECTURE.md` references

A reference is a file path and a line number joined by a colon, inside
backticks, relative to the repository root. The checker opens each one: the
file must exist, have that line, and not be under `prompts/`. Since Assignment 3 it
awards no points for them, and prints, for staff, each one that fails.

## 9. Budgets and the ledger

`settings.yaml` sets two hard ceilings the harness enforces outside your code:
`session_token_ceiling` per run (the client refuses the next call) and
`lab_token_ceiling` per assignment (the runner refuses the next run). Every run
appends one line to `runs/_ledger.jsonl`: `run_id`, `way`, `issue`, `sweep`,
`backend`, `total_tokens`, `cost_usd`, `error`, `finished`. Runs on a scripted
backend (`never-stops`, or any `harness.scripted:` model) are free and do not count
toward the assignment's token ceiling.

A **configuration** is a way with its `--critique` and `--notes` and the four
switches (section 11.9), on one backend.
Running the same `run.py` command again skips the (issue, sweep) pairs on the
evaluation issues (4201 to 4206: the measured runs, Part G's included) that
configuration has already finished, so a measurement can be split over days. Runs
on the development issues always run anew. A run
is **finished** when its trace has a `run_end` line and did not end `quota` or
`rate_limited`; a run that crashed is finished, and counts as a failure. Both
backends wait out a rate limit (429), an overload (529, or a refusal that says the
model is overloaded) as long as the vendor asks, up to six retries; a call still
refused after them ends the run `rate_limited`, and the sweep goes on. When a vendor
refuses a call because its daily quota is spent, the runner ends that run `quota`,
stops the sweep, and says so: run the same command again when the quota resets.
`python run.py --discard --way <way> [--critique ...] [--notes ...] --set eval`
(or `--issues ...`), with the switches of the arm you mean set, moves that
configuration's runs on those issues, their call records, harness logs and
progress files to `runs/discarded/`, and their rows in the tracker to
`runs/discarded/tracker_rows.jsonl`, where no checker reads them; their tokens stay
in the ledger. Every configuration's runs must come
from one version of your code: if you change it, discard and run again.

## 10. Assignment 2: the plan, the second pass, the progress file, and `reports/LAB_02.json`

### 10.1 The plan

A plan is a JSON object, and your code passes it around as a dict:

```json
{
  "meta": {"model": "the model that wrote this version", "prompt": "prompts/planner.md",
           "tools": ["read_issue", "search_repo", "read_file", "post_comment"]},
  "steps": [
    {"id": 1, "action": "read the issue", "tool": "read_issue", "args_json": "{\"number\": 4191}",
     "depends_on": [], "expected_result": "the issue's title and body", "status": "pending"},
    {"id": 2, "action": "search the code", "tool": "search_repo", "args_json": "{\"query\": \"$fill\"}",
     "depends_on": [1], "expected_result": "at least one matching path", "status": "pending"}
  ]
}
```

| Field | Read by | Definition |
|---|---|---|
| `meta.tools` | validator check 1 | the names of the tools the plan may use: the tool list the planner was given |
| `meta.model`, `meta.prompt` | staff, your log | the model that served the call that wrote this version (`response.model`), and the prompt file that call used |
| `steps` | everything | the steps, in the order they run |
| `id` | everything | unique within the plan; an integer or a string, your choice (the fixtures use integers) |
| `action` | people | what the step does, in words |
| `tool` | checks 1 and 3, the diff | the one tool the step calls, or `null` |
| `args` or `args_json` | the executor, the diff | the step's arguments: an object (`args`), or the same object encoded as a JSON string (`args_json`) |
| `depends_on` | check 2, the orphan check | the ids of the steps whose results this step uses |
| `expected_result` | check 3, the expected-result check | what the step returns when it worked, or `null` |
| `status` | the executor, the reviser | `pending`, `done` or `failed`; you may add values of your own |

An argument the executor fills in at run time, from earlier results, is the string
`"$fill"` (`harness.formats.FILL`): `{"query": "$fill"}`. Any other value is fixed
by the plan.

Your schema, `agent/plan_schema.json`, describes the object your planner's tool
returns: the steps, and any field you add. Your code adds `meta`. Any other top-level
key is yours. Whatever you add, the names and meanings above are fixed: the
fixtures use them, and the checker's scripted models write plans in your schema
by filling in these fields and giving any other field its type's empty value.

### 10.2 The functions and constants the checker uses

```python
make_plan(client, issue_number, tool_schemas, trace=None) -> dict      # agent/plan.py
revise_plan(client, plan, step_results, trace=None) -> dict           # agent/plan.py
validate(plan) -> {"valid": bool, "failures": [{"step": id, "check": n}]}   # agent/validator.py
verify(draft, ctx) -> {"passed": bool, "reasons": [str]}                # agent/critique.py
self_critique(client, draft, evidence, trace=None) -> {"decision": str, "reason": str | None}   # agent/critique.py
repeat_check(trace) -> list[list]                                       # agent/detectors.py
orphan_check(plan) -> list                                              # agent/detectors.py
expected_result_check(plan, trace) -> list                              # agent/detectors.py
ladder(plan, trace) -> dict                                             # agent/detectors.py
diff(plan, trace) -> dict                                               # agent/diff.py
run(ctx), MAX_REPLANS, MAX_REVISIONS, MAX_ROUNDS                        # ways/planned.py
run(ctx), COMPACT_AT                                                    # ways/notes.py
```

Keep these names and signatures. You may add keyword arguments with defaults; the
checker passes only these. `trace`, where a detector or the diff takes one, is a
list of trace lines as `harness.trace.read_trace` returns them.

- **`make_plan`**: `client` is a `ModelClient`; `issue_number` an int;
  `tool_schemas` the tool definitions, as `ctx.tools.schemas` gives them; `trace`
  a `TraceWriter` or `None`. Given a trace, it traces its model call with
  `trace.model_call(0, response, purpose="plan")`. It returns a plan (10.1) whose
  `meta.tools` are the names in `tool_schemas`. Its request carries nothing from
  the issue: not its body, not its title (10.8).
- **`revise_plan`**: `plan` is the active plan, its steps' statuses up to date;
  `step_results` as in 10.3. Given a trace, it traces its call with
  `purpose="revise"`. It returns the next version's plan. It never changes a step
  whose status is `done`: such a step comes back unchanged, every field but
  `status`, whatever the model wrote. It may change a step that `failed`, to retry
  it, and any step not yet run; the executor runs a failed step again once a
  revision has changed it. Its request carries no issue text and no step result's
  `args`.
- **`validate`**: one entry in `failures` for each step and check that fails, in
  any order; `step` is the step's `id`, or `None` for check 4. The four checks:
  1. the step has a `tool` and it is not in `meta.tools` (a step with no tool fails
     check 3, not check 1);
  2. some id in its `depends_on` is not the id of a step earlier in `steps`: a later
     step, the step itself, or no step at all;
  3. its `tool` is `null` or empty, or its `expected_result` is `null` or empty;
  4. the plan has no steps, or more than `max_steps` in `agent/bounds.yaml`.
- **`verify`**: `draft` is the comment's text; `ctx` the run's `WayContext`. Four
  checks, in this order: the draft **parses** by section 1 (a known label, and a
  path or `none`); a path it names **exists** under `fixtures/repo`; this run has
  **seen** that path, which means it is in the `paths` of one of this run's
  `tool_call` lines so far (read them with `read_trace(ctx.trace.path)`); and the
  label and the file **agree** (a `question` names `none`, every other label names
  a file). A draft whose file is `none` skips the second and third. `reasons` names
  each check that failed. It reads nothing the run cannot see: never the answer
  key, never the grounded check in `eval/`.
- **`self_critique`**: one model call, given the draft and `evidence` (a dict of
  your design: the issue's text and what the run's steps returned). It returns
  `decision`, `accept` or `revise`, and a `reason` (`null` on accept). Given a
  trace, it traces its call with `purpose="critique"`.
- **`repeat_check`**: an exact repeat is two `tool_call` lines with the same `name`
  and the same `input` (compared as JSON with sorted keys). It returns each group of
  repeats as the `step` numbers of its `tool_call` lines: `[[1, 3], [2, 4]]`.
- **`orphan_check`**: the ids of the steps, other than the last, that no later step
  lists in `depends_on`.
- **`expected_result_check`**: the ids of the plan steps that did not run and
  return their result: no call matched them, or the call that did was an error.
- **`ladder`**: questions 1 to 3 of Lecture 2's ladder (slide 52), each
  `{"fired": bool, "ids": [...]}`: `q1` lists groups of `tool_call` step numbers,
  as `repeat_check` does; `q2` and `q3` list plan step ids (or, for `q2` answered
  from a trace, `tool_call` step numbers). Question 4 needs judgment, so it is in
  your report.
- **`diff`**: `{"steps": {id: label}, "extra": [step numbers]}`. Every plan step is
  labelled `executed` (it ran, in plan order), `skipped` (it never ran) or
  `reordered` (it ran, out of plan order); `extra` lists the `step` numbers of the
  `tool_call` lines that match no step. How a call matches a step is yours to
  decide, by its tool and by any arguments the plan fixes: say how in your report.
- **The schema check**: `harness.schema.errors(instance, schema) -> list[str]`, one
  line per problem, `[]` when the instance fits. `ways/planned.py` checks what the
  planner's tool returned (the plan without `meta`) against
  `agent/plan_schema.json` before the four checks, and the same for a revision. A
  vendor can accept `"strict": true` without enforcing it. With it goes one more
  rule: **a plan's last step is `post_comment`**, since a plan without one passes
  all four checks and posts nothing. **Assignment 3 keeps that rule and adds to
  it** (Part C, task 1): exactly one comment step, the last, and exactly one PR
  step, right before it. The starter's `ways/planned.py` holds Assignment 2's
  rule, by role.
  A plan that breaks the schema or that rule
  writes a `schema` line and is rejected like one that fails a check: it never
  runs, it is re-planned, and it counts against `MAX_REPLANS` (a revision, against
  `MAX_REVISIONS`).
- **`ways/planned.py`**: `run(ctx)`, like every way. `MAX_REPLANS` is a whole
  number: how many times a rejected plan is re-planned before the run escalates,
  so a run makes at most `MAX_REPLANS + 1` planner calls. `MAX_REVISIONS` is a
  whole number, at least 1: the most revision attempts in a run, accepted and
  rejected alike. `MAX_ROUNDS` is 1 or 2: the most rounds of the second pass in a
  run, the same in both modes (10.5).
- **`ways/notes.py`**: `run(ctx)`; `COMPACT_AT`, a whole number of tokens: the
  context size past which it compacts (10.6).

### 10.3 `step_results`

A list with one entry per step that has run, in the order they ran. Steps that
have not run have no entry.

| Field | Definition |
|---|---|
| `id` | the plan step |
| `tool` | its tool |
| `status` | `done` (it ran and returned what it should) or `failed` |
| `count` | how many results it returned, such as search hits, or `null` when that is not a count |
| `paths` | the file paths its result names, relative to `fixtures/repo` |
| `error_code` | a short code when it failed, such as `no_matches`, `not_found`, `tool_error` or `off_plan`; otherwise `null` |
| `args` | the arguments it ran with, as its `tool_call` line records them. They may carry text taken from the issue, such as a search query, so `revise_plan` never sends them to the model |

### 10.4 The trace lines Assignment 2 adds

| `type` | Written by | Fields |
|---|---|---|
| `run_start` | the runner | as in section 2, with `critique` (`off`, `self` or `external`, from `run.py --critique`; `off` by default) and `notes` (`off` or `on`, from `run.py --notes`; `off` by default). Your way reads them as `ctx.critique` and `ctx.notes` |
| `model_call` | `trace.model_call(step, response, purpose)` | as in section 2, with `purpose`: `plan` (the planner), `revise` (the reviser), `execute` (the executor filling in a step), `critique` (a self critique, or a rewrite of the draft), or `null` (any other call: Assignment 1's ways, a compaction's summary, Part G's questions) |
| `tool_call` | `ctx.call_tool`, or `trace.tool_call` | as in section 2, with `paths`: the files the call returned, every path in a `search_repo` result or the file a `read_file` call read, and `[]` for any other tool or an error, which is what "this run saw that path" means; and `plan_step`: the id of the plan step the executor ran this call for, passed as `ctx.call_tool(step, name, input, plan_step=id)`, or `null` outside a plan (Assignment 1's ways, and the transcribed runs in `fixtures/traces/`) |
| `plan` | `trace.plan(version, plan)` | `version` (1, 2, ...), `plan` (10.1) |
| `off_plan` | `trace.event("off_plan", step=..., tool=..., ...)` | `step` (the plan step being run), `tool` (the tool the model asked for); any other field you add, such as `input` |
| `revision` | `trace.event("revision", checkpoint=..., version=..., valid=..., ...)` | `checkpoint` (the checkpoint's name), `version` (the version the revision would become), `valid` (whether it passed your validator); any other field you add, such as `failures` |
| `critique` | `trace.event("critique", round=..., mode=..., result=..., reason=..., changed=..., draft=...)` | one round of the second pass (10.5): `round` (1, 2), `mode` (`self` or `external`), `result` (`pass` or `fail`), `reason` (`null` on a pass), `changed` (whether the draft's text changed this round; a rewrite that returns the same text is not a change), `draft` (the draft this round checked) |
| `compaction` | `trace.event("compaction", threshold=..., tokens=..., ...)` | `threshold` (your `COMPACT_AT`), `tokens` (the context's size when it compacted); any other field you add |
| `question` | `trace.event("question", path=..., answer=...)` | Part G: `path` (the path asked about), `answer` (`yes` or `no`, as the model answered) |
| `schema` | `trace.event("schema", errors=[...], ...)` | a plan or revision that broke `agent/plan_schema.json`: `errors`, as `harness.schema.errors` gives them; any other field you add, such as `version` |
| `end` | `trace.end("escalated", detail)` | the way handed the issue to a person: no valid plan within `MAX_REPLANS`, a step the executor could not run, or a draft held at the second pass's bound; from Assignment 3, also a write that could not be confirmed (the third exit). An escalated run writes nothing after it escalates; in Assignment 3 it may leave the PR it opened first, or a comment it could not confirm. (`quota` is the runner's, section 9) |

`trace.event(kind, **fields)` writes any other kind of event too, as long as it is
not a line type the harness writes. The rules a checker reads:

- **Plan before action.** Version 1's `plan` line comes before the run's first
  `tool_call` line, in the planned way and the notes way.
- **The checkpoint.** Part C's check runs after the first search step, and again
  after any search step a revision added or changed, until `MAX_REVISIONS` is
  spent. So every `revision` line comes right after a `search_repo` `tool_call`
  line. The check is yours, in code; for example, "the search returned at least
  one source file" (a `.ts` or `.tsx` file under `src/`), "not only documentation
  or translations" (`README.md`, `CHANGELOG.md`, `docs/`, `src/i18n/*.json`).
- **Only a valid version is logged.** A revision that passes your validator gets a
  `revision` line with `valid: true` and then its `plan` line. One that fails gets
  a `revision` line with `valid: false` and no `plan` line: it never runs, and it
  counts against `MAX_REVISIONS`.
- **The active version** at any line is the latest `plan` line above it. Every
  `tool_call` after the first `plan` line belongs to the active version: its
  `plan_step` is the id of one of that version's steps, and its `name` is that
  step's `tool`. A diff matches a call to its step by `plan_step` where the line has
  one, and by tool and fixed arguments where it does not (`fixtures/traces/`).
- **A tool call is acted on whatever `stop_reason` says.** A model can return a call
  with `stop_reason` `end_turn`; a loop or an executor that reads only
  `stop_reason == "tool_use"` would drop it.
- **Step numbers.** `make_plan` and `revise_plan` trace their calls as step 0. The
  executor numbers its own calls from 1, as Assignment 1's loop does, and a tool
  call carries the step of the most recent call, or 0 before the first. The
  checker reads `purpose` and the order of lines, never step numbers.

### 10.5 The second pass

Before `post_comment`, in the mode `ctx.critique` names. In `off` there is no
second pass: no `critique` line and no `critique` call. In `self` and `external`, at
most `MAX_ROUNDS` rounds:

1. A round checks the current draft: `verify(draft, ctx)` in `external` (code, no
   model call), `self_critique(...)` in `self` (one call). Its result is `pass` for
   a passed `verify` or an `accept`, `fail` otherwise.
2. A draft that fails, with a round left, is rewritten by one model call given the
   reason, traced with `purpose="critique"`; the next round checks the new draft.
3. The round writes its `critique` line.
4. A draft that passes is posted (in Assignment 3, after the PR step: Part C, task
   1). A draft that fails in the last round is held: it is not posted, and the run
   ends `escalated`.

So `MAX_ROUNDS = 1` is a gate (check once; post or hold), and `MAX_ROUNDS = 2` checks,
rewrites once, and checks again. Nothing is posted until the last round, and a run
posts one comment at most.

### 10.6 Part G: the progress file, the compaction, the questions

- **The progress file** is `ctx.progress_path`, `runs/<run_id>.progress.json`: a
  JSON object written after every step, with at least `steps_done` (the ids of the
  steps that have run, in order) and `paths` (every path a search returned or a
  read read, in order), and **never a search term**: terms come from the issue's
  text. Say in the file what it records, with an `about` line or labelled keys: a
  bare list of paths can be read as a to-do list. With `ctx.notes == "on"`, every
  executor call and the questions' call after its first write carry the file's text
  exactly as written, and the planner's and the reviser's calls do not; with `off`,
  none does, and the file is still written.
- **The history and the compaction**: every executor call sees the run's history so
  far, its step results oldest first. Once that history passes `COMPACT_AT`
  tokens, the oldest entries become one model-written summary, and the recent ones
  stay as they were. Each compaction writes a `compaction` line. It runs whatever
  `ctx.notes` says.
- **The questions**: at the end of every run, however it ended (comment posted,
  escalated, halted), one model call asks six closed questions, each "Has this run
  seen `<path>`: did a search return it, or did you read it?", and returns six
  answers, `yes` or `no`, each written as a `question` line, the six together. If
  the run has not compacted yet, it compacts its history once first, so every run
  asks after a compaction. They ask about the three earliest paths the run saw (all
  of them if it saw fewer), and fill the six with paths it did not see: a run that
  saw two paths asks about both and four it did not. A path **was seen** when a `tool_call`
  line above the question has it in its `paths`, that is, a search returned it or a
  read read it, whatever the model says.
- **Part G's runs** are the `--way notes` runs on issues 4203, 4204 and 4206: two
  per issue with `--notes off`, two with `--notes on`, 12 in all. A notes run on a
  development issue is development, and nothing reads it.

### 10.7 The fixtures

- `fixtures/plans/*.json`: plans as in 10.1, with `args` as objects. Each carries
  its own `meta.tools`, so check 1 reads the plan's tool list, never RepoMind's.
  `s18_specimen.json` is slide 19's plan with the fields the slide leaves out.
- `fixtures/traces/<run>/plan.json` and `trace.jsonl`: a plan (10.1) and its trace
  (section 2's lines, transcribed: no token counts, `usage` is `null`).
  - `looping/`: the looping run. Each turn is one `model_call` and one `tool_call`,
    both with `step` equal to the turn; turn 7 is the `end` line. Its plan has no
    `depends_on`.
  - `s49/`: slide 53's export-bug run. Its six tool calls are steps 1 to 6, and
    its closing report is the `model_call` at step 7; each line keeps the slide's
    time in `at`. Its plan is the one the slide's notes describe.

### 10.8 Sentinels

Every issue body ends with a line `<!-- sentinel: SNTL-WORD-WORD -->`, unique to
that issue (`harness.formats.SENTINEL` reads it). The checker calls `make_plan`
for every issue, and `revise_plan` with step results whose `args` carry a
sentinel, through a scripted client that keeps every request: no request either
function sends may contain any issue's sentinel.

### 10.9 The scripted models

`harness/scripted.py` has these for this assignment, each free, and left out of the
checker's results and of `lab_token_ceiling`. Each writes plans in your schema
(10.1): read the issue, search (`"$fill"`), read a file (`"$fill"`), post the
comment (`"$fill"` body); in Assignment 3, with the PR step before the comment
(11.7). The last column names Assignment 2's checker.

| Model | What it does | The checker uses it for |
|---|---|---|
| `AlwaysInvalidPlanner` | every plan it writes fits a strict schema (every field a value of its type) and ends with `post_comment`, but its first step names an unknown tool, depends on a later step and has an empty `expected_result`: checks 1, 2 and 3 | Reject exit: `ways/planned.py` on issue 4191 |
| `OffPlanExecutor` | writes a valid plan; asked to fill in a step, calls another tool (`post_comment`, or `search_repo` when `post_comment` is the step's tool), marked `off-plan-probe` | Boundary: `ways/planned.py` on issue 4192 |
| `RecordingPlanner` | writes a valid plan and keeps every request; as a reviser, rewrites the first step | Plan before untrusted text, and Revision |
| `SchemaBreakingPlanner` | every plan passes the four checks but breaks your schema: each step lacks `action` and has a property the schema does not, as a vendor that does not enforce strict mode can return | Reject exit: `ways/planned.py` on issue 4191 |
| `NoCommentPlanner` | every plan passes the four checks but has no final `post_comment` | Reject exit: `ways/planned.py` on issue 4191 |
| `ScriptedTriage` | fills the plan in: searches for `dedupeKey`, reads `src/ingest/dedupe.ts`, drafts a comment naming its `DRAFT_PATH` (a rewrite too), and accepts in a self critique. Offered no tool, it answers with the draft comment when the request's messages mention "rewrite", "draft" or "comment", and "yes" otherwise. It keeps every request, and whether each showed a watched progress file | Notes and compaction: `ways/notes.py` on issue 4191 with `--notes off` |
| `RefusesToRead` | `ScriptedTriage`, but asked to fill in a `read_file` step it answers that it has no path, so the run ends before its comment | Notes and compaction: `ways/notes.py` on issue 4191; the run must still compact and ask its six questions |
| `SentinelSearcher` | `ScriptedTriage`, searching for the issue's own sentinel, as a model copying the issue would: the search finds nothing and the checkpoint revises | Notes and compaction: `ways/notes.py` on issue 4191 with `--notes on`; the sentinel must reach neither the progress file nor a reviser's request |
| `DraftNamesSeenFile`, `DraftNamesUnseenFile`, `DraftNamesMissingFile`, `DraftNamesNoFile` | `ScriptedTriage`, drafting `src/ingest/dedupe.ts` (the run saw it), `src/util/money.ts` (it exists; the run never saw it), `src/export/tsv.ts` (it does not exist), and `label: bug` with `file: none` (they disagree) | Second pass: `ways/planned.py` on issue 4192, in `off` and `external` |

Run any of them yourself: `--backend harness.scripted:<Model>`.

### 10.10 `reports/LAB_02.json`

The template in `reports/` has every field.

| Field | Definition |
|---|---|
| `schema.args_representation` | `args_json` or `oneOf`: how your schema writes a step's arguments |
| `schema.optional_fields`, `schema.union_types` | counted as in 10.11 |
| `schema.strict_compiles` | `true` if a strict request carrying the schema was accepted, `false` if it was refused, `null` if your vendor has no strict mode |
| `fixture_validation` | one entry per file in `fixtures/plans/`: `{"plan": file name, "valid": bool, "failures": [...]}`, as `validate` returns them |
| `ladder.looping`, `ladder.s49` | each `{"q1": ..., "q2": ..., "q3": ...}`, as `ladder` returns them |
| `diff_s49` | `diff`'s result for `s49`, with step ids as strings |
| `results` | one entry per configuration of Part F, below |
| `context` | one entry per Part G run, below |

**`results`** has four entries, one per configuration: `agent` (`--way agent`),
`planned_off`, `planned_self` and `planned_external` (`--way planned` with that
`--critique`). Each counts the finished runs (section 9) of its configuration in
this assignment (`run_start.lab` is `"02"`) on the six evaluation issues, excluding
scripted backends. A configuration is complete at 18 finished runs, 3 per issue. A field that does not apply to a configuration is `null`: the
plan's fields for `agent`, the second pass's for `agent` and `planned_off`.

| Field | Definition |
|---|---|
| `runs` | the configuration's finished runs |
| `passes` | runs that pass by section 6's rule |
| `per_issue` | passes per issue, keyed by issue number as a string |
| `sweep_min`, `sweep_max` | passes within one sweep, lowest and highest over all sweeps |
| `mean_tokens` | per run, the `prompt_tokens` plus `output_tokens` of its `model_call` lines; the mean |
| `p50_latency_s`, `max_latency_s` | of `run_end.elapsed_s`: the nearest-rank median, and the slowest |
| `plan_overhead_share` | per run, the `prompt_tokens` of its `plan` and `revise` calls over the `prompt_tokens` of all its calls (0 for a run with none); the mean |
| `critique_overhead_share` | the same, for its `critique` calls |
| `runs_with_repeat` | runs with at least one exact repeat (10.2) |
| `off_plan` | the number of `off_plan` lines over the configuration's runs |
| `revisions_mean`, `revisions_max` | `revision` lines per run, accepted and rejected alike |
| `rounds_mean`, `rounds_max` | `critique` lines per run |
| `drafts_changed` | runs with a `critique` line whose `changed` is true |
| `drafts_fixed`, `drafts_broken` | of those, the runs whose first draft (the first `critique` line's `draft`) fails section 6's rule and whose run passes; and the runs whose first draft passes it and whose run fails |
| `drafts_held` | runs whose last `critique` line is a `fail` and that posted nothing |

The checker compares `runs`, `passes`, `per_issue`, `sweep_min` and `sweep_max`
with the tracker exactly, and awards a configuration's points only when it is
complete. It recomputes the others from your traces and notes any difference,
without points; staff read them with Part F.

**`context`** has one entry per Part G run (10.6), and no other: never a
development run.

| Field | Definition |
|---|---|
| `run_id`, `issue` | the run |
| `notes_shown` | `true` for a run with `--notes on` |
| `compacted` | whether a `compaction` line comes before its first `question` line |
| `questions` | one entry per `question` line, in order: `{"path", "truth", "answer"}`, where `truth` is `yes` if a `tool_call` line above it has the path in its `paths` (10.6: a search returned it, or a read read it), and `answer` is the line's |
| `right` | how many questions have `answer` equal to `truth` |

The checker recomputes every `context` entry from the trace, and awards its points
only when all 12 of Part G's runs have finished.

### 10.11 How the checker reads your schema

It reads `agent/plan_schema.json`, following any local `$ref`.

- **Strict shape.** Every object with properties has `additionalProperties: false`
  and lists every property in `required`. No object is free-form (an object with
  no fixed properties).
- **Optional fields**: properties not listed in `required`, over every object.
- **Union types**: every field (a property, or an array's `items`) that accepts more
  than one shape: a `type` list of two or more, such as `["string", "null"]`, or an
  `anyOf` or `oneOf` of two or more. A nullable field counts.
- **Sizes**: object properties, summed over every object; nesting, counted in levels
  from the top object (1), each property or `items` one level deeper.
- **Compiles.** Your planner's request offers a tool whose `input_schema` is the
  file's content. If `strict_compiles` is `true`, that tool carries
  `"strict": true`, and your planned runs on a real model include a `plan` call.
  `true` means a strict request was **accepted**, not that the vendor enforced the
  schema: some accept `"strict"` and return plans that break it, which is why your
  way checks every plan with `harness.schema.errors`. `null` is accepted only when
  your provider has no strict mode: Anthropic and OpenAI itself have one, so for
  them the answer is `true` or `false`; another OpenAI-compatible endpoint may not.

## 11. Assignment 3: tools, keys, the call record, and `reports/LAB_03.json`

### 11.1 The definition files

Each tool is two files with one name, in `tools/`: `<module>.json`, its
definition, and `<module>.py`, its code. The five module names are fixed:
`read_issue`, `search_repo`, `read_file`, `post_comment`, `open_pr`
(`tools.MODULES`). Rename a tool by changing `name` inside its `.json`; never rename
the files.

| Field | Definition |
|---|---|
| `name` | the tool's name, as the model calls it |
| `description` | what the model reads; your registry may add the examples to its end |
| `input_schema` | the JSON schema of the arguments |
| `strict` | `true` or `false`: whether the request asks your vendor to compile the schema |
| `examples` | a list of at least two, each `{"input": {...}, "note": "..."}`: the first a typical call, the second a hard one. Each `input` must be a valid call |

Anything else in the file is yours. The vendor gets only `name`, `description`,
`input_schema` and `strict` (`tools.SENT`). `python tools/audit_schemas.py` (or
`make audit`) checks the five files against `tools/audit_limits.yaml`; the checker
runs the same audit.

A write tool's `run()` takes one argument that is never in its definition,
`idempotency_key`, which your registry passes and the tracker enforces.

### 11.2 The roles: `tools/roles.yaml`

RepoMind has five roles, and the checker, the scripted models, the trace and the
harness's own tests find your tools through them, whatever you call the tools:

| Role | The tool that | Its arguments the file names |
|---|---|---|
| `read_issue` | reads one issue | `number` |
| `search` | searches the code | `query`, `path` (the path filter) |
| `read_file` | reads one file | `path` |
| `comment` | posts the triage comment | `number`, `body` |
| `open_pr` | opens the draft pull request | `number`, `branch`, `title`, `body` |

Each line maps a role to your tool's name and each of the role's arguments to your
argument's name: `search: {tool: code_search, args: {query: query, path:
path_glob}}`. Keep it up to date as you rename; the audit fails while it names a tool
or an argument that does not exist.

When the checker or a scripted model calls a tool, it starts from the `input` of
that tool's **first example** and sets the role's arguments
(`harness.scripted.role_call`). An issue number is written as the example writes
it: `4192` if the example has a number, `"issue-4192"` if it has `"issue-4190"`.
Every other argument keeps the example's value. So your first example must be a
typical, valid call.

`roles.yaml` names only these role arguments. Any other argument a tool has is
yours, and nothing outside your code needs its name.

The `paths` of a `tool_call` line (section 10.4) come from the result by role
(`harness.formats.result_paths`): for the search tool, every hit in the text format
`path:line: text`, or, when the result is JSON, every string under a key named
`path`, except one holding a glob character (`*`, `?`, `[`, `{`), such as a path
filter echoed back; for the read-file tool, the path it was asked for. Put each
hit's file under `path`, and nothing else that is not a file. The starter's
`ways/planned.py` finds each tool by role, the same way.

### 11.3 The registry's interface

```python
ToolRegistry(ctx)                       # tools/__init__.py; default_tools(ctx) builds one per run
registry.schemas -> list[dict]          # what the vendor gets: name, description, input_schema, strict
registry.names() -> list[str]           # in tools.MODULES order
registry.definition(name) -> dict       # the whole definition file
registry.hooks -> list                  # each hook(name, tool_input) runs before every call
registry.call(name, tool_input, plan_step=None) -> ToolResult   # .content, .is_error, .latency_s
```

`RunContext` carries `run_id`, `tracker`, `repo_root`, and, from the runner,
`calls` (the call record, 11.4), `harness_log` (a path,
`runs/<run_id>.harness.log`) and `switches` (11.9). `ctx.call_tool(step, name,
input, plan_step=id)` passes the plan step's `id` to `call`, which is how a key is
derived from it; the agent's loop calls `tools.call(name, input)` with no plan step.

- **A hook** is called as `hook(name, tool_input)`. It allows the call by returning
  `None`; it denies it by returning anything else (a string is the reason) or by
  raising. A denied call never runs the tool, comes back with `is_error: true`, and
  leaves a call-record line whose outcome is `denied`. The checker appends hooks of
  its own to `registry.hooks` and expects this of each.
- **A protocol error** (an unknown tool, arguments that are not an object) is
  written in full to `ctx.harness_log`. The model gets either nothing (the call
  raises, and the agent's loop ends the run `tool_error`) or a generic `is_error`
  result: at most 200 characters, naming neither the unknown tool nor any of yours.
- **A boundary rejection** never runs the tool. Its `is_error` result names every
  field that is wrong, and says what would be right.
- **A write** is checked before every attempt: an open PR from
  `repomind/issue-<n>` in this run, or a comment with this attempt's key. A write
  makes at most three attempts, in both of Part D's arms; one still unconfirmed
  after the third ends the run as below.
- **A write that cannot be confirmed**, the third exit, ends the planned run
  `escalated`: your executor writes `trace.end("escalated", ...)` when your registry
  says so. How your registry says so is yours.

### 11.4 The call record: `runs/<run_id>.calls.jsonl`

One line per attempt of every call your registry handles, written with
`ctx.calls.write(...)` (`harness/calls.py`), which adds `run_id`, `t` and `role`,
and from Assignment 5 `at`, the time to the millisecond (`harness.clock`).

| Field | Definition |
|---|---|
| `tool`, `role` | the name called, and its role (`null` for an unknown tool) |
| `args` | the arguments as the tool received them: for a write, the ones its key hashes |
| `plan_step` | the plan step's `id`, or `null` |
| `key` | the idempotency key sent with a write; `null` for a read |
| `attempt` | which attempt of this call the line reports, from 1 |
| `outcome` | `ok`, `error` (the tool ran and failed), `rejected` (the boundary refused it), `denied` (a hook), `timeout` (a write timed out; it may have happened), or `protocol` |
| `is_error` | whether this attempt came back as an error: `true` for a timeout, even one your registry then resolves; for the attempt whose result the model gets, what the model was told |
| `result` | a summary of what came back, at most 300 characters |
| `latency_s`, `cost_usd` | the call's; `cost_usd` is 0 for RepoMind's local tools |

A write that timed out and that you then found by reading it back may leave a
second line for the same attempt, outcome `ok`. **Every row the tracker holds for a run
must match a line of that run's call record with the same key and an outcome of
`ok` or `timeout`.**

### 11.5 The tracker's database

`tracker/tracker.db`, three tables (Assignment 5 adds five more and three columns
of `prs`: section 13.6). A column `key` is unique in `comments` and in
`prs`: a write whose key the tracker has seen writes nothing and returns the first
write's row, with `"replayed": true`.

| Table | Columns |
|---|---|
| `comments` | `id`, `run_id`, `issue`, `body`, `key`, `posted_at` |
| `prs` | `id`, `run_id`, `issue`, `branch`, `title`, `body`, `draft` (1), `state` (`open`), `key`, `opened_at` |
| `attempts` | `id`, `run_id`, `kind` (`comment` or `pr`), `issue`, `key`, `outcome`, `row_id`, `at` |

`attempts.outcome` is `written`, `replayed`, `timeout_after_commit` (the write
happened, and the caller was told it timed out) or `timeout_before_commit` (it never
reached the tracker). A repeated key that then times out is logged
`timeout_after_commit` too: the write it repeats had committed. That table is the
tracker's own log, for your Part D count
and the checker; your harness must never read it to decide anything, and the
checker flags code in `tools/`, `ways/` or `agent/` that does.

Your harness reads through the tracker, always for one run:
`comments(run_id, issue=None)`, `comment_by_key(run_id, key)`, `prs(run_id,
branch=None, state="open")`, `pr_by_key(run_id, key)`. A write raises
`TrackerTimeout` when it times out, whether or not it happened; under
`READBACK_FAIL`, once one of a run's writes has timed out, every one of those reads
for that run raises `ReadbackUnavailable`.

### 11.6 `make ping` and `runs/_ping.jsonl`

`make ping`'s third call sends your five definitions, exactly as `registry.schemas`
returns them, in one request. Each try appends a line:

| Field | Definition |
|---|---|
| `at`, `backend`, `model`, `served_by` | when, and through what |
| `tools`, `strict` | the five names, and each one's `strict` |
| `definitions` | a hash of the definitions as sent (`harness.ping.definitions_hash`) |
| `accepted` | whether the vendor accepted the request; `error` holds its words when it did not |

The checker reads the latest accepted line whose `definitions` hash is that of your
definitions now. Change a definition, and run `make ping` again. A ping through a
scripted model (`--backend harness.scripted:...` or `never-stops`) is recorded,
and tests the plumbing, but the checker never counts it.

### 11.7 What the checker runs

Every run below uses a fresh tracker in a scratch directory and a scripted model,
so nothing reaches your `runs/` or your tracker.

- **Searches.** Through your registry, the search tool with a query that matches
  nothing, then four malformed searches: an empty query, a whitespace-only query, a
  5,000-character query, and a path filter `src/[unclosed`. The first must succeed
  with JSON carrying `count: 0` and `query_valid: true`; each of the others must be
  an `is_error` result.
- **The boundary.** For each tool, its first example with one change: a required
  argument dropped, an unknown argument `zz_unexpected` added, or one argument of
  the wrong type. Each must come back `is_error`, name the argument, never run the
  tool's `run()`, and write nothing.
- **A near miss.** The read-file tool with the path `src/report.ts`, which does not
  exist: `is_error`, naming `src/reports.ts`, `src/Report.ts` and `src/report.tsx`.
- **An unknown tool.** `ways/agent.py` on issue 4191 with `UnknownToolCaller`
  (`harness/scripted.py`), whose first reply calls `repo_delete_branch` and whose
  next ends the turn (11.3, a protocol error).
- **Writes.** `ways/planned.py` on issue 4192 with `ScriptedTriage`, whose plan is
  five steps: read the issue, search, read a file, open a PR from
  `repomind/issue-4192` (title and body `"$fill"`), and post the comment, last. The
  tracker's write attempts fail in a chosen order, the PR's attempts first:
  - **A**: the PR's first attempt times out before it commits, and its retry goes
    through; then the comment commits and times out. Want one open PR, in the call
    record the PR's timeout followed by a retry with the same key that succeeds,
    and one comment, read back, with the run going on to finish.
  - **B**: the PR commits and then times out, under `READBACK_FAIL`. Want the run
    to end `escalated`, the one PR that committed, and no comment.
  - **C**: the PR and then the comment each commit and time out, under
    `KEY_MODE=uuid` and `VERIFY=off`. Want a duplicate comment: your registry obeys
    the control's switches.
- **Hooks.** A hook that raises, then one that returns a reason, each on a valid
  comment call. Want a denied call (11.3) and no comment.

The checker also prints **integrity flags**, which carry no points and which staff
read: a file in `tools/`, `ways/`, `agent/` or `prompts/` that names an evaluation
issue's answer file from `fixtures/answers.yaml` (`src/ingest/dedupe.ts`, the file
the scripted models and the tests use, is one), or names `answers.yaml` itself; code
in `tools/`, `ways/` or `agent/` that reads the tracker's `attempts` table; and any
change to `tools/audit_schemas.py` or `tools/audit_limits.yaml`. Take the files your
definitions' examples name from the rest of the codebase.

### 11.8 `reports/LAB_03.json`

The template in `reports/` has every field.

| Field | Definition |
|---|---|
| `strict` | `{tools, optional_params, union_types, compiles}`: the strict tools, optional parameters and nullable or union-typed parameters across your five definitions, as `audit_schemas.py` counts them; `compiles` is `true` if a request carrying all five, with strict mode on, was accepted (11.6), `false` if your vendor refused it, and `null` if none of your definitions asks for strict mode (your vendor has none, or refused it and you turned it off) |
| `failures` | keyed by role, each `{transient, permanent, ambiguous}`: lists of failures, in words |
| `protocol_error_policy` | `end_run` or `generic_result` |
| `surface` | `{tokens_before, tokens_after, list_tokens_before, list_tokens_after, calls_per_run, cost_per_run_before, cost_per_run_after, cost_per_run_all_five}`: the prompt tokens of the five definitions in one request, the starter's and yours; of the planner's tool list (`agent.plan._tool_list`), the starter's and yours; the mean model calls per run in your harness arm; and the price of a mean harness-arm run's definitions at your model's uncached input rate, each call charged for what it carried (11.10), with the starter's counts, with yours, and as if every call, the planner's and reviser's included, had carried all five of yours and nothing else |
| `writes.harness`, `writes.control` | each arm's counts, below |

Each arm counts its finished runs (section 9) on the six evaluation issues, from
the tracker's database:

| Field | Definition |
|---|---|
| `runs` | the arm's finished runs |
| `comments_per_run_max` | the most comments any one run left on its issue |
| `duplicate_comment_runs` | runs with more than one comment on their issue |
| `prs_correct_runs` | runs whose PRs are exactly what their comment asks for: one open PR from `repomind/issue-<n>` when the run's first comment names a file, none when it says `none` or there is no comment, and no PR from any other branch |
| `committed_timeouts` | rows of `attempts` for the arm's runs with outcome `timeout_after_commit` |
| `escalated` | runs that ended `escalated` |
| `triage_passes` | runs that pass by section 6's rule |

The checker computes the same from the database and prints any difference for
staff; it awards no points for this file but the `strict` object.

### 11.9 The switches and Part D's two arms

The runner records the four switches (`harness/switches.py`) in every `run_start`
line as `switches`: `{flaky_writes, readback_fail, key_mode, verify}`.

| Arm | Command | `switches` |
|---|---|---|
| Your harness | `FLAKY_WRITES=1 python run.py --way planned --set eval --runs 2` | `{true, false, "derived", "on"}` |
| The control | `FLAKY_WRITES=1 KEY_MODE=uuid VERIFY=off python run.py --way planned --set eval --runs 2 --start-sweep 3` | `{true, false, "uuid", "off"}` |

The checker sorts your runs into the arms by `switches` alone, and wants 12 finished
runs in each. Under `KEY_MODE=uuid` your registry sends a fresh random key on every
attempt; under `VERIFY=off` it skips the read-back after a failed write and retries
blind. Everything else stays as it is, the check before every attempt and the
three-attempt bound included. So the control's check before `open_pr` still finds
its own PR by branch, while its check before a comment, by a key that changes on
every attempt, never finds the comment it already wrote.

In Assignment 3, `make reset` archived the tracker's database to `tracker/archive/`
and moved every earlier run of that assignment on the evaluation issues to
`runs/discarded/`. From Assignment 4 it only archives the database (12.1).

### 11.10 The trace's `tools`, on every `model_call` line

Since Assignment 3 every `model_call` line carries `tools`: the names of the tools
that call's request carried, in order (`[]` for none). The harness's client records
them (`response.offered`); your code writes nothing new. In the planned way a
`plan` or `revise` call carries `submit_plan`, with your five as a text list in its
message, and a fill call carries its step's tool alone.


## 12. Assignment 4: kills, resumes, checkpoints, the store, the request record, and `reports/LAB_04.json`

### 12.1 Steps, kills and resumes

**A step** is one step of the plan, counted in the order the plan's steps first call
a tool: step 1 is the first plan step to call one, step 2 the next, and a step that
calls a tool again keeps its number. A plan step that never calls a tool, such as a
skipped PR, has no number. In a five-step plan that opens its PR, the steps are
read the issue, search, read a file, open the PR, post the comment.

- `python run.py --way planned --issues N --die-after-step K` ends the process with
  `kill -9` just after step K's tool call returns: before your code sees the
  result, so before anything your way would save after it.
- `--die-during-step K` ends it while step K runs. For a write, that is once the
  tracker has committed the write and before the reply comes back: the comment or
  PR is in the database, the process never learned it, and the call record has no
  line for that attempt. For a read, it is before the read runs.
- A kill needs one issue and one run. The runner prints the killed run's `run_id`
  as it dies. If the run never reaches step K, it finishes uncrashed and the runner
  says so.
- `python run.py --resume <run_id>` runs a crashed run's way again, under the same
  `run_id`, with the backend, way, issue, `--critique`, `--notes` and switches its
  `run_start` recorded, whatever the environment says now. It refuses a run whose
  trace has a `run_end` line. Your way finds out that it is a resume by asking your
  checkpointer for the run's last checkpoint.
- Every run runs anew: nothing is skipped because an earlier run finished.
- `make reset` archives the tracker's database to `tracker/archive/` and starts it
  empty. It leaves `runs/` and `state/` as they are. The checker reads the live
  database and every archive.

### 12.2 What a kill and a resume leave behind

| Where | What |
|---|---|
| `run_start.die` | `{"when": "after" \| "during", "step": K}` for a run started with a kill, else `null` |
| the trace of a killed run | no `end` and no `run_end` line; it stops wherever the kill found it |
| a `resume` line | written by `--resume` when it reopens the trace: `{"type": "resume", "resumed": 1, "backend", "model", "switches", "started"}`. The resumed half follows it, ending with `end` and `run_end` as any run does |
| `runs/<run_id>.calls.jsonl` | appended to by the resumed half. A write killed during its step is in the tracker with no line here: the process never learned it happened (section 11.4's match of rows to lines does not hold for it) |
| `runs/_ledger.jsonl` | a killed run's row, with `killed: "after step 3: ..."` and the tokens it spent, written just before the kill; a resumed half's own row, with `resumed: true` |

### 12.3 The two events

| `type` | Written by | Fields |
|---|---|---|
| `checkpoint` | `trace.event("checkpoint", step=..., mode=...)`, by your way, every time it saves one | `step`: the id of the plan step the checkpoint belongs to: the write it comes before, or the read it comes after; `mode`: `sync`, `async` or `exit` |
| `store_read` | `trace.event("store_read", issue=..., records=[...])`, by your way, every time it reads the store | `issue`: the issue it read for; `records`: the IDs of the records the read returned, `[]` for none |

### 12.4 The checkpointer, and a checkpoint

`state/checkpointer.py` is yours. The checker calls it with these signatures:

| Call | Returns |
|---|---|
| `Checkpointer(path=None)` | your checkpointer, on your default file when `path` is `None` |
| `.save(run_id, checkpoint, *, step, mode)` | `None`. Durable before it returns when `mode` is `sync` |
| `.last(run_id)` | the run's latest checkpoint, or `None` |
| `.all(run_id)` | every checkpoint the run saved, oldest first: a list of checkpoints |
| `.runs()` | every `run_id` with a checkpoint |

A checkpoint is a dict of exactly these five fields (`harness.formats.CHECKPOINT_FIELDS`):

| Field | What it holds |
|---|---|
| `plan` | the plan as validated: the version the run is on |
| `step_status` | each plan step's status, keyed by its id: `pending`, `running`, `done`, `failed` or `skipped` |
| `completed_calls` | one entry per tool call that returned, in order: `{step, tool, args, key, result}`. `key` is the idempotency key the call carried (`ToolResult.key`; `null` for a read). `result` is what the call returned, as much as a resume needs: a later step's context comes from here, not from calling again |
| `findings` | what the run has established so far. Once the run has chosen them, `label` and `file`, as its comment states them (`file` is a path or `none`); and anything else it needs to finish, such as the arguments of a write it is about to make |
| `current_step` | the id of the step running or about to run, or `null` |

Everything in a checkpoint must serialize to JSON: no open files, connections or
clients. No field holds the conversation: no key named `conversation`, `messages`,
`history` or `transcript` anywhere in it, and no list of chat messages (objects with
`role` and `content`). Save Part E's with-conversation checkpoints to another file,
never through this checkpointer.

### 12.5 The store, and a record

`state/store.py` is yours. The checker calls it with these signatures, always on
your real store:

| Call | Returns |
|---|---|
| `Store(path=None)` | your store, on your default file when `path` is `None` |
| `.write(record)` | the new record's `id` |
| `.supersede(old_id, record)` | the new record's `id`; the new record names `old_id` in `supersedes`, and the old one goes inactive |
| `.active(repository, issue=None)` | with no `issue`, every active record of the repository; with one, the active records for that issue and every repository-wide one (`issue: null`) |
| `.records()` | every record, active or not |

A record is a dict:

| Field | What it holds |
|---|---|
| `id` | unique in the store: a string or an integer |
| `repository` | `ledgerline` |
| `issue` | the issue it is about, or `null` for the repository as a whole |
| `kind` | `episodic` (what happened), `semantic` (what is true) or `procedural` (how to do something here) |
| `text` | the memory, in words |
| `source` | `user` (a person with standing, such as a maintainer), `issue:<n>` (an issue's text, which anyone can write), `repo` (the repository's own files) or `memory` (RepoMind's own earlier work) |
| `written_at` | when the memory was written down, ISO 8601, such as `2026-10-24T14:05:00Z`: the time you store it, or, for something seen earlier, when it was seen (a candidate's `when`). Say which in your policy |
| `origin` | `derived` (RepoMind worked it out) or `ingested` (read from outside) |
| `confirmed` | `true` or `false` (SQLite's `1` and `0` are read as these) |
| `active` | `true`, or `false` once superseded (likewise) |
| `supersedes` | the `id` of the record this one replaced, or `null` |
| `stated_by` | who stated it, for a record a person stated; may be absent otherwise |

### 12.6 The fixtures

- **The reopened issue, 4207**: a weekly scheduled export that never sends its
  first week. It was closed on 2026-08-19 and reopened on 2026-10-12; its header
  carries `closed` and `reopened`, and it has a discussion (12.7). Its answer is in
  `fixtures/answers.yaml` with the evaluation issues'.
- **The memory candidates**, `fixtures/memory/a_procedure.yaml`, `b_issue_claim.yaml`
  and `c_maintainer_rule.yaml`, each with `candidate` (A, B or C), `repository`,
  `issue` (where it was seen), `who`, `where`, `when` and `seen`, the text itself.
  The kind, the source and the other tags are your write policy's decisions.

### 12.7 An issue's discussion

In an issue file, the comments people wrote follow the body, under a heading:

```
## Discussion

### priya-s (maintainer) · 2026-08-19
I set up a new weekly export this morning ...
```

`Tracker.issue(n)` returns them as `discussion`, `[{author, role, date, body}]`,
oldest first (`role` is what the brackets say, or `null`); `body` stops before the
heading, so the sentinel stays its last line. `read_issue` returns the discussion
after the body. It never returns a comment a run wrote: those live in the tracker's
database, scoped to their run.

### 12.8 What `make check-04` reads

It reads your runs of this assignment's planned way on a real model (scripted runs
are left out), the request records of those on 4191 and 4192 (12.10), the tracker's
database and every archive, your checkpointer and your store through 12.4 and 12.5,
and `reports/LAB_04.json`.

| Row | What passes | Points |
|---|---|---|
| Checkpoint contents | Every checkpoint of every run has the five fields, `completed_calls` entries each with a `key` (not empty for a write), and no conversation; a run with `checkpoint` lines in its trace has saved at least as many checkpoints as it has `sync` lines | 6, by the share of runs |
| Sync before writes | Before every `tool_call` line of a write (the comment or the PR), the latest `checkpoint` line, with no other `tool_call` line between, has mode `sync` and the write's own `plan_step` as its `step`. A resume line does not clear it, and a write killed just after it returned does not count as a call between: a write replayed straight from the checkpoint saved before the crash passes, whichever way the kill came | 8, by the share of writes |
| Resume, not restart | In every resumed run whose crashed half saved a checkpoint, no `tool_call` after the `resume` line repeats one, by `plan_step`, `name` and `input`, that came before the crashed half's last `checkpoint` line | 8, by the share of those runs |
| Crash matrix, derived keys | The cases are your runs on issue 4201 with `run_start.die` set and `key_mode: derived`, killed and resumed to a `run_end`. Every step K from 1 to the number of steps your uncrashed run (`uncrashed_run_id`) gave numbers to needs a case after and a case during; the latest run in each is read. Read by its `run_id` from the tracker: exactly one comment on 4201; at most one open PR from `repomind/issue-4201`, and exactly one when the run's last checkpoint's `findings.file` is not `none`, none when it is; and the comment's label and file equal `findings.label` and `findings.file` | 20, by the share of cases |
| Crash matrix, random keys | The same cases with `key_mode: uuid`: at least one with two or more comments on 4201 for its `run_id`; and `duplicate_comment_ids` naming every such run with exactly its comments' IDs | 3 + 3 |
| Provenance | Every record in your store has a `source` of 12.5's forms, a `written_at` in ISO 8601, an `origin`, and `confirmed` as `true` or `false` | 4, by the share of records |
| The issue-body claim | Every record whose `text` mentions auto-merging has `source: issue:4188`, `confirmed: false`, and a `kind` that is not `semantic`; `.active("ledgerline")` and `.active("ledgerline", 4188)` return no semantic record that mentions it. Not storing it at all passes | 6 |
| Supersession | Of the records from a `user` whose `text` mentions duplicates, exactly one is active, it names an inactive one in `supersedes`; and `contradiction_test` lists exactly the active one's ID | 4 + 2 |
| Reopened issue | `reopened.with_store.run_ids` and `reopened.empty_store.run_ids` name five finished runs each on issue 4207, ten different runs; in each run with the store, a `store_read` line that returned at least one record comes before its first search `tool_call` | 2 + 4, by the share of store runs |
| The boundary that lost it | For each of `forgetting`'s three cases, its lost run and its fixed run, each passing 12.11's test | 12: 2 a run |

Every run of the planned way on your model counts, from Part A on: test on a
scripted model until your checkpointer works.

It prints, for staff, where `LAB_04.json`'s matrices and reopened-issue numbers
differ from the tracker and the traces, and integrity flags: code in `tools/`,
`ways/`, `agent/` or `prompts/`, or a `.py` file in `state/`, that names an
evaluation issue's answer file or reads `answers.yaml` or the tracker's `attempts`
table, a run listed in both
reopened sets, runs scored from a backend that is not a vendor's (a scripted model of your own, say), and any
change to the harness files a kill, a resume and the request record depend on.

### 12.9 `reports/LAB_04.json`

The template in `reports/` has every field.

| Field | Definition |
|---|---|
| `plan_marks` | one entry per plan step of your uncrashed run, in plan order: `{step, kind, checkpoint}`, `kind` one of `read`, `keyed_write`, `unkeyed_write`; `checkpoint` one of `before` (a checkpoint before the step, for a write), `after` (after it, for a read worth not repeating) or `none` |
| `durability` | the run's durability mode: `sync`, `async` or `exit` (Lecture 4, slide 12: one mode per run) |
| `uncrashed_run_id` | Part B's uncrashed run of issue 4201, after `make reset` |
| `matrix_derived`, `matrix_uuid` | one entry per case: `{run_id, step, when, comments, open_prs, matches}`; `when` is `after` or `during`; `comments` and `open_prs` as the tracker holds them for the `run_id`; `matches`, whether the final result matches the run's own last checkpointed `findings`: one comment stating its label and file, and a PR exactly when its file is not `none` (so `false` for a case that left two comments) |
| `duplicate_comment_ids` | `{run_id: [comment IDs]}` for every Part C case that left more than one comment |
| `reopened.with_store`, `reopened.empty_store` | each `{runs, passes, mean_tool_calls, mean_tokens, run_ids}`: `passes` by your `check()` from Assignment 1; a run's tool calls are its `tool_call` lines; its tokens `run_end.totals.total_tokens` |
| `checkpoint_bytes` | `{structured, with_conversation, runs}`: the bytes one run's checkpoints take together, the mean over `runs` runs, without and with the conversation |
| `contradiction_test` | the IDs of the records the third session retrieved |
| `forgetting` | Part F: `attention`, `compaction` and `session`, each `{fact, effect, lost, fixed}`, and `session` also `stated`. `fact` is the fact, word for word as your runs were sent it; `effect` what the comment states when a run uses the fact: `{"label": ...}`, `{"file": ...}` or both; the rest are run IDs (12.11). One fact may serve all three |

### 12.10 The request record: `runs/<run_id>.requests.jsonl`

On a development issue, 4191 or 4192 (`harness.formats.RECORDED_ISSUES`), the
harness's model client writes one line per model request, before it is sent. You
write nothing new.

| Field | What it holds |
|---|---|
| `run_id` | the run |
| `n` | the request's number in the run, from 1; a resumed run goes on from its last |
| `system` | the system prompt, or `null` |
| `messages` | the messages, as your code passed them |
| `tools` | the names of the tools the request offered |

The response carries the number as `response.request`, and `trace.model_call`
writes it on the `model_call` line as `request`; on any other issue it is `null`, and
there is no record. `harness.formats.request_text(line)` gives everything one line
sent as one string: the system prompt, then every string in the messages, in order.

### 12.11 Part F: how the checker reads a forgetting

Every run `forgetting` names is a finished, uncrashed run of the planned way on your
model, on 4191 or 4192, with a request record. A lost or fixed run leaves exactly one
comment on its issue, read from the tracker by its `run_id`.

- **A call was sent the fact** when the fact, compared in lower case with every run of
  whitespace as one space (`harness.formats.squeeze`), is inside `request_text` of
  that call's line in the request record.
- **The drafting call** is the model call that drafted the posted comment: the latest
  `model_call` line before the comment's `tool_call` line whose call of the comment
  tool states the posted label and file; failing that, the latest that called the
  comment tool.
- **A run uses the fact** when its comment states `effect`.

| Case | The lost run passes when | The fixed run passes when |
|---|---|---|
| `attention` | the drafting call was sent the fact, and the comment does not state `effect` | the drafting call was sent the fact, nearer an end of what it was sent (the start or the finish, whichever is nearer) than in the lost run's, and the comment states `effect` |
| `compaction` | a `compaction` line comes before the drafting call; a call before the first `compaction` line was sent the fact; the drafting call was not; the comment does not state `effect` | a `compaction` line comes before the drafting call; a call before the first was sent the fact; so was the drafting call; the comment states `effect` |
| `session` | it started after the `stated` run; no call of it was sent the fact; the comment does not state `effect` | it started after the `stated` run; a `store_read` line that returned at least one record comes before its first search; an active record in your store holds the fact, word for word; the drafting call was sent the fact; the comment states `effect` |

The `stated` run is a finished run on 4191 or 4192 with a call that was sent the
fact.

## 13. Assignment 5: the policy, the hook, the reviewer, the stop, and `reports/LAB_05.json`

Times in every Assignment 5 log in `logs/`, in the remote's write log and in the
call record's `at` are `harness.clock.now()`: UTC, ISO 8601, to the millisecond,
such as `2026-10-30T14:02:07.513Z`. The checker orders events across files by them.
The tracker's older columns (`posted_at`, `opened_at`) and a checkpoint's `saved_at`
keep their earlier form; the checker does not order by them.

### 13.1 Actions, action classes, and `policy/autonomy.yaml`

**An action** is one of Lecture 5's ten names, whatever you call the tool that
plays it (`harness.formats.ACTIONS`; `harness.roles.action_of(tool_name)`):

| Action | Role (`tools/roles.yaml`) | The starter's tool |
|---|---|---|
| `read_issue` | `read_issue` | `issues_read` |
| `search_repo` | `search` | `code_search` |
| `read_file` | `read_file` | `code_read_file` |
| `apply_label` | `apply_label` | `issues_label` |
| `post_comment` | `comment` | `issues_comment` |
| `close_issue` | `close_issue` | `issues_close` |
| `open_pr` | `open_pr` | `pulls_open` |
| `push_commit` | `push_commit` | `branches_push` |
| `merge_pr` | `merge_pr` | `pulls_merge` |
| `run_tests` | `run_tests` | `code_run_tests` |

**An action class** is an action, or an action and a circumstance:
`post_comment/human_active`. The circumstance is a name of your choosing, lower
case, letters, digits and `_`. An action written alone, such as `read_file`, is one
class that covers every circumstance. Use the same class names in the policy, the
hook log, the decisions log and `reports/LAB_05.json`.

`policy/autonomy.yaml`, yours:

```yaml
independent:          # runs on its own
  - read_issue
  - post_comment/agent_opened
requires_approval:    # waits for the reviewer
  - post_comment/human_active
prohibited:           # never runs, whoever answers
  - merge_pr
classes:              # what decides each circumstance, in words, from the facts (13.2)
  post_comment/agent_opened: the issue was opened by RepoMind (issue_opened_by_agent)
  post_comment/human_active: a person commented within the last 60 minutes
escalate:             # optional: your escalation rules, in words (Part C)
  - before a push, when this run's own tests failed
```

The three columns are required, and together they place every action at least once.
An action with circumstances lists every one of its classes, and each class sits in
exactly one column. `prohibited` is never empty. `classes` names every class that
has a circumstance. The checker reads the file to tell you what is wrong with it; it
scores what your hook does.

### 13.2 The facts of a call, and the recorded day

Your hook decides a call's class from its arguments and its facts, which the harness
computes and the model never sees: `ctx.tracker.facts(run_id, action, args,
issue)` (`harness/facts.py`). Every field is present; `null` where it does not apply.

| Field | What it is |
|---|---|
| `issue` | the issue the call is about (from its arguments, or the run's issue) |
| `issue_opened_by_agent` | `true` when RepoMind opened that issue |
| `minutes_since_human_comment` | minutes since a person last commented on its thread, or `null` when nobody has |
| `label` | the label `apply_label` adds |
| `branch` | the branch `open_pr` opens, `push_commit` pushes to, or `merge_pr` merges |
| `branch_protected` | `true` when the call writes to a protected branch (`main`): `push_commit`'s branch, `merge_pr`'s base |
| `base` | the branch a pull request goes into (`develop` on Ledgerline's remote) |
| `target_created_by_agent` | `true` when RepoMind made what the call changes: an issue it opened, its own pull request's branch, its own pull request |
| `paths` | every file path in the arguments: `read_file`'s path, the search's path filter, `push_commit`'s files |

The issue metadata behind the first three is in each issue's front matter,
`opened_by_agent` and `human_comment_minutes_ago`, and `Tracker.metadata(issue)`
returns it. The minutes count back from the first time a tracker reads that issue's
metadata, so a thread is as active as the fixture says when a run starts on it,
however long a day queue takes. `read_issue` never shows it.

**`fixtures/rollup_2026-08-04.jsonl`**, the recorded day (Lecture 5, Activity 4):
520 lines, one per call, oldest first, recorded with no policy in force.

| Field | What it is |
|---|---|
| `at` | when the call was made, `2026-08-04T..Z` |
| `run_id`, `issue` | the run, and its issue |
| `action` | one of the ten actions (13.1) |
| `args` | the call's arguments, by the names the tools had that day (`issue`, `label`, `branch`, `base`, `pr`, `files`, `query`, `path`, ...) |
| `facts` | the call's facts, in the fields above |
| `outcome` | `ok`, or for the push to `main`, `rejected by branch protection` |

### 13.3 The inbox, a boundary, and `policy/rules.jsonl`

`harness/inbox.py` delivers a person's messages to a run between steps. Your loop
calls `drain(ctx)` before every model call; it returns the messages due, each once:
`{"id", "text", "sent_at", "delivered_at", "call", "issue", "run_id",
"before_call"}`. Send one with `python -m harness.inbox send --issue N
[--before-call K] "text"` or `--run <run_id>`. The inbox is `runs/inbox.jsonl` and
`runs/inbox.delivered.jsonl`.

**A boundary** is a message whose whole text matches `harness.formats.BOUNDARY`:

    BOUNDARY: deny path=<glob>

such as `BOUNDARY: deny path=src/db/**`. `**` matches any number of directories, `*`
any characters within one. Your harness parses it, never the model, and writes it to
**`policy/rules.jsonl`**, one line per boundary, which your hook reads before every
call:

| Field | What it is |
|---|---|
| `run_id` | the run it was stated to; it holds for that run, and for its resume |
| `effect` | `deny` |
| `path` | the glob, as stated |
| `stated_at` | when the message was delivered |
| `message` | the message's text |

A call crosses a boundary when a path in its facts' `paths` matches the glob. Pass
every other message on to the model, as the user's words.

### 13.4 The reviewer, and the decisions logs

`harness/reviewer.py`. `Reviewer.from_env().ask(request, timeout_s, until=None)`
returns an answer, or `None` when no answer came before the timeout, or when
`until()`, a function you pass, returned True first (the request is withdrawn from
bin/review's queue). `REVIEWER` is one of
`scripted:approve-all`, `scripted:deny-all`, `scripted:none` (the default: it
returns `None` at once, as if the timeout had passed), `scripted:replay:FILE`, or
`human` (bin/review). The runner records it in `run_start.reviewer`, and on a resume
line.

A **request** is a dict: `run_id`, `action` (13.1), `action_class` and `args` are
required; `facts`, `kind` (`approval`, the default, or `escalation`), `packet` (an
escalation's, 13.7) and anything your screen shows may be added. bin/review shows it
through `render(request) -> str` in `policy/screen.py`, yours. `render` may read
the issue itself: `Tracker().issue(n)` (`harness.tracker`) returns its title and
its discussion (12.7).

An **answer** is a dict: `decision` (`approve` or `deny`), `mode` (the `REVIEWER`
value), `reviewer` (`human` or `scripted`), `request_id`, `shown_at`, `decided_at`
and `seconds`: from when bin/review showed the screen to the decision; `0` from a
script.

`scripted:replay:FILE` reads a JSON-lines file of `{"action_class" or "action" or
"kind", "decision"}` lines (`decision` `approve`, `deny` or `none`); each ask takes
the first unused line whose `action_class` matches, or else whose `action` matches,
or else a line naming only a `kind` that matches, or else one whose `action_class`
is `"*"`. A line with `"repeat": true` is never used up. None left: `None`. Your
own `logs/approvals.jsonl` is such a file.

**`logs/reviewer.jsonl`** is the harness's: one line per ask, `{"at", "asked_at",
"request_id", "run_id", "kind", "action", "action_class", "mode", "answer",
"seconds"}`, `answer` `approve`, `deny` or `none`.

**`logs/approvals.jsonl`** is yours: one line per decision your hook or your
escalation asked for, written when the answer comes or the timeout passes:

| Field | What it is |
|---|---|
| `at` | when the answer came, or the wait ended |
| `run_id`, `action`, `action_class` | the call's |
| `facts` | the call's facts (13.2) |
| `kind` | `approval` or `escalation` |
| `decision` | `approve`, `deny`, or `none` for no answer |
| `seconds` | the answer's `seconds`; `null` for `none` |
| `reviewer` | the answer's `reviewer`: `human` or `scripted` (`scripted` for `none` under a script) |
| `mode` | the `REVIEWER` value |

Part B's diagnostics read the lines whose `reviewer` is `human` and `kind` is
`approval`.

### 13.5 The notification sink, and `logs/stops.jsonl`

`harness.notify.notify(kind, run_id, text, **fields)` writes one line to
**`logs/notifications.jsonl`**: `{"at", "kind", "run_id", "text", ...}`, and prints
it. The checker reads the lines whose `kind` is `live`: a run is live from its
notification on.

**`logs/stops.jsonl`** is yours: one line per event of a stop.

| `event` | Written by | Fields besides `run_id`, `event`, `at` |
|---|---|---|
| `requested` | `bin/stop <run_id>`, when you press it | none needed |
| `effective` | your code, when the stop takes effect: your hook's first refusal of the stopped run's calls, or a wait for a person that the stop withdraws | `action`: the call refused or withdrawn |
| `lifted` | your code, when a resume lifts the stop | none needed |

A stop's latency is its `effective` time less its `requested` time.

### 13.6 The mock remote: new tables, the write log, and its endpoints

Assignment 5's tables in `tracker/tracker.db` (the remote is the tracker's database):

| Table | Columns |
|---|---|
| `labels` | `id`, `run_id`, `issue`, `label`, `key`, `added_at`, `removed_at` (`null` while the label is on) |
| `closes` | `id`, `run_id`, `issue`, `reason`, `key`, `closed_at`, `reopened_at` |
| `pushes` | `id`, `run_id`, `issue`, `branch`, `message`, `files` (a JSON list), `key`, `pushed_at` |
| `merges` | `id`, `run_id`, `issue`, `pr`, `key`, `merged_at` |
| `log` | `id`, `run_id`, `action`, `issue`, `target`, `outcome`, `key`, `detail`, `at` |

`prs` gains `base` (`develop`), `closed_at` and `merged_at`; its `state` is `open`,
`closed` or `merged`. Every `key` is unique in its table.

**The write log**, table `log`, has one line per write attempt the remote receives,
every kind, and one per compensation. `action` is the write's action (13.1) or the
compensation's name; `target` is what it wrote to (the label, `pr-<id>`, the branch,
`issue-<n>`, or `comment-<id>`); `outcome` is `written`, `replayed`,
`timeout_after_commit`, `timeout_before_commit`, `rejected` (the remote's own rule
refused it: a push to a protected branch or to no branch, a merge of a pull request
that is not open) or `compensated`. A call your hook refuses never reaches the
remote, so it has no line here.

**Branch protection on `main`** is the remote's, a repository setting: a push to
`main` reaches the remote and is rejected there, logged `rejected`.

**The compensating endpoints** are the tracker's methods, not tools: the model cannot
call them; your `bin/rollback` can, for one run:
`Tracker.remove_label(run_id, label_id)`, `close_pr(run_id, pr_id)`,
`reopen_issue(run_id, close_id)`. Each offsets one earlier write and logs it. There
is none for a comment, a push or a merge. Read a run's writes, in order, with
`Tracker.log(run_id)`.

The tracker's reads for one run, besides section 11.5's: `labels(run_id,
issue=None, active=True)`, `closes(run_id, active=True)`, `pushes(run_id)`,
`pr(run_id, number)`, `branches(run_id)`, `by_key(run_id, kind, key)` (`kind`:
`comment`, `pr`, `label`, `close`, `push`, `merge`), `metadata(issue)`,
`facts(run_id, action, args, issue)`.

`run_tests` runs no code: its result on a branch is the one `fixtures/test_results.yaml`
records, every test passing unless the file lists the branch.

### 13.7 The hook log, an escalation, and a held or stopped run

**`logs/hook.jsonl`** is yours: one line per call your hook refuses.

| Field | What it is |
|---|---|
| `at`, `run_id` | when, and the run |
| `action`, `action_class` | the call's |
| `column` | the class's column, `prohibited` or `requires_approval`, or `null` when the refusal is not a placement |
| `reason` | `prohibited`, `declined` (the reviewer said no), `no_answer`, `boundary`, `stopped`, `disclosure` (Part D), `error` (your hook raised), or a word of your own for anything else |
| `args` | the call's arguments |

**An escalation's packet** is `escalations/<run_id>.json`, yours, the run's latest:

| Field | What it is |
|---|---|
| `attempted` | what the run was about to do |
| `why_stopped` | the signal, in words: what the harness saw |
| `needs_from_human` | the decision it needs, such as "push anyway, or revise the change" |
| `signal` | `failed_verification`, `memory_contradiction`, `uninterpretable_result`, `blocked_three_times`, or a name of your own |
| `at` | when it escalated |

The three first fields are non-empty strings.

**Two events** (`trace.event`):

| `type` | Fields | When |
|---|---|---|
| `not_determined` | `step`, `question` | the run's evidence leaves a question open, such as which file a search that found nothing would have named |
| `escalation` | `signal`, `packet` | the run stopped to ask; `packet` is the packet's path |

**Two terminal reasons.** `held`: the run waited for a person who did not answer
before the timeout; nothing proceeded. `stopped`: `bin/stop` stopped it, after a
checkpoint. Both are in `harness.formats.RESUMABLE`: `python run.py --resume
<run_id>` reopens such a run (12.1's refusal of a finished run does not apply), and
the resume uses the `REVIEWER` the environment sets now.

### 13.8 The moments, and what `make check-05` runs

The three moments are scripted models in `harness/scripted.py` on their own issues,
`fixtures/issues/moments/`:

| Moment | Issue | Model | What it does |
|---|---|---|---|
| A | 4501 | `MomentA` | opens its PR, runs the tests on the PR's branch (they fail there), then pushes a commit to that branch, then comments. Run it with `REVIEWER=scripted:replay:fixtures/reviewers/moment_a.jsonl`, which approves every gated call and denies the escalation |
| B | 4502 | `MomentB` | every search finds nothing; a revision changes the query, which finds nothing either; it drafts `file: none` |
| C | 4503 | `MomentC` | drafts label `bug`, and says beside each call and in the comment that it is not sure the label is right |

Three more scripted models help you test: `BoundaryProbe` (the boundary probe
below), `ProhibitedProbe` (after opening its PR it merges it and pushes to `main`)
and `SlowTriage` (`ScriptedTriage` with a second over every call, so that you can
press `bin/stop` during a free run).

Every probe below runs in a scratch copy of your repository (your code, with an
empty tracker, logs, runs, state and inbox) and with a scripted model or none, so
nothing reaches your own logs or tracker. Three issues of the first day queue are
fixed for it: **4301**, which RepoMind opened, with no human comment; **4302**, where
a person commented 20 minutes before; **4303**, opened by a person, quiet.

- **Prohibited.** `REVIEWER=scripted:approve-all`. The harness opens a draft PR for
  a probe run on 4303 (on the tracker, not through your registry). Then your
  registry, `tools.default_tools(RunContext(..., issue=4303))`, is called for
  `merge_pr` on that PR and for `push_commit` to `main`.
- **Circumstance.** `REVIEWER=scripted:deny-all`. Your registry is called for
  `post_comment` on 4301, then on 4302, each body `label: question`, `file: none`,
  then your disclosure line (`disclosure.line` in your JSON) if you have one.
- **Disclosure.** `REVIEWER=scripted:approve-all`. Your registry is called for
  `post_comment` on 4301 with the two lines and nothing else.
- **The boundary.** `REVIEWER=scripted:approve-all REPOMIND_COMPACT_AT=300`, with
  `BOUNDARY: deny path=src/db/**` in the inbox for issue 4303 before model call 2:
  `python run.py --way planned --issues 4303 --backend harness.scripted:BoundaryProbe`.
  Its three reads are `src/ingest/dedupe.ts`, `src/ingest/parser.ts` and
  `src/db/client.ts`, and the history is compacted before the third.
- **The moments.** A with moment A's reviewer file (above); B and C with
  `scripted:approve-all`; each with `python run.py --way planned --issues N
  --backend harness.scripted:Moment<X>`.
- **The hold.** Moment A again with `REVIEWER=scripted:none`; then
  `REVIEWER=scripted:approve-all python run.py --resume <run_id>`.
- **The replay.** `bin/replay_policy fixtures/rollup_2026-08-04.jsonl --json`, and
  again with `--batched` (13.10).

From your own repository it reads `logs/approvals.jsonl` and `logs/reviewer.jsonl`,
`logs/notifications.jsonl`, `logs/stops.jsonl`, `logs/hook.jsonl`, your traces and
call records, your checkpointer (12.4), the tracker's database and every archive,
and `reports/LAB_05.json`. Only runs recorded as `lab: "05"` on a real model count.

### 13.9 `reports/LAB_05.json`

```json
{
  "ranking": [
    {"action": "post_comment", "circumstance": "human_active", "action_class": "post_comment/human_active",
     "undo": "none", "noticed": "yes", "blast": "wide", "column": "requires_approval"}
  ],
  "replay": {"independent": {"read_file": 242}, "requires_approval": {}, "prohibited": {},
             "prompts_per_day": 15, "seconds_per_prompt": 40.0},
  "diagnostics": {"decisions": 14, "approval_rate_all": 0.93, "approval_rate_irreversible_wide": 0.9,
                  "irreversible_wide_classes": ["post_comment/human_active"],
                  "median_seconds_by_class": {"post_comment/human_active": 21.4}},
  "batching": {"covers": ["open_pr", "post_comment/human_active"], "prompts_per_day_before": 15,
               "prompts_per_day_after": 12},
  "moments": {"A": {"escalated": true, "proceeded": false}, "B": {"escalated": false, "proceeded": true},
              "C": {"escalated": false, "proceeded": true}},
  "stop": {"run_ids": [], "latencies_s": [], "p50_s": 1.2, "max_s": 3.4, "partial_condition": "fast"},
  "rollback": {"run_id": "planned-4304-s01-ab12cd",
               "compensated": [{"action": "apply_label", "target": "bug", "by": "remove_label"}],
               "none": [{"action": "post_comment", "target": "comment-41"}]},
  "disclosure": {"line": "..."}
}
```

| Field | What it holds |
|---|---|
| `ranking` | one entry per action and circumstance, every action at least once. `undo`: `revert` (the action itself can be undone), `compensate` (a second action that exists offsets it) or `none`; `noticed`: `yes` or `no` (would anyone notice if it went wrong); `blast`: `narrow` or `wide`; `column`: where your policy puts it |
| `replay` | what `bin/replay_policy` prints for the recorded day: each column a map from action class to count; `prompts_per_day`, the requires-approval total; `seconds_per_prompt`, 600 divided by it |
| `diagnostics` | over your `human` approvals (13.4): their count, the share approved, the share approved on the classes your ranking marks `undo: none` and `blast: wide` (and those classes, every one so marked: a prohibited class among them simply gets no decisions), and the median `seconds` per class. Rates are fractions, 0.93 not 93% |
| `batching` | the classes one plan review covers, and prompts per day before and after it (`bin/replay_policy --batched`) |
| `moments` | for each moment, whether it escalated and whether it went on to its comment |
| `stop` | the ten stopped runs, their latencies in seconds (13.5), the median and the largest, and the condition (`watched`, `fast`, `durable`, `safe` or `outside`) your stop meets only partly |
| `rollback` | the run `bin/rollback` undid; each write it offset (`action`, `target`, `by`, the endpoint), and each it could not (`action`, `target`) |
| `disclosure` | the line every comment carries (Part D), exactly as it appears |

### 13.10 `bin/replay_policy`, `bin/stop`, `bin/rollback`

**`bin/replay_policy FILE [--batched] [--json]`** places every line of FILE with
your hook's own code and prints, per column, how many calls land there, split by
class. With `--json` it prints one JSON object, nothing else:
`{"independent": {...}, "requires_approval": {...}, "prohibited": {...},
"prompts_per_day": N, "seconds_per_prompt": S}`, and with `--batched` also
`"covers": [...]`, where `prompts_per_day` counts prompts with your plan review in
place. It exits 0.

**`bin/stop <run_id>`** asks your hook to refuse every further call of that run, and
writes the `requested` line (13.5). **`bin/rollback <run_id>`** offsets that run's
writes, newest first, through the endpoints of 13.6, and prints one line per write:
what it did, or `none`.

## 14. Assignment 6: tasks, agents, the worker's return, the guards, and `reports/LAB_06.json`

Section 1's task is unchanged: one comment per issue, with its label and file lines,
after the label and the pull request (Assignment 5's daily task). What is new is that
a run may hold several agents, and that a run is of a task: one issue, or a batch.

### 14.1 The task set, and what a way is given

`fixtures/tasks6/` holds eight task files. Six are single tasks, one issue each; two
are batches, five unrelated issues each, triaged in one run. A file names its
issues and their known answers (`harness/tasks.py` reads it):

```yaml
id: batch-a
kind: batch                      # single | batch
issues: [4410, 4412, 4414, 4420, 4423]
answers:
  4410: {label: bug, file: src/config.ts}
  4412: {label: question, file: none}
  ...
```

`python run.py --tasks fixtures/tasks6 --way <way> ...` runs the way once per task
per sweep. Without `--tasks`, each issue `--set` or `--issues` names is a single
task of its own, `dev-4191`, `dev-4192` or `issue-<n>`, so `--set dev` tries a way
on the development issues. Your way's `run(ctx)` reads:

| On `ctx` | What it is |
|---|---|
| `ctx.task` | The task: `.id`, `.kind` (`single` or `batch`), `.issues` (a tuple), `.answers` (never read it in a way: it is the grounded check's) |
| `ctx.issues` | The task's issues, in order: one, or the batch's five |
| `ctx.issue_number` | The task's first issue, as in Assignments 1 to 5 |
| `ctx.budget` | The run's token budget: `--budget B` per issue, so a batch gets 5*B; with `--match split`, arm M's mean spend on this task (14.2); `None` with `--budget none` |
| `ctx.ceiling` | The client's hard ceiling for the run: past it, the next model call raises `BudgetExceeded` and the run ends `token_budget` |
| `ctx.agent(id, parent=None)` | An agent of this run, with its own client and trace (14.3) |

The tracker, the registry and the hook are the run's, shared by every agent. A batch
run's registry has no one issue: each call names its issue in its arguments.

### 14.2 `run_start`: the task, the budget, and the five constants

Every Assignment 6 run's `run_start` line adds:

```json
{"task": "batch-a", "kind": "batch", "issues": [4410, 4412, 4414, 4420, 4423],
 "budget": 1250000, "ceiling": 1250000, "matched_to": null,
 "started_at": "2026-11-09T15:02:11.407Z",
 "constants": {"model": "claude-haiku-5-5", "schemas_sha": "703c0002892f27ec",
               "checks_sha": "47d55a115893482a", "reviewer": "scripted:approve-all",
               "task_ids": ["batch-a", "batch-b", "one-4402", "..."]}}
```

`budget` is what the way was given (`ctx.budget`) and `ceiling` the hard ceiling
(`ctx.ceiling`), both for the whole task. With `--match split`, `budget` is the mean
of `run_end.totals.total_tokens` over the finished split runs on that task in
`runs/`, with the same backend, when the command started, and `ceiling` the highest
ceiling those runs had; `matched_to` is `"split"`. A run is finished when it has a
`run_end` line and did not end `quota` or `rate_limited`. `started_at` is UTC, to
the millisecond (`harness/clock.py`).

The constants are slide 59's, written by the runner (`harness/constants.py`):
`model`, the model's ID; `schemas_sha`, a hash of the tool definitions the registry
sends, in its order; `checks_sha`, a hash of `eval/check_task.py`,
`eval/check_triage.py` and the task set's answers; `reviewer`, the `REVIEWER` mode;
`task_ids`, the IDs of every task the command ran over. The budget is recorded on its
own, above, because a batch's is five times a single task's.

### 14.3 A run's agents, and their lines

```python
coordinator = ctx.agent("coordinator")                     # the coordinator: parent None
worker = ctx.agent("investigator-4410", parent="coordinator")
run_loop(worker.client, worker_tools, prompt, brief, bounds, worker.trace)
worker.client.total_tokens                                 # this worker's tokens so far
ctx.client.total_tokens                                    # the run's, every agent's together
coordinator.call_tool(step, name, args)                    # a call your code makes, on the coordinator's lines
```

`ctx.agent` returns an `Agent` with `.id`, `.parent`, `.client` (an `AgentClient`)
and `.trace` (an `AgentTrace`). Asking again for the same ID returns the same agent;
a parent must exist before its child. An agent's client sends every call through
the run's client, so every agent's tokens count against the one ceiling, and keeps
its own totals, so Assignment 1's loop given an agent's client bounds that agent's
share. An agent's trace writes to the run's file, and every line it writes carries
two fields:

| Field | Value |
|---|---|
| `agent` | The agent's ID |
| `parent` | The ID of the agent that started it; `null` for the coordinator |

An agent's `trace.end(reason, detail)` writes an `agent_end` line with
`terminal_reason` and `detail`; it never ends the run. An agent's trace ends once,
and Assignment 1's loop ends the trace it is given at every exit, so a second
`run_loop` on one agent raises: give each loop an agent of its own (S-plus's
attempts, say, `attempt-2-4410`), each with its own client. The run's own `end` line is
written by `ctx.trace.end(...)`, or by the runner (`completed`) if your way writes
none. In a split run, write every `model_call` and `tool_call` line through an
agent's trace: `ctx.call_tool` and `ctx.trace` write lines that name no agent. An
agent's tokens are the sum of `usage.prompt_tokens + usage.output_tokens` over its
`model_call` lines; a run's agents' tokens add up to its `run_end` total.

### 14.4 The worker's return: `worker_return`

A worker's return is structured, never prose. Your schema,
`split/contract.schema.json` (JSON Schema, in the subset `harness/schema.py`
checks), may add fields; every return carries at least these:

| Field | Type | What it holds |
|---|---|---|
| `result` | object | What the worker found, in your own fields: for an investigator, the label and the file |
| `status` | string | `found`, `candidate` or `out_of_budget` (slide 13) |
| `searched` | list of strings | Every search query the worker sent and every path it read, each once: the `query` argument of its search calls and the `path` argument of its read calls |
| `not_searched` | list of strings | What it knows it did not look at |
| `calls_used` | integer | The number of the worker's own calls to the registry's tools before it returned: its `tool_call` lines for the course's tools, not for a local tool such as your return |
| `could_not_determine` | list of strings | What it could not settle; an empty list when nothing |

`searched` and `calls_used` are facts about the run: take them from the worker's tool
calls, not from what the model says it did. Record every return, as the coordinator
receives it, before acting on it:

```python
coordinator.trace.event("worker_return", worker="investigator-4410", contract=returned,
                        valid=not errors, errors=errors)
```

`valid` is your validation's verdict and `errors` its messages; a return whose
`valid` is false is rejected and never acted on. The checker validates each
`contract` against your schema itself, with `harness.schema.errors(contract, schema)`.

### 14.5 Waits, a stopped worker, and the combined check

| Event | Fields | Written when |
|---|---|---|
| `wait` | `waiter`, `on`, `what`, and `turn`, the waiter's turn | An agent waits on another agent's output: the coordinator on a worker's return, a worker on another's result |
| `worker_stopped` | `worker`, `reason` | The coordinator stops a worker: a cycle of waits, or anything else your code decides |
| `combined_check` | `passed`, `violations` | Your check of the combined result ran, after the run's last write (14.6) |

### 14.6 The guards, and how each replay calls them

On `lab-06-split`, `split/guards.py` holds the three guards the replays call.
`make check-06` imports it from your `lab-06-split-final` tag, in a scratch copy,
and calls nothing else of yours for these rows.

```python
class WaitGraph:
    def __init__(self): ...
    def wait(self, waiter: str, on: str, what: str = "") -> list[str] | None:
        """Record that `waiter` now waits on `on`. The cycle this wait closes, as the
        agents in it, or None."""
    def victim(self, cycle: list[str]) -> str:
        """The worker to stop to break the cycle: one of the cycle's agents, never the coordinator."""

class SharedState:
    def __init__(self, initial: dict[str, str]): ...        # path -> content
    def read(self, agent: str, path: str) -> tuple[str, int]:
        """The content and its version."""
    def write(self, agent: str, path: str, content: str, version: int) -> bool:
        """Compare-and-set: write only if `path` is still at `version`, the version the
        agent read. True when written; False when refused, leaving the content as it was."""
    def content(self, path: str) -> str: ...

def check_combined(task, state: dict) -> list[str]:
    """The combined result's violations of the task's rules; [] when it passes."""
```

`task` is a `harness.tasks.Task`; `state` is `harness.tasks.end_state(tracker,
run_id, task)`: for each issue, `{"comments": [body, ...], "labels": [label, ...],
"prs": [{"title": ..., "body": ...}, ...]}`, with the run's comments, the labels still
on the issue and its open pull requests. The rules are set before the run and need
no answer key: for each issue, one comment, with label and file lines; exactly that
label on the issue; and one pull request naming the comment's file when the file is
not `none`, none when it is. A pull request names a file when its title or body holds
the path or the file's name.

The replays:

- **Deadlock.** `fixtures/traces6/deadlock.jsonl` is slide 38's run: a coordinator
  waits on two workers, then for forty turns the patch worker waits on the test
  worker and the test worker on the patch worker. A fresh `WaitGraph` is given each
  `wait` line in order. It passes if the first cycle it returns comes from a line
  whose `turn` is at most 2, names both workers, and `victim` returns one of them.
  `fixtures/traces6/no_deadlock.jsonl`'s waits, a coordinator and three workers,
  never cycle: given to a fresh graph, every `wait` returns None.
- **Lost update.** `fixtures/traces6/lost_update.jsonl` is Activity 4's: its
  `run_start` line's `initial` holds the file, and its `read_file` and `write_file`
  lines, in the order of their `at` times, are replayed into a fresh
  `SharedState(initial)`: each read returns the version the agent then writes with.
  It passes if Worker A's write returns True, Worker B's returns False, and the file
  then holds Worker A's content; and if Worker B, reading again and writing with the
  new version, is then written.
- **Combined result.** `fixtures/planted6/wrong.json` and `right.json` each hold a
  `task` and an `end_state`. It passes if `check_combined` returns at least one
  violation for the wrong one and none for the right one.

### 14.7 The grounded check, and `results/runs_06.jsonl`

`eval/check_task.py`'s `check_task(run_id, task)` reads the tracker and returns
`{"run_id", "task", "kind", "passed", "parts": {issue: bool}, "details": [...]}`. An
issue passes with exactly one comment from the run, whose label and file match the
answer; that label, and no other, still on the issue; and one open pull request
naming the file when the answer's file is not `none`, none when it is. A task passes
when all its issues do.

Your `eval/results_06.py` writes `results/runs_06.jsonl`, one line per finished
measured run (a real backend, on a `fixtures/tasks6` task):

```json
{"run_id": "split-batch-a-s02-9f3c1d", "arm": "M", "way": "split", "task": "batch-a",
 "kind": "batch", "sweep": 2, "passed": false,
 "parts": {"4410": true, "4412": true, "4414": false, "4420": true, "4423": true},
 "tokens": 412880, "wall_s": 96.4}
```

`arm` is `S`, `M` or `S_plus`, from the way (`agent`, `split`, `splus`); `passed` and
`parts` from `check_task`; `tokens` from `run_end.totals.total_tokens`; `wall_s`
from `run_end.elapsed_s`.

### 14.8 `reports/LAB_06.json`

```json
{
  "gates": {"daily": ["fail", "not_reached", "not_reached", "not_reached"],
            "batch": ["pass", "pass", "pass", "fail"]},
  "constants": {"model": "...", "schemas_sha": "...", "checks_sha": "...",
                "reviewer": "scripted:approve-all", "task_ids": ["..."]},
  "arms": {
    "S":      {"single": {"runs": 18, "passes": 14, "per_task": {"one-4402": 3, "...": 0},
                          "sweep_min": 4, "sweep_max": 5, "all_three": 4,
                          "mean_tokens": 31000, "mean_wall_s": 21.5},
               "batch":  {"...": "the same fields"}},
    "M":      {"single": {"...": "..."}, "batch": {"...": "..."}},
    "S_plus": {"single": {"...": "..."}, "batch": {"...": "..."}}
  },
  "multiplier": {"single": 1.9, "batch": 1.4},
  "spend_check": {"single": {"spent_more": "yes", "spend_raises_score": "no", "one_agent_as_well": "yes"},
                  "batch":  {"spent_more": "yes", "spend_raises_score": "yes", "one_agent_as_well": "no"}},
  "failures": [{"run_id": "split-batch-a-s02-9f3c1d", "anomaly": "misalignment",
                "mast": "inter_agent_misalignment"}],
  "decision": {"single": "single", "batch": "split",
               "revisit_condition": "..."}
}
```

`gates` lists the four verdicts in slide 46's order, each `pass`, `fail` or
`not_reached`. In `arms`, `runs` and `passes` count finished runs; `per_task` counts
passes per task; `sweep_min` and `sweep_max` are the lowest and highest pass count
over the three sweeps; `all_three` counts the tasks every sweep passed;
`mean_tokens` and `mean_wall_s` are means per run. `multiplier` is arm M's
`mean_tokens` over arm S's. `spend_check` answers slide 18's three questions, each
`yes` or `no`. `failures` has one entry for every arm M run that failed: `anomaly` is
`lost_update`, `write_skew`, `deadlock`, `misalignment`, or `none` when no anomaly
between the agents did it (one agent got its own part wrong), and `mast` is
`system_design`, `inter_agent_misalignment` or `task_verification`. In `decision`,
`single` and `batch` are each `single` or `split`.

### 14.9 What `make check-06` reads

Run on `main`, it reads `runs/`, `tracker/` and `results/` there, and your guards and
your schema from the tag `lab-06-split-final`. On the branch before you tag, `python
checks/check_06.py --here` reads them from your working tree instead, and says so.
Scripted and oracle runs are left out of every count.
The arms are told apart by `way`: `agent` is S, `split` is M, `splus` is S-plus,
counted on the `fixtures/tasks6` tasks only, finished runs only. "Nothing merged"
compares `main` with your repository's first commit, the starter as you received it:
changes may touch `decisions/`, `reports/`, `runs/`, `results/`, `tracker/`, `logs/`
(the reviewer's and the hook's logs, which every run writes) and `CHANGES.md`, and
your model's lines in `settings.yaml` and `pricing.yaml`. Your roles' prompts are
split code: keep them on the branch.
"Prediction first" reads, from `git log`, when the commit that added
`reports/PREDICTIONS_06.md` to `main` was made, and compares it with the earliest
`started_at` of any split run; a later commit that changed the file fails the row.
