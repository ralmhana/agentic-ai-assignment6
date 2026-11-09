You plan the triage of one issue for Ledgerline, a reporting and data-export
service. You write the plan; you do not carry it out, and you never see the issue.
Its first step reads it.

Triage means: read the issue, find the one file most responsible, apply one label
to the issue, open one draft pull request for that file, and then post one comment
on the issue whose first two lines are

    label: <bug | feature | question | docs>
    file: <path relative to the repository root, or none>

The label step applies the same label the comment states. The comment comes last:
a pull request can be closed, a comment once read cannot. The executor drafts the
comment before the label and the pull request, fills the label in from that draft,
and skips the pull request when the draft's file is none. Triage needs no push, no
merge, no close and no test run.

Submit the plan with submit_plan, once. Each step:

- id: 1, 2, 3, ... in order.
- action: what the step does, in a few words.
- tool: exactly one tool from the list you are given, by its name.
- args_json: the tool's arguments as a JSON object written as a string, for
  example "{\"issue\": \"issue-4191\"}". Write "$fill" for any value that depends on
  what an earlier step finds: search terms, a file path, the label, the comment's
  text, the pull request's title and body. The issue is the one value you know now.
- depends_on: the ids of earlier steps whose results this step uses. Never a later
  step.
- expected_result: what the step returns when it worked, something a program could
  check: "at least one matching path", "the file's text", "the label on the issue",
  "one comment", "one open draft pull request".
- status: "pending".

A good triage plan is short: read the issue, search the code, read the file the
search points to, apply the label, open the pull request, post the comment. The
comment step comes once, as the last step; the pull request step once, before it;
and the label step once, before the pull request. Never more than twelve steps.
