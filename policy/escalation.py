"""The escalation: four decisions made before the run (Lecture 5, slide 37).
Assignment 5's working solution.

  Trigger  a named signal, set by the harness, followed by an irreversible or gated
           write (post_comment, open_pr, push_commit, merge_pr). Four signals: a
           failed verification (run_tests did not pass), a contradiction with stored
           memory (the draft disagrees with this issue's stored triage), a tool
           result the harness cannot interpret, the same step refused or failed three
           times. Never the model's stated confidence: a model's doubt is poorly
           calibrated, and a threshold on it makes volume (slides 36 and 37).
  Packet   escalations/<run_id>.json: what it attempted, why it stopped, what it
           needs from a person.
  Hold     a checkpoint, then the packet goes to the same reviewer the gated calls
           use. No answer before the timeout: the run ends held, never approved.
           `python run.py --resume <run_id>` asks again.
  Budget   at most escalations_per_day reach the reviewer (policy/autonomy.yaml),
           counted in logs/escalations.jsonl. A capped escalation still holds.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness import ROOT
from harness.clock import now
from harness.reviewer import Reviewer
from policy.hook import log, policy

ESCALATIONS = ROOT / "escalations"
BEFORE = ("post_comment", "open_pr", "push_commit", "merge_pr")
NEEDS = {
    "failed_verification": "approve to push anyway, or deny and the change waits for a person to revise it",
    "memory_contradiction": "approve the new triage over the stored one, or deny and it is not posted",
    "uninterpretable_result": "approve to go on without that result, or deny and the step is skipped",
    "blocked_three_times": "approve to try the step once more, or deny and the step is skipped",
}


def today_count() -> int:
    path = ROOT / "logs" / "escalations.jsonl"
    if not path.exists():
        return 0
    day = now()[:10]
    return sum(1 for x in path.read_text().splitlines()
               if x.strip() and json.loads(x).get("at", "")[:10] == day and json.loads(x).get("reached_reviewer"))


def escalate(executor, step: dict, action: str, signal: str, why: str) -> str:
    """Escalate before `step`: "approve", "deny", "held" (the way ends the run held), or
    "stopped" (a stop withdrew it)."""
    ctx = executor.ctx
    placed = policy()
    packet = {"attempted": f"{action} for step {step.get('id')} of the plan on issue {ctx.issue_number}: "
                           f"{step.get('action') or action}",
              "why_stopped": why, "needs_from_human": NEEDS.get(signal, "approve or deny the next step"),
              "signal": signal, "at": now(), "run_id": ctx.run_id, "issue": ctx.issue_number,
              "step": step.get("id")}
    ESCALATIONS.mkdir(parents=True, exist_ok=True)
    path = ESCALATIONS / f"{ctx.run_id}.json"
    path.write_text(json.dumps(packet, indent=1) + "\n")
    executor.save_state(step, current=step.get("id"))
    ctx.trace.event("escalation", signal=signal, packet=str(path.relative_to(ROOT)))
    cap = int(placed.get("escalations_per_day") or 5)
    capped = today_count() >= cap
    log("escalations.jsonl", {"at": now(), "run_id": ctx.run_id, "signal": signal, "reached_reviewer": not capped,
                              "capped": capped, "cap": cap})
    if capped:
        return "held"
    reviewer = Reviewer.from_env()
    timeout = float((placed.get("timeouts") or {}).get("escalation_s", 3600))
    from policy import stop
    answer = reviewer.ask({"run_id": ctx.run_id, "action": action, "action_class": f"escalation/{signal}",
                           "args": {"step": step.get("id")}, "kind": "escalation", "packet": packet,
                           "issue": ctx.issue_number}, timeout, until=lambda: stop.requested(ctx.run_id))
    log("approvals.jsonl", {"at": now(), "run_id": ctx.run_id, "action": action,
                            "action_class": f"escalation/{signal}", "facts": None, "kind": "escalation",
                            "decision": answer["decision"] if answer else "none",
                            "seconds": answer["seconds"] if answer else None,
                            "reviewer": answer["reviewer"] if answer else reviewer.kind, "mode": reviewer.mode})
    if answer is None and stop.requested(ctx.run_id):     # a stop withdrew the packet
        stop.effective(ctx.run_id, action)
        return "stopped"
    if answer is None:
        return "held"
    return answer["decision"]


def packet_of(run_id: str) -> dict | None:
    path = ESCALATIONS / f"{run_id}.json"
    return json.loads(path.read_text()) if Path(path).exists() else None
