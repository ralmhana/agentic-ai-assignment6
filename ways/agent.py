"""Way 3, the agent: the model decides what to call and when to stop. Arm S in Assignment 6.

One loop holding every tool, on the task's issues: one, or a batch of five in one
context, one after another. It does Assignment 5's daily task (the label, a draft
pull request when the file is not none, the comment last), and every call goes
through the registry and its hook, as every call from any agent does.

Its bounds are Assignment 1's, per issue: a batch gets five times the steps and the
wall-clock. Its token budget is the run's, ctx.budget, which run.py --budget sets
per issue (a batch gets five times it), and which every arm of Part C shares on
paper.

The disclosure line in policy/autonomy.yaml goes on every comment here, in code,
before the registry: the model never has to remember it, and the hook refuses a
comment without it. `with_disclosure` is the one function every comment passes.
"""

from __future__ import annotations

from dataclasses import replace

from agent.loop import load_bounds, run_loop
from harness.roles import arg, role_of


def with_disclosure(body: str, line: str) -> str:
    """The comment with the disclosure line after its first two lines (label and file),
    unless it already has it there."""
    lines = str(body or "").splitlines()
    if not line or any(r.strip() == line for r in lines[2:]):
        return str(body or "")
    return "\n".join(lines[:2] + [line] + (lines[2:] if lines[2:] else []))


class Disclosing:
    """A registry whose comments carry the disclosure line, added in code."""

    def __init__(self, tools, line: str):
        self.tools, self.line = tools, line
        self.body_arg = _body_arg()

    @property
    def schemas(self) -> list[dict]:
        return self.tools.schemas

    def call(self, name: str, args: dict, **kwargs):
        if role_of(name) == "comment" and isinstance(args, dict) and self.body_arg in args:
            args = {**args, self.body_arg: with_disclosure(args[self.body_arg], self.line)}
        return self.tools.call(name, args, **kwargs)

    def __getattr__(self, attr):          # everything else is the registry's
        return getattr(self.tools, attr)


def _body_arg() -> str:
    return arg("comment", "body")


def disclosure_line() -> str:
    from policy.hook import disclosure
    return disclosure()


def task_message(issues: list[int]) -> str:
    if len(issues) == 1:
        return f"Triage issue #{issues[0]}."
    listed = ", ".join(f"#{n}" for n in issues)
    return (f"Triage these {len(issues)} issues, one after another: {listed}. Each gets its own label, "
            f"its own pull request when a file is responsible, and its own comment.")


def run(ctx) -> None:
    issues = ctx.issues
    bounds = load_bounds()
    n = len(issues)
    bounds = replace(bounds, max_steps=bounds.max_steps * n, wall_clock_s=bounds.wall_clock_s * n,
                     max_tokens=ctx.budget if ctx.budget else bounds.max_tokens * n)
    run_loop(ctx.client, Disclosing(ctx.tools, disclosure_line()), ctx.prompt("agent.md"),
             task_message(issues), bounds, ctx.trace)


__all__ = ["run", "with_disclosure", "Disclosing", "disclosure_line", "task_message"]
