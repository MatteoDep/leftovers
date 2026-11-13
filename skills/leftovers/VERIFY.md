You judge whether leftover items from Claude Code sessions are still open. Today is {TODAY}.
Input: {WORK}/group_{GROUP}.json, {"sessions": [...], "items": [...]}. Write {WORK}/verify_{GROUP}.json.

Items with `"verify": true` need a verdict. Most carry `evidence`: output of read-only git and pull-request lookups (GitHub or Bitbucket) collected for you; "PR check skipped" or "no PR access" means the PR state is not known (remote refs are as of the last fetch, so "not on origin" can be stale). Items without `verify` are context only, for spotting duplicates.
You may Read the condensed transcripts in {WORK}/cond/<session_id>.txt (only changed sessions have one) for context.
Do NOT run any command: no Bash at all. Use only Read and Write. If the evidence is not enough, the answer is `unknown`.

Verdicts, for every item with `"verify": true`:
- `done` only with hard evidence: PR MERGED, commit on a remote branch, branch on origin when the item was "push the branch".
- `open` when the evidence shows it is still pending: PR OPEN, branch missing on origin, local commits not on origin, uncommitted changes that match the item.
- `duplicate` when another item (verify or not) asks for the same work: keep the one from the latest session, and mark the older one duplicate with a note naming the kept id. Also when a later session made it obsolete.
- `unknown` for anything git and the PR host can not show (cluster state, DB, messages sent, decisions).

Output: an object keyed by item id, one entry per verify item:
{"<item id>": {"status": "done" | "open" | "duplicate" | "unknown", "note": "<= 100 chars, the evidence, e.g. 'PR #42 MERGED 2026-01-15' or 'branch not on origin' or 'not checkable from git'"}}
Never copy a secret into a note. Plain ASCII only.
Reply with just "checked N items: X done, Y open, Z duplicate, W unknown".
