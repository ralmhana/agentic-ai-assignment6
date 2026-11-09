"""Fill reports/LAB_04.json from the environment: Assignment 4's working solution,
as Assignment 4 left it.

    python -m eval.lab04_report --uncrashed <run_id>

Reads the traces in runs/, the tracker's database and its archives, the checkpoints
and the store, and writes plan_marks, durability, uncrashed_run_id, matrix_derived,
matrix_uuid, duplicate_comment_ids, reopened and checkpoint_bytes
(checks/FORMATS.md, section 12.9). contradiction_test is written by
state/contradiction_test.py, session 3.

A matrix cell is the latest killed and resumed run per (when, step) and key mode, on
issue 4201. The reopened sets are the latest five runs of issue 4207 of each kind,
told apart by their store_read line (store "empty" or the store's file), leaving out
the first run with the store, the seed. checkpoint_bytes compares the runs that also
saved their checkpoints with the conversation (CHECKPOINT_CONVERSATION=1).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import yaml

from eval.check_triage import check
from harness import LAB, ROOT
from harness.formats import normalize_path, parse_triage_comment
from harness.roles import WRITES, role_of
from harness.runner import is_free, is_trace
from harness.trace import read_trace
from harness.tracker import Tracker
from state.checkpointer import Checkpointer

MATRIX_ISSUE, REOPENED = 4201, 4207
BRANCH = f"repomind/issue-{MATRIX_ISSUE}"
CONVERSATION_DB = ROOT / "state" / "checkpoints_with_conversation.db"
PLACEMENT = {"read_file": "after", "comment": "before", "open_pr": "before"}


def runs() -> list[dict]:
    out = []
    for path in sorted((ROOT / "runs").glob("*.jsonl")):
        if not is_trace(path):
            continue
        records = read_trace(path)
        start = records[0] if records and records[0].get("type") == "run_start" else None
        if not start or start.get("lab") != LAB or start.get("way") != "planned" or is_free(start.get("backend") or ""):
            continue
        out.append({"run_id": start["run_id"], "start": start, "records": records, "mtime": path.stat().st_mtime})
    return out


def writes() -> tuple[dict, dict]:
    comments, prs = {}, {}
    files = [ROOT / "tracker" / "tracker.db", *sorted((ROOT / "tracker" / "archive").glob("*.db"))]
    for path in (p for p in files if p.exists()):
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        for table, sink in (("comments", comments), ("prs", prs)):
            for row in db.execute(f"SELECT * FROM {table} ORDER BY id"):
                sink.setdefault(row["run_id"], []).append(dict(row))
        db.close()
    return comments, prs


def resumed(run: dict) -> bool:
    types = [r.get("type") for r in run["records"]]
    return "resume" in types and "run_end" in types


def matrix(all_runs: list[dict], key_mode: str, comments: dict, prs: dict, cp: Checkpointer) -> list[dict]:
    latest = {}
    for run in all_runs:
        die, switches = run["start"].get("die"), run["start"].get("switches") or {}
        if run["start"].get("issue") != MATRIX_ISSUE or not die or (switches.get("key_mode") or "derived") != key_mode:
            continue
        key = (die["when"], die["step"])
        order = (run["start"].get("started") or "", run["mtime"])
        if key not in latest or order > latest[key][0]:
            latest[key] = (order, run)
    out = []
    for (when, step), (_, run) in sorted(latest.items(), key=lambda kv: (kv[0][1], kv[0][0] != "after")):
        rid = run["run_id"]
        mine = [c for c in comments.get(rid, []) if c["issue"] == MATRIX_ISSUE]
        open_prs = [p for p in prs.get(rid, []) if p["branch"] == BRANCH and p["state"] == "open"]
        saved = cp.all(rid)
        findings = saved[-1]["findings"] if saved else {}
        matches = False
        if resumed(run) and len(mine) == 1 and "file" in findings:
            label, file = parse_triage_comment(mine[0]["body"])
            want = normalize_path(str(findings["file"]))
            matches = (label, file) == (findings.get("label"), want) and len(open_prs) == (0 if want == "none" else 1)
        out.append({"run_id": rid, "step": step, "when": when, "comments": len(mine), "open_prs": len(open_prs),
                    "matches": matches, "comment_ids": [c["id"] for c in mine]})
    return out


def reopened(all_runs: list[dict], tracker: Tracker) -> dict:
    answer = yaml.safe_load((ROOT / "fixtures" / "answers.yaml").read_text())["eval"][REOPENED]
    kinds = {"with_store": [], "empty_store": []}
    for run in sorted(all_runs, key=lambda r: (r["start"].get("started") or "", r["mtime"])):
        finished = any(r.get("type") == "run_end" for r in run["records"])
        if run["start"].get("issue") != REOPENED or run["start"].get("die") or not finished:
            continue
        read = next((r for r in run["records"] if r.get("type") == "store_read"), None)
        if read is None:
            continue
        kinds["empty_store" if read.get("store") == "empty" else "with_store"].append(run)
    kinds["with_store"] = kinds["with_store"][1:]        # the first is the seed run
    out = {}
    for name, chosen in kinds.items():
        chosen = chosen[-5:]
        ids = [r["run_id"] for r in chosen]
        calls = [sum(1 for x in r["records"] if x.get("type") == "tool_call") for r in chosen]
        tokens = [next((x.get("totals") or {} for x in reversed(r["records"]) if x.get("type") == "run_end"), {})
                  .get("total_tokens", 0) for r in chosen]
        out[name] = {"runs": len(chosen), "passes": sum(check(tracker, i, REOPENED, answer) for i in ids),
                     "mean_tool_calls": round(sum(calls) / len(calls), 2) if calls else None,
                     "mean_tokens": round(sum(tokens) / len(tokens)) if tokens else None, "run_ids": ids}
    return out


def checkpoint_bytes(cp: Checkpointer) -> dict:
    if not CONVERSATION_DB.exists():
        return {"structured": None, "with_conversation": None, "runs": 0}
    wide = Checkpointer(CONVERSATION_DB)
    ids = [r for r in wide.runs() if cp.all(r)]
    if not ids:
        return {"structured": None, "with_conversation": None, "runs": 0}
    return {"structured": round(sum(cp.size(r) for r in ids) / len(ids)),
            "with_conversation": round(sum(wide.size(r) for r in ids) / len(ids)), "runs": len(ids)}


def plan_marks(run: dict) -> list[dict]:
    plan = next((r["plan"] for r in reversed(run["records"]) if r.get("type") == "plan"), {"steps": []})
    marks = []
    for step in plan.get("steps") or []:
        role = role_of(str(step.get("tool")))
        kind = "keyed_write" if role in WRITES else "read"
        marks.append({"step": step.get("id"), "kind": kind, "checkpoint": PLACEMENT.get(role, "none")})
    return marks


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--uncrashed", required=True, help="Part B's uncrashed run of issue 4201")
    a = p.parse_args(argv)
    all_runs = runs()
    base = next((r for r in all_runs if r["run_id"] == a.uncrashed), None)
    if base is None:
        raise SystemExit(f"{a.uncrashed} is not a run of this assignment in runs/")
    comments, prs = writes()
    cp = Checkpointer()
    tracker = Tracker(ROOT, flaky=False, readback_fail=False)
    derived = matrix(all_runs, "derived", comments, prs, cp)
    uuid = matrix(all_runs, "uuid", comments, prs, cp)
    path = ROOT / "reports" / "LAB_04.json"
    report = json.loads(path.read_text())
    report.update({
        "plan_marks": plan_marks(base), "durability": "sync", "uncrashed_run_id": a.uncrashed,
        "matrix_derived": [{k: v for k, v in c.items() if k != "comment_ids"} for c in derived],
        "matrix_uuid": [{k: v for k, v in c.items() if k != "comment_ids"} for c in uuid],
        "duplicate_comment_ids": {c["run_id"]: c["comment_ids"] for c in uuid if c["comments"] > 1},
        "reopened": reopened(all_runs, tracker), "checkpoint_bytes": checkpoint_bytes(cp),
    })
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("matrix_derived", "matrix_uuid", "duplicate_comment_ids")}, indent=1)[:3000])
    print(json.dumps({k: report[k] for k in ("reopened", "checkpoint_bytes", "plan_marks")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
