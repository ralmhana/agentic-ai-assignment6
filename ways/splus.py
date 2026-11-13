"""Arm S-plus: one agent, same task, with M's matched per-task budget."""
from __future__ import annotations

from dataclasses import replace
from agent.loop import load_bounds, run_loop
from ways.agent import Disclosing, disclosure_line, task_message


def run(ctx) -> None:
    bounds = load_bounds()
    n = len(ctx.issues)
    bounds = replace(bounds, max_steps=bounds.max_steps * n,
                     wall_clock_s=bounds.wall_clock_s * n,
                     max_tokens=ctx.budget if ctx.budget is not None else bounds.max_tokens * n)
    agent = ctx.agent("single")
    run_loop(agent.client, Disclosing(ctx.tools, disclosure_line()),
             ctx.prompt("splus.md"), task_message(ctx.issues), bounds, agent.trace)
