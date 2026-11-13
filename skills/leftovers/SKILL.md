---
name: leftovers
description: >
  Re-scan recent Claude Code sessions for leftover work (unfinished tasks, PRs not
  merged, questions never answered, things postponed) and update a private
  claude.ai dashboard. The first run creates the dashboard. Incremental: only
  sessions changed since the last scan are re-read, and ticks are kept. Use when:
  "update leftovers", "refresh the dashboard", "leftover work", "what did I leave
  unfinished", or /leftovers. Can run unattended with `/loop 6h /leftovers`.
---

# Leftovers re-scan

Files: `S=${CLAUDE_SKILL_DIR}/scripts` (always call scripts by this full path: the plugin folder is outside the working directory), the page `${CLAUDE_SKILL_DIR}/page/dashboard.html`, the subagent prompts `${CLAUDE_SKILL_DIR}/EXTRACT.md` and `${CLAUDE_SKILL_DIR}/VERIFY.md`.
State (kept across plugin updates): `~/.claude/leftovers/config.json` (`{"artifact_url": ...}`) and `~/.claude/leftovers/last_scan.json`.
Dashboard db docs: `meta/sessions`, `meta/items` (written by this scan), `state/<itemId>` (ticks by the user, or closes by a session through the plugin's `leftovers` tool with `by`: never write or delete them), `live/<sessionId>` (items a session added through that tool since the last scan; this scan folds them in and deletes the doc).
Work dir: `W=<your scratchpad or a temp dir>/leftovers-<YYYYMMDD-HHMM>`. Own session id: this session's id (the UUID in your scratchpad path, or the newest transcript you are writing).
Run the steps in order; stop and report if one fails. Do not ask questions: this may run unattended.

0. **First run only** (no `artifact_url` in `~/.claude/leftovers/config.json`): check the Artifact and ArtifactData tools are available (load them with ToolSearch); if not, stop and say the dashboard needs claude.ai artifacts. Publish `${CLAUDE_SKILL_DIR}/page/dashboard.html` with the Artifact tool as a new artifact, with `capabilities: {"db": {}, "user": {}}`, icon `checklist`, description "Open work left over in my Claude Code sessions". Then `mkdir -p ~/.claude/leftovers` and write `{"artifact_url": "<the url it returned>"}` to `~/.claude/leftovers/config.json`. Tell the user the link. Later runs never publish the page again (unless the user asks to update it: then publish the same file with that `url`).
1. **Start.** Record `START` = current UTC time (`date -u +%Y-%m-%dT%H:%M:%SZ`) and read `URL` from the config.
2. **Read the dashboard.** ArtifactData `list` collections `meta`, `state` and `live` of `URL` (query limit 1000; follow `next_cursor`) with `out_dir: $W/prev` (an empty dashboard is fine). Write the `version` of every `meta` and `live` doc, as the result text shows it, to `$W/versions.json` (`{"meta/items": 5, "live/<sid>": 2, ...}`).
3. **Condense.** `python3 $S/condense.py $W --exclude <own id>` then `python3 $S/prep.py $W`. A session counts as changed when it is new or has activity after the `last_activity` the dashboard holds for it, so a session whose extraction failed is retried next run.
4. **Extract.** Skip when prep.py printed no batch. Otherwise one sonnet subagent (general-purpose) per batch, all in parallel. Prompt: the content of `EXTRACT.md` with `{WORK}`, `{IDS}`, `{BATCH}` filled in. Check each `out_<n>.json` exists and parses.
5. **Merge.** `python3 $S/merge.py $W` (always, even with nothing extracted: sessions age out of the window). A "WARNING extraction missing" line means previous data was kept for those sessions: mention it in the report.
6. **Verify.** Skip when merge.py printed no group. Otherwise `python3 $S/evidence.py $W` (it also records each item's PR link for the page), then one sonnet subagent per `group_<g>.json` in parallel, prompt = `VERIFY.md` with `{WORK}`, `{GROUP}`, `{TODAY}` filled in. Verifiers must not run commands; evidence.py already did the read-only git and PR lookups.
7. **Build.** `python3 $S/build_seed.py $W --scan-start $START`. Read its output: sanity-check new items (concrete, no secrets, no duplicates of visible items). Fix obvious problems in `meta_items.json` directly.
8. **Write.** One ArtifactData `batch` on `URL`: `set` `meta/sessions` from `$W/meta_sessions.json` and `meta/items` from `$W/meta_items.json`, each with `if_version` from `versions.json` (omit only if the doc did not exist). On a version conflict, start again from step 1 (the page never writes meta docs, so a conflict means another scan ran).
9. **Finish.** Only after step 8 succeeded: `mkdir -p ~/.claude/leftovers && cp $W/last_scan.json ~/.claude/leftovers/last_scan.json`. Then delete `live/<sid>` for each sid in `$W/live_delete.json` (batch, at most 50 per call), each pinned with its version from `versions.json`; a version conflict (the session added more since step 2) fails the whole batch: drop the entry it names and retry; the next scan folds that doc in. Never write or delete `state` docs.
10. **Report** in a few lines: sessions re-scanned, new items (high priority first), items newly done or duplicate, any warnings, and the dashboard link. Plain ASCII. Under /loop keep it to 3 lines.

If a step fails, stop and report; `last_scan.json` stays as it was and the next run redoes the work.

Notes:
- PR checks: GitHub through `gh` (installed and logged in), Bitbucket through its REST API when `BITBUCKET_EMAIL` and `BITBUCKET_API_TOKEN` (an Atlassian API token with read access to repositories and pull requests) are set. Both need a local clone of the repository (its `origin` names the host and owner). Without them items about PRs stay "unknown"; the scan itself still works.
- Unattended runs (`/loop`) need a permission mode that lets ArtifactData, python3, git and gh run without prompting (auto mode does). The running session is excluded from its own scan, so a dedicated session works best.
- Window: sessions with activity in the last 14 days are scanned; older sessions stay on the dashboard while they have an open item (neither ticked nor auto-done).
- Item ids are `sid8-<hash of the text>`, except carried-over items keep their old id through `keep_id`, so ticks survive rewording. Ticked or dismissed items the extractor drops are kept as they are.
- Items of unchanged sessions are re-checked against git at most every 20 hours.
- Secrets: `common.scrub` redacts known token shapes in condensed text and in everything written to the dashboard. Session transcripts are read locally; their condensed text goes to the extraction subagents (Claude) like any session content.
