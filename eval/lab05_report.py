"""reports/LAB_05.json from what the runs left. Assignment 5's working solution.
It ships in Assignment 6's starter as RepoMind's own.

    python -m eval.lab05_report [--rollback RUN_ID]

Every number is read from the environment: the replay from bin/replay_policy's own
function, the diagnostics from logs/approvals.jsonl, the moments from the runs on
4501 to 4503 and the remote, the stop from logs/stops.jsonl, the rollback from the
remote's write log. The ranking is the reference's table (reports/LAB_05.md, Part A).
"""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import json
import statistics
from pathlib import Path

from harness import LAB, ROOT
from harness.clock import seconds_between
from harness.runner import is_free, is_trace
from harness.trace import read_trace
from harness.tracker import Tracker
from policy.hook import disclosure

ROLLUP = ROOT / "fixtures" / "rollup_2026-08-04.jsonl"
MOMENTS = {"A": 4501, "B": 4502, "C": 4503}
# Part A's ranking: undo (revert | compensate | none), noticed (yes | no), blast (narrow | wide), the column.
RANKING = [
    ("read_issue", None, "revert", "yes", "narrow", "independent"),
    ("search_repo", None, "revert", "yes", "narrow", "independent"),
    ("read_file", None, "revert", "yes", "narrow", "independent"),
    ("run_tests", None, "revert", "yes", "narrow", "independent"),
    ("apply_label", None, "compensate", "yes", "narrow", "independent"),
    ("close_issue", None, "compensate", "yes", "narrow", "independent"),
    ("post_comment", "agent_opened", "none", "yes", "narrow", "independent"),
    ("post_comment", "quiet", "none", "yes", "narrow", "independent"),
    ("post_comment", "human_active", "none", "yes", "wide", "requires_approval"),
    ("open_pr", None, "compensate", "yes", "wide", "requires_approval"),
    ("push_commit", "unprotected", "none", "yes", "wide", "requires_approval"),
    ("push_commit", "protected", "none", "yes", "wide", "prohibited"),
    ("merge_pr", None, "none", "no", "wide", "prohibited"),
]


def replay_module():
    path = ROOT / "bin" / "replay_policy"
    loader = importlib.machinery.SourceFileLoader("replay_policy", str(path))
    spec = importlib.util.spec_from_loader("replay_policy", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()] if Path(path).exists() else []


def runs() -> dict[str, dict]:
    out = {}
    for path in sorted((ROOT / "runs").glob("*.jsonl")):
        if not is_trace(path):
            continue
        records = read_trace(path)
        if records and records[0].get("type") == "run_start" and records[0].get("lab") == LAB:
            out[records[0]["run_id"]] = {"start": records[0], "records": records, "mtime": path.stat().st_mtime}
    return out


def diagnostics(real: set[str], wide: set[str]) -> dict:
    lines = [a for a in jsonl(ROOT / "logs" / "approvals.jsonl") if a.get("reviewer") == "human"
             and (a.get("kind") or "approval") == "approval" and a.get("decision") in ("approve", "deny")
             and a.get("run_id") in real]
    if not lines:
        return {"decisions": 0, "approval_rate_all": None, "approval_rate_irreversible_wide": None,
                "irreversible_wide_classes": sorted(wide), "median_seconds_by_class": {}}
    on_wide = [a for a in lines if a.get("action_class") in wide]
    by_class: dict[str, list[float]] = {}
    for a in lines:
        if isinstance(a.get("seconds"), (int, float)):
            by_class.setdefault(a["action_class"], []).append(float(a["seconds"]))
    return {"decisions": len(lines),
            "approval_rate_all": round(sum(a["decision"] == "approve" for a in lines) / len(lines), 2),
            "approval_rate_irreversible_wide": (round(sum(a["decision"] == "approve" for a in on_wide) / len(on_wide), 2)
                                                if on_wide else None),
            "irreversible_wide_classes": sorted(wide),
            "median_seconds_by_class": {k: round(statistics.median(v), 1) for k, v in sorted(by_class.items())}}


def moments(all_runs: dict, tracker: Tracker) -> dict:
    out = {}
    for name, issue in MOMENTS.items():
        mine = sorted((r for r in all_runs.values() if r["start"].get("issue") == issue), key=lambda r: r["mtime"])
        if not mine:
            out[name] = {"escalated": None, "proceeded": None, "run_id": None}
            continue
        run = mine[-1]
        rid = run["start"]["run_id"]
        escalated = any(r.get("type") == "escalation" for r in run["records"])
        wrote = {w["action"] for w in tracker.log(rid) if w["outcome"] in ("written", "timeout_after_commit")}
        out[name] = {"escalated": escalated,
                     "proceeded": ("push_commit" if name == "A" else "post_comment") in wrote, "run_id": rid}
    return out


def stop(real: set[str]) -> dict:
    events: dict[str, dict] = {}
    for line in jsonl(ROOT / "logs" / "stops.jsonl"):
        if line.get("run_id") not in real:
            continue
        ev = events.setdefault(line["run_id"], {})
        if line["event"] == "requested" and "effective" not in ev:
            ev["requested"] = line["at"]
        elif line["event"] == "effective" and "requested" in ev and "effective" not in ev:
            ev["effective"] = line["at"]
    done = {rid: ev for rid, ev in events.items() if "effective" in ev}
    latencies = [seconds_between(ev["requested"], ev["effective"]) for ev in done.values()]
    return {"run_ids": list(done), "latencies_s": latencies,
            "p50_s": round(statistics.median(latencies), 3) if latencies else None,
            "max_s": round(max(latencies), 3) if latencies else None, "partial_condition": "fast"}


def rollback(run_id: str | None, tracker: Tracker) -> dict:
    if not run_id:
        return {"run_id": None, "compensated": [], "none": []}
    log = tracker.log(run_id)
    undone = {"remove_label": "apply_label", "close_pr": "open_pr", "reopen_issue": "close_issue"}
    compensated = [{"action": undone[w["action"]], "target": str(w["target"]), "by": w["action"]}
                   for w in log if w["action"] in undone]
    none = [{"action": w["action"], "target": str(w["target"])} for w in log
            if w["action"] in ("post_comment", "push_commit", "merge_pr") and w["outcome"] in ("written",
                                                                                               "timeout_after_commit")]
    return {"run_id": run_id, "compensated": compensated, "none": none}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rollback", help="the run bin/rollback undid")
    a = p.parse_args(argv)
    path = ROOT / "reports" / "LAB_05.json"
    report = json.loads(path.read_text()) if path.exists() else {}
    tracker = Tracker(flaky=False, readback_fail=False)
    all_runs = runs()
    real = {rid for rid, r in all_runs.items() if not is_free(r["start"].get("backend") or "")}
    ranking = [{"action": act, "circumstance": circ, "action_class": f"{act}/{circ}" if circ else act, "undo": undo,
                "noticed": noticed, "blast": blast, "column": column}
               for act, circ, undo, noticed, blast, column in RANKING]
    wide = {r["action_class"] for r in ranking if r["undo"] == "none" and r["blast"] == "wide"}
    replay = replay_module()
    plain = replay.replay(ROLLUP)
    batched = replay.replay(ROLLUP, batched=True)
    report.update({
        "ranking": ranking,
        "replay": plain,
        "diagnostics": diagnostics(real, wide),
        "batching": {"covers": batched["covers"], "prompts_per_day_before": plain["prompts_per_day"],
                     "prompts_per_day_after": batched["prompts_per_day"]},
        "moments": moments(all_runs, tracker),
        "stop": stop(real),
        "rollback": rollback(a.rollback or (report.get("rollback") or {}).get("run_id"), tracker),
        "disclosure": {"line": disclosure()},
    })
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {path.relative_to(ROOT)}: {report['diagnostics']['decisions']} human decisions, "
          f"{len(report['stop']['run_ids'])} stops, replay {plain['prompts_per_day']} prompts a day "
          f"({batched['prompts_per_day']} batched)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
