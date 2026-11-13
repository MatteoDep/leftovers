# Leftovers

Find the work you left unfinished across your AI coding sessions.
It currently supports Claude Code; other harnesses may follow.
`/leftovers` reads your recent session transcripts, pulls out what was still open at the end of each one, and keeps it in a private dashboard on claude.ai.
Items about branches and pull requests are checked against git and GitHub or Bitbucket, and the ones already finished are ticked off automatically.

## What you get

- A private claude.ai dashboard with your open items, grouped by project and session.
  Each item shows its priority, a link to its PR when there is one, and the command to resume its session.
  You can tick items done or dismiss them, and your ticks are kept across scans.
- The `/leftovers` skill.
  Its first run creates the dashboard.
  Later runs re-read only the sessions that changed.
  Run it by hand, or leave it running in a spare session with `/loop 6h /leftovers`.
- A `leftovers` tool in every session.
  Claude closes an item when it finishes the work, and adds one when a turn ends with work left for later.
  Closing an item that belongs to another session asks you first.
- A reminder at session start when the last scan is more than a day old.

## Install

From a shell:

```
claude plugin install leftovers --marketplace MatteoDep/leftovers --scope user
```

Or inside a Claude Code session:

```
/plugin marketplace add MatteoDep/leftovers
/plugin install leftovers@leftovers
```

Then run `/leftovers` once to create your dashboard; Claude replies with its link.

## Requirements

- Claude Code with claude.ai artifacts available on your account (the dashboard is an artifact).
- Linux or macOS, with `python3` and `git`.
- Optional, for pull-request checks and links:
  - GitHub: the `gh` CLI, logged in (`gh auth login`).
  - Bitbucket: set `BITBUCKET_EMAIL` (your Atlassian account email) and `BITBUCKET_API_TOKEN` (an Atlassian API token with read access to repositories and pull requests).

  PR checks need a local clone of the repository, because its `origin` remote tells the scan which host and owner to ask.
  Without these the scan still works, and PR items stay unchecked.

## Privacy

- Transcripts are read on your machine from `~/.claude/projects`.
  The scan sends condensed transcript text to Claude subagents to extract the leftovers, as your sessions already send their content to Claude.
- Known token shapes (GitHub, GitLab, AWS, Slack, private keys, `password=...`) are redacted before anything reaches the dashboard.
- Git and PR checks are read-only, with no fetch, push or write calls.
- The dashboard is private to you unless you share it from its Share menu.

## Unattended runs

`/loop 6h /leftovers` in a spare session keeps the dashboard current.
That session needs a permission mode that lets it run `python3`, `git`, `gh` and the artifact tools without asking; auto mode works.
The session running the scan is left out of its own results, so a separate session works best.

## Files

- `skills/leftovers/`: the skill, its scripts and the dashboard page.
- `hooks/`: the `leftovers` tool and the reminder (a Claude Code plugin hooks module).
- Your state lives in `~/.claude/leftovers/` (the dashboard link and the time of the last scan), so plugin updates keep it.

## License

MIT
