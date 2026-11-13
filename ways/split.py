"""Arm M: independent investigations, checked handoffs, serialized publication."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import PurePosixPath

from agent.loop import load_bounds, run_loop
from harness.client import tool_result
from harness.formats import LABELS, normalize_path, parse_triage_comment
from harness.roles import arg, role_of
from harness.schema import errors as schema_errors
from harness.tasks import end_state
from tools import ToolResult
from ways.agent import disclosure_line, with_disclosure
from split.guards import SharedState, WaitGraph, check_combined

RETURN = "return_finding"


class RoleTools:
    """Restrict advertised tools AND dispatch; collect observed facts for each worker."""
    def __init__(self, registry, roles: set[str], issue: int, *, finding=None, schema=None):
        self.registry, self.roles, self.issue = registry, roles, issue
        self.finding, self.schema = finding, schema
        self.calls = 0
        self.searched: list[str] = []
        self.returned = None
        self.stage = 0
        self.schemas = [s for s in registry.schemas if role_of(s["name"]) in roles]
        if schema is not None:
            self.schemas.append({"name": RETURN, "description": "Return the investigation to the coordinator. This makes no repository write.",
                                 "input_schema": schema, "strict": True})

    def call(self, name: str, values: dict):
        if name == RETURN and self.schema is not None and self.returned is None:
            self.returned = {**values, "calls_used": self.calls, "searched": list(self.searched)}
            return ToolResult("Finding received by coordinator.", False, 0.0)
        role = role_of(name)
        values = dict(values) if isinstance(values, dict) else {}
        if self.schema is not None and role is not None:
            self.calls += 1
            key = (arg("search", "query") if role == "search" else
                   arg("read_file", "path") if role == "read_file" else None)
            if key is not None and values.get(key) is not None:
                item = str(values[key])
                if item not in self.searched:
                    self.searched.append(item)
        if role not in self.roles:
            return ToolResult("Tool unavailable to this role.", True, 0.0)
        if role in ("read_issue", "apply_label", "open_pr", "comment"):
            if str(values.get(arg(role, "number"))) != f"issue-{self.issue}":
                return ToolResult("This role owns a different issue.", True, 0.0)
        if self.finding is not None:
            label, file = self.finding["label"], self.finding["file"]
            expected = (["apply_label", "comment"] if file == "none" else
                        ["apply_label", "open_pr", "comment"])
            if self.stage >= len(expected) or role != expected[self.stage]:
                return ToolResult("Publish in order: label, optional PR, comment.", True, 0.0)
            if role == "apply_label" and values.get(arg(role, "label")) != label:
                return ToolResult("Label differs from the accepted finding.", True, 0.0)
            if role == "open_pr" and (file == "none" or not any(
                file in str(values.get(arg(role, key), "")) for key in ("title", "body")
            )):
                return ToolResult("PR must name the accepted file.", True, 0.0)
            if role == "comment":
                body_key = arg(role, "body")
                if parse_triage_comment(values.get(body_key, "")) != (label, file):
                    return ToolResult("Comment differs from the accepted finding.", True, 0.0)
                values[body_key] = with_disclosure(values[body_key], disclosure_line())
        result = self.registry.call(name, values)
        if self.finding is not None and not result.is_error:
            self.stage += 1
        return result


def _investigate(ctx, worker, issue, schema, tokens):
    tools = RoleTools(ctx.tools, {"read_issue", "search", "read_file"}, issue, schema=schema)
    bounds = replace(load_bounds(), max_steps=12, max_tokens=tokens)
    messages = [{"role": "user", "content":
                 f"Investigate issue #{issue}. Read the file you will name as responsible, "
                 "then return one finding with label, file and concrete evidence."}]
    started = time.monotonic()
    step = 0
    while tools.returned is None:
        if step >= bounds.max_steps:
            worker.trace.end("turn_limit", detail=f"{step} model calls without a structured return")
            break
        if worker.client.total_tokens >= bounds.max_tokens:
            worker.trace.end("token_budget", detail=f"{worker.client.total_tokens} tokens")
            break
        if time.monotonic() - started >= bounds.wall_clock_s:
            worker.trace.end("wall_clock", detail=f"{time.monotonic() - started:.1f}s")
            break
        step += 1
        response = worker.client.create(system=ctx.prompt("investigator.md"),
                                        messages=messages, tools=tools.schemas)
        worker.trace.model_call(step, response)
        messages.append(response.assistant_message())
        if not response.tool_calls:
            messages.append({"role": "user", "content":
                             "Finish by calling return_finding. Use only bug, feature, question, or docs "
                             "as the label. Name the file that needs a change, after reading it; "
                             "a supporting file is evidence, not necessarily the responsible file. "
                             "State uncertainty with candidate or out_of_budget instead of guessing."})
            continue
        results = []
        for call in response.tool_calls:
            result = tools.call(call.name, call.input)
            worker.trace.tool_call(step, call, result)
            results.append(tool_result(call, result.content, result.is_error))
            if tools.returned is not None:
                break
        messages.append({"role": "user", "content": results})
    if tools.returned is not None:
        worker.trace.end("model_stopped", detail="structured return received")
    if tools.returned is not None:
        # The loop may make more calls after the local return tool; the recorded
        # facts must describe every actual call before coordinator receipt.
        return {**tools.returned, "calls_used": tools.calls, "searched": list(tools.searched)}
    return {"result": {"issue": issue, "label": "question", "file": "none", "evidence": ""},
            "status": "out_of_budget", "searched": tools.searched,
            "not_searched": [], "calls_used": tools.calls,
            "could_not_determine": ["No complete structured finding was returned."]}


def _acceptable(contract, issue: int) -> list[str]:
    result = contract["result"]
    file = normalize_path(result["file"])
    problems = []
    if result["issue"] != issue:
        problems.append("issue ownership differs")
    if contract["status"] != "found" or contract["could_not_determine"]:
        problems.append("finding is uncertain")
    if result["label"] not in LABELS or not file or file.startswith("/") or ".." in PurePosixPath(file).parts:
        problems.append("invalid label or file")
    if not result["evidence"].strip() or (file != "none" and file not in contract["searched"]):
        problems.append("no evidence for the responsible file")
    return problems


def run(ctx) -> None:
    issues = ctx.issues
    coordinator = ctx.agent("coordinator")
    schema = json.loads((ctx.root / "split" / "contract.schema.json").read_text(encoding="utf-8-sig"))
    graph = WaitGraph()
    shared = SharedState({f"finding-{n}": "" for n in issues})
    allotment = max(1000, int((ctx.budget or 250000 * len(issues)) * .65 / len(issues)))
    workers = {n: ctx.agent(f"investigator-{n}", parent="coordinator") for n in issues}
    for n in issues:
        cycle = graph.wait(coordinator.id, workers[n].id, "issue finding")
        coordinator.trace.event("wait", waiter=coordinator.id, on=workers[n].id, what="issue finding", turn=0)
        if cycle:
            victim = graph.victim(cycle)
            coordinator.trace.event("worker_stopped", worker=victim, reason="wait cycle")
            graph.done(coordinator.id, workers[n].id)
    accepted = {}
    with ThreadPoolExecutor(max_workers=len(issues)) as pool:
        pending = {pool.submit(_investigate, ctx, workers[n], n, schema, allotment): n for n in issues}
        for future in as_completed(pending):
            n = pending[future]
            contract = future.result()
            worker_id = workers[n].id
            graph.done(coordinator.id, worker_id)
            errors = schema_errors(contract, schema)
            coordinator.trace.event("worker_return", worker=worker_id, contract=contract,
                                    valid=not errors, errors=errors)
            problems = errors or _acceptable(contract, n)
            if problems:
                coordinator.trace.event("worker_stopped", worker=worker_id, reason="; ".join(problems))
                continue
            key = f"finding-{n}"
            _, version = shared.read(coordinator.id, key)
            if not shared.write(coordinator.id, key, json.dumps(contract["result"]), version):
                coordinator.trace.event("worker_stopped", worker=worker_id, reason="stale finding version")
                continue
            accepted[n] = contract["result"]
    for n in issues:
        if n not in accepted:
            continue
        finding = accepted[n]
        publisher = ctx.agent(f"publisher-{n}", parent="coordinator")
        tools = RoleTools(ctx.tools, {"apply_label", "open_pr", "comment"}, n, finding=finding)
        coordinator.trace.event("wait", waiter="coordinator", on=publisher.id, what="publication", turn=0)
        run_loop(publisher.client, tools, ctx.prompt("publisher.md"),
                 f"Publish issue #{n}.\nlabel: {finding['label']}\nfile: {finding['file']}\nEvidence: {finding['evidence']}",
                 replace(load_bounds(), max_steps=8, max_tokens=max(1000, int((ctx.budget or 250000 * len(issues)) * .30 / len(issues)))),
                 publisher.trace)
    violations = check_combined(ctx.task, end_state(ctx.tracker, ctx.run_id, ctx.task))
    coordinator.trace.event("combined_check", passed=not violations, violations=violations)
    coordinator.trace.end("model_stopped", detail=f"{len(accepted)}/{len(issues)} findings accepted")

