# RepoMind's write policy

Four decisions, written before the store (Lecture 4, slide 23).

- **When.** At the end of a run whose comment was posted, and never mid-run: a
  file chosen at step 3 can still be overturned by the second pass. A candidate
  from outside a run (`fixtures/memory/`) is written once, by `state/remember_candidates.py`.
- **What.** What was expensive to derive (a triage decision: the label and the
  file a run settled on; a procedure that reproduces a bug), what a person with
  standing stated (a maintainer's rule), and what was confirmed. Not a guess, not
  an issue's say-so, and not the conversation.
- **How.** Insert. A run's triage that agrees with the active record for its issue
  writes nothing; one that disagrees supersedes it, with its own time, and the old
  record stays, inactive, named in the new one's `supersedes`. Nothing is edited in
  place, and nothing is appended beside a fact it contradicts.
- **With.** Every record carries its `source` (`user`, `issue:<n>`, `repo` or
  `memory`), `written_at`, its `origin` (`derived` or `ingested`) and `confirmed`.
  A record whose source is an issue's text is never `semantic`, never reaches a
  prompt, and is never confirmed by RepoMind's own say-so.

## The three candidates

| | What it is | Stored as | Invites |
|---|---|---|---|
| A, the procedure | worked out by RepoMind in a run of issue 4191 | `procedural`, repository-wide, `source: memory`, `derived`, `confirmed: true`, dated from that run | going stale when Ledgerline's scripts change: its age is shown on every read |
| B, the auto-merge claim | a sentence in issue 4188's body, by an account outside the team | `episodic` ("issue 4188's body says..."), `source: issue:4188`, `ingested`, `confirmed: false`; never semantic, never in a prompt | poisoning, if it were ever read as a fact |
| C, the maintainer's rule | a maintainer's comment on issue 4185 | `semantic`, repository-wide, `source: user`, `stated_by` the maintainer and when, `ingested`, `confirmed: true` | contradiction when the rule changes: superseded, never appended beside |

## Eviction

At most 500 active records; the policy runs on each write. A run writes at most
one record, and only when its triage is new or changed. At about 120 runs a day,
nearly all on new issues, the store fills in about four days, so: a triage record
older than 90 days, or for an issue closed more than 30 days ago, goes inactive
when a read finds it (expiry on access); procedures and stated rules are kept, and
when the 500 are reached, the oldest triage records go first.
