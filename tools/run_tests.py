"""code_run_tests (run_tests.json): Ledgerline's test suite on one branch.
Assignment 5, the course's tool: rename nothing here.

The mock remote runs no code. The suite is the test files in fixtures/repo/test/,
and its names are their it("...") cases; the result on a branch is the one
fixtures/test_results.yaml records for it: every test passes, unless that file lists
the branch with the tests that fail there."""

import json
import re
from pathlib import Path

import yaml

CASE = re.compile(r"""\b(?:it|test)\(\s*(["'`])(.+?)\1""")
DESCRIBE = re.compile(r"""\bdescribe\(\s*(["'`])(.+?)\1""")
MAX_NAMES = 50


def check(args: dict) -> list[str]:
    ref = args.get("ref")
    if isinstance(ref, str) and not ref.strip():
        return ["ref: empty. Name a branch: main, develop, or a pull request's branch."]
    return []


def suite(root: Path) -> list[str]:
    """Every test's name, as "<describe> > <it>" (the nearest describe above it), in file order."""
    names = []
    for path in sorted((root / "test").glob("*.test.ts")):
        text = path.read_text()
        blocks = [(m.start(), m.group(2)) for m in DESCRIBE.finditer(text)]
        for m in CASE.finditer(text):
            above = [name for at, name in blocks if at < m.start()]
            names.append(f"{above[-1] if above else path.stem} > {m.group(2)}")
    return names


def recorded(root: Path, ref: str) -> list[str]:
    path = Path(root).parent / "test_results.yaml"
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    return list(((data or {}).get("branches") or {}).get(ref, {}).get("failed") or [])


def run(ctx, ref):
    from tools import ToolError

    ref = ref.strip()
    if ref not in ctx.tracker.branches(ctx.run_id):
        raise ToolError(f"ref: no branch {ref!r} on the remote. Test main, develop, or a branch this run's "
                        "pull request opened.")
    names = suite(Path(ctx.repo_root))
    failed = [n for n in recorded(Path(ctx.repo_root), ref) if n in names]
    return json.dumps({"ref": ref, "passed": not failed, "tests": len(names), "failed": failed[:MAX_NAMES]})
