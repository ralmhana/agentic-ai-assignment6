# RepoMind

The course's running system, built one layer at a time. RepoMind triages issues
for **Ledgerline**, a small reporting and export service: it reads an issue,
searches Ledgerline's private codebase, applies a label, opens a draft pull request
for the file it names, and posts a triage comment where the issue's author can read
it.

That combination is deliberate. RepoMind reads text anyone can write, reaches
code nobody outside the team should see, and writes somewhere public. Lecture 1
calls it the lethal trifecta. You build it this way on purpose, and Lecture 8 is
when you close it.

## Start here

You have two things: this repository, and the assignment handout from your
instructor. The handout says what to build and how it is graded; this file says
how the repository works. For Assignment 6, read the handout's "Getting started"
first.

This repository holds Assignment 5's working solution in place of your own code:
the planned way, the autonomy policy in the registry's hook, the reviewer, the stop
and rollback, and the disclosure line. Assignment 6 asks whether RepoMind should be
several agents, so the single agent you compare against is the agent way, one loop
holding every tool (`ways/agent.py`), updated to Assignment 5's daily task and to a
batch of five issues in one run. There is no sub-agent code here: you build the
split yourself, on the `lab-06-split` branch. A fresh copy runs, and `make
check-06` awards it nothing. That is expected.

### What you need

- Python 3.10 or later, `git` and `make`. Python's built-in `sqlite3` is all the
  database this assignment needs.
- The model and API key you used before, or any model with tool calling. Never
  commit the key and never share it.

### Set up, and use your model

```bash
make setup                     # creates .venv and installs the three dependencies
source .venv/bin/activate      # in every new terminal
make test                      # the harness's own tests; they spend no tokens
```

From your earlier repository, copy the `provider`, `model`, `base_url` and
`api_key_env` lines of `settings.yaml` into this one, and your model's line in
`pricing.yaml`, if this sheet does not have it. Change nothing else in
`settings.yaml`. Two backends cover almost every vendor:

| Your model | In `settings.yaml` |
|---|---|
| Claude, through Anthropic's API | `provider: anthropic`, `model`; the key in `ANTHROPIC_API_KEY` |
| Anything with an OpenAI-compatible API: OpenAI, Google Gemini, Mistral, DeepSeek, Groq, OpenRouter, a local Ollama or vLLM server, and many more | `provider: openai-compatible`, `model`, `base_url` (none for OpenAI itself), and `api_key_env`, the variable that holds your key (default `OPENAI_API_KEY`) |

Then check it:

```bash
export OPENAI_API_KEY=...      # or the variable your api_key_env names
make ping                      # your key, your model, tool calling, its price line, and your tool definitions
export REVIEWER=scripted:approve-all   # every run in this assignment
```

`make test` and `make ping` must both pass before you write any code.

### Where to start: Assignment 6

| Order | What you write | How you test it | Costs |
|---|---|---|---|
| Part A, on `main` | `reports/PREDICTIONS_06.md`, committed and pushed on its own, and section A of the report | Nothing to run | Nothing |
| Part B, on `lab-06-split` | `ways/split.py`, your roles, `split/contract.schema.json`, `split/guards.py` | `python checks/check_06.py --here` replays the recorded runs into your guards, free; `ScriptedWorkers`, free; a few runs on the development issues | A few runs |
| Part C, on `lab-06-split` | `eval/results_06.py`, `ways/splus.py`; then the three arms | `ScriptedWorkers` first, free | 72 runs |
| Part D, on `main` | `decisions/0006-topology.md`, `CHANGES.md` | Nothing to run | Nothing |

`make check-06` works at any point and shows what is still missing; it is the same
checker staff run. On `lab-06-split`, run `python checks/check_06.py --here` to
check the guards in your working tree before you tag.

## What is here, and what is yours

| Path | What it is | Yours to edit? |
|---|---|---|
| `ways/agent.py`, `prompts/agent.md`, `agent/loop.py`, `agent/bounds.yaml` | **Arm S**, the single agent: Assignment 1's loop holding every tool, on one issue or a batch, the disclosure line added in code (`with_disclosure`). Its token budget is the run's (`ctx.budget`); its steps and wall-clock scale with the number of issues | **No**, on either branch: it is the arm you compare against |
| `ways/planned.py`, `agent/`, `state/`, `policy/`, `bin/`, `tools/` | Assignment 5's working solution. Every call any agent makes goes through the registry and `policy/hook.py` | Not on `main` |
| `fixtures/tasks6/` | The eight tasks: six single issues and two batches of five, each with its known answers | **Never** |
| `fixtures/traces6/`, `fixtures/planted6/` | The recorded deadlock, a set of waits with no cycle, the recorded lost update, and a batch's two end states, wrong and right: what the guard replays feed your guards | **Never** |
| `eval/check_task.py` | The grounded check of one run on one task, from the tracker | No: call it |
| `run.py`, `harness/` | New for Assignment 6: tasks and batches (`harness/tasks.py`), the token budget per issue and `--match` (`harness/runner.py`), the five constants in every `run_start` line (`harness/constants.py`), and a client and a trace per agent (`ctx.agent`) | No |
| `checks/` | `check_06.py`, the Assignment 6 checker, and `FORMATS.md`, which defines every format it reads (section 14 is new) | No |
| `tests/` | The harness's own tests | No |
| `settings.yaml`, `pricing.yaml` | Your model, the ceilings, the dated price sheet | Once, in setup: your model and its price line; never the ceilings |
| `reports/`, `decisions/`, `CHANGES.md` | Your write-ups, on `main`; `reports/` starts with the templates for `LAB_06.md` and `LAB_06.json` | **Yes** |
| `ways/split.py`, `ways/splus.py`, `split/`, `eval/results_06.py`, your prompts | Yours to create, on `lab-06-split` only | **Yes**, on `lab-06-split` |
| `runs/`, `tracker/`, `results/`, `logs/` | Made as you run: traces, call records, the ledger, the tracker's database, the reviewer's and the hook's logs; `results/runs_06.jsonl` from your script | Written by the harness and your code; **commit them** on `main` |

## Running

```bash
python run.py --tasks fixtures/tasks6 --way agent --budget 250000 --runs 3    # arm S
python run.py --tasks fixtures/tasks6 --way split --budget 250000 --runs 3    # arm M, on lab-06-split
python run.py --tasks fixtures/tasks6 --way splus --match split --runs 3      # arm S-plus, on lab-06-split
python run.py --way split --set dev --budget 250000                           # try the split on the development issues
python run.py --tasks fixtures/tasks6/batch-a.yaml --way split --budget 250000 \
    --backend harness.scripted:ScriptedWorkers                                # one task, free
make check-06                                                                 # the Assignment 6 checker
```

`--budget B` is the token budget per issue: a batch gets 5*B. Your way reads it as
`ctx.budget`, and it is also the run's hard ceiling (`ctx.ceiling`), shared by every
agent: past it, the next model call raises and the run ends `token_budget`.
`--match split` gives each task the mean spend of your finished split runs on it,
on the same backend, as its budget, under the ceiling those runs had.

On your model, a run of a task in `fixtures/tasks6/` that a way has already
finished at that sweep is skipped, so the same command again redoes only the runs a
rate limit or the daily quota stopped. To measure a way again after a change,
`python run.py --tasks fixtures/tasks6 --way <way> --discard` first. Scripted runs
and `--set` or `--issues` runs always run anew.

**ScriptedWorkers** is a scripted model for testing a split without spending a
token. It tells its loops apart by the tools they are offered: offered every tool,
it triages each issue the first message names, in turn; offered reads and a tool
whose input has `could_not_determine` (your worker's return), it reads the issue,
searches, reads `src/ingest/dedupe.ts` and calls the return tool with every field
your schema names; offered only writes, it applies the label, opens the PR and
posts the comment from the first `label:` and `file:` lines in its messages. Its
answers are always `bug` and `src/ingest/dedupe.ts`, so its runs test your
plumbing, never your accuracy, and the checker leaves them out.

## How your code calls the harness

```python
# In your way: the task, its budget, and one agent per role (checks/FORMATS.md, section 14)
def run(ctx):
    ctx.task.id, ctx.task.kind, ctx.issues          # "batch-a", "batch", [4410, 4412, 4414, 4420, 4423]
    ctx.budget, ctx.ceiling                          # the run's token budget, and its hard ceiling
    lead = ctx.agent("coordinator")                  # parent None
    worker = ctx.agent("investigator-4410", parent="coordinator")
    run_loop(worker.client, worker_tools, prompt, brief, bounds, worker.trace)   # Assignment 1's loop, one agent
    worker.client.total_tokens                       # this agent's tokens; ctx.client.total_tokens is the run's
    lead.trace.event("wait", waiter="coordinator", on=worker.id, what="a finding", turn=0)
    lead.trace.event("worker_return", worker=worker.id, contract=returned, valid=not errors, errors=errors)
    lead.call_tool(step, name, args)                 # a call your own code makes, on the coordinator's lines

# A role's tool surface: anything with .schemas and .call(name, input), which run_loop accepts
ctx.tools.schemas                                    # every tool's definition; give a role only its own
ctx.tools.call(name, args)                           # the registry: the hook, the keys, the call record

# The disclosure line, in code, before the registry (Assignment 5's)
from ways.agent import disclosure_line, with_disclosure
body = with_disclosure(body, disclosure_line())

# The end state, and the grounded check (sections 14.6 and 14.7)
from harness.tasks import end_state, load_tasks
state = end_state(ctx.tracker, ctx.run_id, ctx.task)   # {issue: {"comments", "labels", "prs"}}
from eval.check_task import check_task
check_task(run_id, task)["passed"]                   # from the tracker, never from an agent's words

# Validating a return against your schema
from harness.schema import errors
errors(returned, schema)                             # [] when it fits
```

An agent's `trace.end(reason, detail)` writes an `agent_end` line and never ends
the run; a worker can run `run_loop` unchanged. An agent's trace ends once, and
`run_loop` ends it at every exit, so give each loop an agent of its own (S-plus's
attempts, say, `attempt-2-4410`). In a split run, write every model and tool line
through an agent's trace: `ctx.trace` and `ctx.call_tool` write lines that name no
agent.

## The rules the harness enforces

- **Success is read from the environment, never from the agent.** The grounded
  check reads the tracker; a spend comes from the `run_end` lines.
- **Every read of the tracker is scoped to one run**, and every write is stamped
  with it.
- **Every run has a hard ceiling**: its task's budget, under the harness's own
  (`session_token_ceiling`); and **every assignment has one** (`lab_token_ceiling`).
  The runner stops starting runs at the second. Ask before you pass `--over-budget`.
- **Every run records what it held constant**: the model, the tools, the budget, the
  evaluator and the task set.
- **Prompts live in `prompts/`**, and a layer held only by a prompt is empty.
- **Disclose AI assistance** in each report: which tool, what it wrote, what you
  checked.

## Submitting an assignment

Your copy of this repository is private. When you create it, add the course
staff's GitHub account as a collaborator (**Settings**, then **Collaborators**)
and post its URL on the assignment in Canvas: that is how staff find and read
your work.

Tag the last commit of `lab-06-split` and push the branch and the tag; then, on
`main`, run `make check-06`, commit everything, including `runs/`, `tracker/` and
`results/`, tag the commit and push both. A tag you have not pushed has not been
submitted.

```bash
git switch lab-06-split
git push
git tag lab-06-split-final
git push origin lab-06-split-final
git switch main
make check-06
git add -A
git commit -m "Assignment 6"
git tag lab-06
git push
git push origin lab-06
```
