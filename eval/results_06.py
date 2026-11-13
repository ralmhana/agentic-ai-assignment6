"""Rebuild Assignment 6 measured rows and aggregates from traces and the tracker.

Usage: python -m eval.results_06. This does not fill the interpretation fields.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from eval.check_task import check_task
from harness import ROOT
from harness.runner import is_free, is_trace
from harness.tasks import load_tasks
from harness.trace import read_trace
from harness.tracker import Tracker

ARMS = {"agent": "S", "split": "M", "splus": "S_plus"}


def measured_rows(root: Path = ROOT) -> tuple[list[dict], dict]:
    tasks = {task.id: task for task in load_tasks(root / "fixtures/tasks6")}
    tracker = Tracker(flaky=False, readback_fail=False)
    rows, constants = [], {}
    for path in sorted((root / "runs").glob("*.jsonl")):
        if not is_trace(path):
            continue
        records = read_trace(path)
        start = next((r for r in records if r.get("type") == "run_start"), {})
        end = next((r for r in reversed(records) if r.get("type") == "run_end"), None)
        terminal = next((r for r in reversed(records) if r.get("type") == "end"), {})
        way, task_id = start.get("way"), start.get("task")
        if (task_id not in tasks or way not in ARMS or not end or
                terminal.get("terminal_reason") in {"quota", "rate_limited"} or
                is_free(str(start.get("backend") or ""))):
            continue
        task = tasks[task_id]
        run_id = start["run_id"]
        grounded = check_task(run_id, task, tracker)
        rows.append({"run_id": run_id, "arm": ARMS[way], "way": way, "task": task_id,
                     "kind": task.kind, "sweep": int(start["sweep"]),
                     "passed": grounded["passed"],
                     "parts": {str(k): v for k, v in grounded["parts"].items()},
                     "tokens": end["totals"]["total_tokens"], "wall_s": end["elapsed_s"]})
        constants[run_id] = start.get("constants")
    return rows, constants


def aggregate(rows: list[dict]) -> dict:
    out = {}
    for arm in ARMS.values():
        out[arm] = {}
        for kind in ("single", "batch"):
            mine = [r for r in rows if r["arm"] == arm and r["kind"] == kind]
            per_task, sweeps = defaultdict(int), defaultdict(int)
            for row in mine:
                per_task[row["task"]] += int(row["passed"])
                sweeps[row["sweep"]] += int(row["passed"])
            out[arm][kind] = {"runs": len(mine), "passes": sum(r["passed"] for r in mine),
                              "per_task": dict(sorted(per_task.items())),
                              "sweep_min": min(sweeps.values()) if sweeps else 0,
                              "sweep_max": max(sweeps.values()) if sweeps else 0,
                              "all_three": sum(v == 3 for v in per_task.values()),
                              "mean_tokens": round(mean(r["tokens"] for r in mine)) if mine else 0,
                              "mean_wall_s": round(mean(r["wall_s"] for r in mine), 1) if mine else 0}
    return out


def main() -> None:
    rows, constants = measured_rows()
    output = ROOT / "results/runs_06.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    report_path = ROOT / "reports/LAB_06.json"
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    report["arms"] = aggregate(rows)
    if constants:
        unique = {json.dumps(value, sort_keys=True) for value in constants.values()}
        if len(unique) != 1:
            raise ValueError("Measured runs disagree on held constants; report needs investigation")
        report["constants"] = next(iter(constants.values()))
    for kind in ("single", "batch"):
        s, m = report["arms"]["S"][kind], report["arms"]["M"][kind]
        report["multiplier"][kind] = round(m["mean_tokens"] / s["mean_tokens"], 3) if s["mean_tokens"] else None
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} grounded measured rows to {output}")
    print("M failures needing trace analysis:", [r["run_id"] for r in rows if r["arm"] == "M" and not r["passed"]])


if __name__ == "__main__":
    main()
