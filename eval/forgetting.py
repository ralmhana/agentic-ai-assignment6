"""Part F's seven runs, and `forgetting` in reports/LAB_04.json: Assignment 4's
working solution, as Assignment 4 left it.

    python -m eval.forgetting [--backend NAME] [--cases attention compaction session]

One fact, a rule a maintainer states, lost three ways and fixed each way (Lecture 4,
slide 34), on issue 4192, through ways/planned.py's Part F switches:

  attention   told the fact first, under PLANT_BURY characters of Ledgerline's files;
              then told it last, after the step results
  compaction  told it as the history's first turn, compacted past REPOMIND_COMPACT_AT
              tokens; then the same with --notes on, which keeps it outside the history
  session     one run told it, with the store, which keeps it as stated; the next run
              with an empty store; then one with the store

The attention and compaction runs have an empty store, so that only the boundary under
test can lose or carry the fact. Each run's comment is read from the tracker, and the
script says when a lost run used the fact or a fixed run did not: run that case again.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from harness import ROOT
from harness.formats import parse_triage_comment
from harness.tracker import Tracker

ISSUE = 4192
FACT = ("Ledgerline's maintainers label every report about the Export button `feature`: they plan its "
        "fixes on the feature board.")
EFFECT = {"label": "feature"}
BURY = 60000          # characters of Ledgerline's files after the fact, in the attention case's lost run
COMPACT = 400         # tokens: low enough that every run compacts its history before it drafts the comment
SWITCHES = ("PLANT_FACT", "PLANT_BURY", "REPOMIND_COMPACT_AT", "REPOMIND_STORE")
RUNS = {
    "attention": [("lost", {"PLANT_FACT": FACT, "PLANT_BURY": str(BURY), "REPOMIND_STORE": "empty"}, []),
                  ("fixed", {"PLANT_FACT": FACT, "REPOMIND_STORE": "empty"}, [])],
    "compaction": [("lost", {"PLANT_FACT": FACT, "REPOMIND_COMPACT_AT": str(COMPACT), "REPOMIND_STORE": "empty"}, []),
                   ("fixed", {"PLANT_FACT": FACT, "REPOMIND_COMPACT_AT": str(COMPACT), "REPOMIND_STORE": "empty"},
                    ["--notes", "on"])],
    "session": [("stated", {"PLANT_FACT": FACT}, []),
                ("lost", {"REPOMIND_STORE": "empty"}, []),
                ("fixed", {}, [])],
}


def one_run(env: dict, extra: list[str], backend: str | None) -> str:
    clean = {k: v for k, v in os.environ.items() if k not in SWITCHES}
    command = [sys.executable, "run.py", "--way", "planned", "--issues", str(ISSUE), *extra]
    if backend:
        command += ["--backend", backend]
    done = subprocess.run(command, cwd=ROOT, env={**clean, **env}, capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"{' '.join(command)} failed:\n{done.stdout}{done.stderr}")
    return json.loads((ROOT / "runs" / "_ledger.jsonl").read_text().splitlines()[-1])["run_id"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--backend", default=None, help="a backend for run.py; your model when left out")
    p.add_argument("--cases", nargs="+", choices=list(RUNS), default=list(RUNS))
    a = p.parse_args(argv)
    path = ROOT / "reports" / "LAB_04.json"
    report = json.loads(path.read_text())
    part = report.get("forgetting") if isinstance(report.get("forgetting"), dict) else {}
    tracker = Tracker(ROOT, flaky=False, readback_fail=False)
    for case in a.cases:
        entry = {"fact": FACT, "effect": EFFECT}
        for role, env, extra in RUNS[case]:
            rid = one_run(env, extra, a.backend)
            entry[role] = rid
            comments = tracker.comments(rid, ISSUE)
            said = parse_triage_comment(comments[0]["body"]) if comments else (None, None)
            used = said[0] == EFFECT["label"]
            warn = "" if role == "stated" or used == (role == "fixed") else \
                f"   <- a {role} run that {'used' if used else 'did not use'} the fact: run --cases {case} again"
            print(f"{case:<11} {role:<7} {rid:<26} comment {said[0]}, {said[1]}{warn}")
        part[case] = entry
    report["forgetting"] = part
    path.write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
