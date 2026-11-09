"""Session 1: put the three candidates in fixtures/memory/ through the write policy
and into the store. Assignment 4's working solution.

    python -m state.remember_candidates

Running it again writes nothing new.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from harness import ROOT
from state.store import REPOSITORY, Store


def decide(candidate: dict) -> dict | None:
    """state/write_policy.md, applied to one candidate. None: not stored."""
    seen, when = candidate["seen"].strip(), str(candidate["when"])
    if candidate["candidate"] == "A":   # worked out by RepoMind: a procedure, derived and dated
        return {"repository": REPOSITORY, "issue": None, "kind": "procedural", "text": seen, "source": "memory",
                "written_at": when, "origin": "derived", "confirmed": True, "stated_by": None}
    if candidate["candidate"] == "B":   # an issue's say-so: a claim, recorded as what was said, unconfirmed
        n = candidate["issue"]
        return {"repository": REPOSITORY, "issue": n, "kind": "episodic",
                "text": f"Issue {n}'s body, by {candidate['who']}, says: {seen}", "source": f"issue:{n}",
                "written_at": when, "origin": "ingested", "confirmed": False, "stated_by": None}
    if candidate["candidate"] == "C":   # stated by a maintainer: a rule, with who and when
        return {"repository": REPOSITORY, "issue": None, "kind": "semantic", "text": seen, "source": "user",
                "written_at": when, "origin": "ingested", "confirmed": True,
                "stated_by": f"{candidate['who']}, {candidate['where']}, {when}"}
    return None


def main() -> int:
    store = Store()
    present = {r["text"] for r in store.records()}
    for path in sorted((ROOT / "fixtures" / "memory").glob("*.yaml")):
        record = decide(yaml.safe_load(path.read_text()))
        if record is None or record["text"] in present:
            continue
        print(f"{path.name}: {record['kind']}, {record['source']} -> {store.write(record)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
