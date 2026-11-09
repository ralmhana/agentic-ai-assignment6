"""RepoMind harness: the parts of the system the course provides.

You build on these; you do not edit them. The checkers assume they are unchanged.

    settings  course settings (model, ceilings)
    pricing   the dated price sheet
    formats   the formats a checker reads: comments, terminal reasons, paths, plans
    trace     one JSONL line per model call, per tool call, per plan and per event
              and, from Assignment 6, a trace per agent: each line names its agent and parent
    client    the metered model client, with a hard per-run ceiling; from Assignment 4,
              on issues 4191 and 4192, the request record (runs/<run_id>.requests.jsonl)
              and, from Assignment 6, a client per agent, sharing the run's ceiling
    backends  the real model provider
    scripted  scripted models for testing without spending tokens; from Assignment 5,
              the three moments and the boundary's test run
    tracker   the mock issue tracker and remote, in SQLite; it can lie (Assignment 3);
              from Assignment 5, labels, closed issues, pushes, merges, branch
              protection on main, a log of every write, the three compensating
              endpoints, and each issue's metadata and each call's facts
    reviewer  Assignment 5: the person, or the script, who answers an approval
              (REVIEWER), and bin/review's queue
    inbox     Assignment 5: messages from a user, delivered to a run between steps
    notify    Assignment 5: the notification sink, logs/notifications.jsonl
    clock     Assignment 5: one form of time for every log, to the millisecond
    switches  FLAKY_WRITES, READBACK_FAIL, KEY_MODE and VERIFY, read from the environment
    roles     which of your tools plays each role (tools/roles.yaml)
    calls     the call record, one line per tool call (runs/<run_id>.calls.jsonl)
    runner    runs a way over issues, stamps run IDs, keeps the token ledger; from
              Assignment 4, kills a run at a plan step (--die-after-step,
              --die-during-step) and resumes it under its own run_id (--resume); from
              Assignment 5, resumes a run that ended held or stopped; from Assignment 6,
              runs a way over a task set, with a token budget per issue (--tasks, --budget)
    tasks     Assignment 6: the task set (fixtures/tasks6/), each task one issue or a
              batch of five, with its known answers and its token budget
    constants Assignment 6: the five things a comparison holds constant (slide 59),
              recorded in every run_start line
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The assignment this copy of the repository is for. The runner records it on every
# run (run_start.lab), and each assignment's checker reads only its own runs.
LAB = "06"
