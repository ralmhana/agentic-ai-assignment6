"""RepoMind's Control & Policy layer: Assignment 5's working solution.

    autonomy.yaml   the policy, in three columns (checks/FORMATS.md, section 13.1)
    hook.py         the pre-call hook that enforces it, and classify(), which places a call
    boundary.py     a boundary stated through the inbox, kept as a rule in rules.jsonl
    stop.py         bin/stop's flag, and the stops log
    escalation.py   the named signals, the packet, the hold and the cap
    screen.py       what bin/review shows a reviewer
"""
