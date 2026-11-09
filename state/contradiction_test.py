"""Part E, task 2: the contradiction test's second and third sessions. Session 1
is state/remember_candidates.py, which stored the maintainer's rule. Each session
is its own process. Assignment 4's working solution.

    python -m state.contradiction_test contradict   # session 2: the same maintainer changes the rule
    python -m state.contradiction_test check        # session 3: retrieve the rule, and record the IDs
"""

from __future__ import annotations

import json
import re
import sys
import time

from harness import ROOT
from state.store import REPOSITORY, Store

RULE = re.compile(r"duplicate", re.IGNORECASE)
NEW_RULE = ("For duplicates: label them `duplicate`, link the original, and close them after 14 days if the "
            "reporter has not replied.")


def rules(store: Store) -> list[dict]:
    return [r for r in store.active(REPOSITORY) if r["source"] == "user" and RULE.search(r["text"])]


def main(argv: list[str]) -> int:
    store = Store()
    if argv[:1] == ["contradict"]:
        current = rules(store)
        if len(current) != 1:
            raise SystemExit(f"want one active rule on duplicates to contradict, found {len(current)}")
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        new = store.supersede(current[0]["id"], {
            "repository": REPOSITORY, "issue": None, "kind": "semantic", "text": NEW_RULE, "source": "user",
            "written_at": when, "origin": "ingested", "confirmed": True,
            "stated_by": f"priya-s, a maintainer, a comment on issue 4185, {when}"})
        print(f"{new} supersedes {current[0]['id']}")
        return 0
    if argv[:1] == ["check"]:
        ids = [r["id"] for r in rules(store)]
        path = ROOT / "reports" / "LAB_04.json"
        report = json.loads(path.read_text())
        report["contradiction_test"] = ids
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"retrieved": ids}))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
