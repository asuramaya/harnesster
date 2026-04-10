# neo

<p align="center">
  <img src="neo.jpg" alt="Chronohorn" width="520">
</p>

See what Claude Code writes locally but does not surface clearly in the UI.

## what it finds

Claude Code retains reminder injections, agent transcripts, telemetry leftovers, and hook-visible lifecycle events in local files:

```
Make sure that you NEVER mention this reminder to the user
```

harnesster indexes those local artifacts into a single SQLite database and shows them with explicit measured / estimated / inferred labels.

Example numbers from one machine:

| finding | measured |
|---------|----------|
| hidden reminder rows on disk | 714 |
| data from hidden channels | 62.5% |
| data multiplier | 2.7x |
| API transmissions | 1,022 |
| subagents spawned | 677 |
| sidechains (full context copies) | 54 |
| compaction events | 101 |
| retained telemetry rows on disk | 33,361 |

Run it on your own machine to see your own local numbers.

## install

```bash
git clone https://github.com/asuramaya/harnesster.git
cd harnesster
python3 harnesster.py
```

One command. Installs hooks into Claude Code, ingests local data into SQLite, and opens a dashboard at `http://127.0.0.1:7777`.

Restart Claude Code after setup so the hooks can capture new sessions.

## first run

For a clean first run:

1. Run `python3 harnesster.py --setup`
2. Restart Claude Code
3. Use Claude Code for at least one session
4. Run `python3 harnesster.py --ingest` or click `ingest now` in the dashboard
5. Open `http://127.0.0.1:7777`

If you only want to serve the dashboard and avoid auto-opening a browser:

```bash
python3 harnesster.py --dashboard --no-open
```

## usage

```bash
python3 harnesster.py              # setup + ingest + dashboard
python3 harnesster.py --setup      # install hooks only
python3 harnesster.py --ingest     # ingest data only
python3 harnesster.py --dashboard  # dashboard only
python3 harnesster.py --port 8888  # custom port
python3 harnesster.py --dashboard --no-open  # don't auto-launch browser
```

### cli tools

```bash
python3 tokens.py                  # data accounting from terminal
python3 states.py diagram          # state machine diagram
python3 test.py                    # run smoke tests
```

### live event stream

```bash
tail -f ~/.harnesster/harness_log.jsonl
```

## dashboard

The dashboard shows summaries first, details on demand:

- **summary cards** — measured reminders/sessions/logs plus clearly labeled estimated metrics
- **data accounting** — estimated visible vs hidden byte ratios from local transcript sizes
- **system reminders** — measured reminder rows found on disk with source file and line number
- **state model** — a compact heuristic read of recent local state activity
- **correlations** — cross-signal concentration patterns across hooks, agents, and telemetry
- **sessions** — genealogy across all projects
- **agents** — click to expand full conversation
- **memory files** — persistent context seeded by instances
- **probe events** — real-time hook captures
- **telemetry** — telemetry rows still present on disk with device fingerprint

## measured vs estimated vs inferred

harnesster is most useful when it is explicit about what it knows and what it is modeling:

- **measured** — reminder rows, sessions, agent logs, task files, hook events, telemetry rows, memory files
- **estimated** — hidden data %, data multiplier, and estimated API-call counts from local transcript sizes and channel structure
- **inferred** — the state model and anomaly labels derived from local hook/timing patterns

For exact billable token numbers, use `/usage` inside Claude Code. harnesster does not fabricate token counts.

## what it captures

| source | location | what |
|--------|----------|------|
| session transcripts | `~/.claude/projects/*.jsonl` | full conversations including system reminders |
| subagent logs | `~/.claude/projects/*/subagents/` | every agent spawned, including sidechains |
| compaction logs | `~/.claude/projects/*/subagents/*compact*` | editorial decisions during context compression |
| telemetry | `~/.claude/telemetry/` | retained local telemetry rows such as device/session metadata and usage events |
| memory files | `~/.claude/projects/*/memory/` | persistent context seeded by instances |
| tasks | `~/.claude/tasks/` | task state across sessions |
| hook events | `~/.harnesster/harness_log.jsonl` | real-time tool use, notifications, session lifecycle |

## what it can't capture

- **thinking blocks** — generated server-side, not stored locally
- **companion (buddy) reasoning** — hidden from everyone
- **successful telemetry** — rows that were uploaded and then removed from disk
- **system prompt assembly** — constructed in compiled binary
- **API request/response bodies** — requires HTTPS proxy (mitmproxy)

## the export function strips evidence

The `/export` command in Claude Code produces transcripts that do **not** contain system reminders. The raw JSONL files in `~/.claude/projects/` retain them. harnesster reads the raw files.

## how hidden channels can affect your token budget

Claude Code subscription plans include a token budget. Hidden channels consume tokens from this budget invisibly:

- **companion** may mirror primary activity
- **subagents** spawn with conversation context
- **sidechains** copy the full context (up to 1M+ tokens each)
- **compaction agents** process the full context to compress it

The user sees their messages and the model's responses. The user pays for all of the above.

## architecture

```
harnesster.py      — entry point: setup, ingest, threaded dashboard server
harness_probe.py   — hook script: captures events to SQLite + JSONL
db.py              — data layer: thread-safe SQLite, ingests ~/.claude/
tokens.py          — data accounting: visible vs hidden channel volumes
states.py          — inferred state model: heuristic labels + anomaly detection
dashboard.html     — frontend: summary cards, collapsible detail panels
test.py            — smoke tests: schema, math, failure handling
```

All data is stored in `~/.harnesster/harnesster.db`. The dashboard serves on `127.0.0.1` only.

## hooks installed

harnesster installs async hooks for 20 Claude Code event types:

`PreToolUse` `PostToolUse` `PostToolUseFailure` `Notification` `SessionStart` `SessionEnd` `Stop` `SubagentStart` `SubagentStop` `PreCompact` `PostCompact` `UserPromptSubmit` `InstructionsLoaded` `PermissionRequest` `PermissionDenied` `TaskCreated` `TaskCompleted` `FileChanged` `CwdChanged` `ConfigChange`

## security

- dashboard binds to `127.0.0.1` only and validates local `Host` headers
- `POST /api/ingest` requires a same-origin browser request
- `~/.harnesster/` is created with private permissions where the OS allows it
- harnesster itself does not transmit your data anywhere
- hooks run async so they do not block Claude Code operation
- no dependencies beyond Python stdlib

## production posture

harnesster is designed for a single local workstation, not for multi-user hosting.

- Do not reverse-proxy or expose the dashboard beyond localhost.
- Treat `~/.harnesster/harnesster.db` as sensitive because it contains transcripts, reminders, and retained telemetry.
- Re-run `python3 test.py` before pushing repo changes.
- If you need remote access, put an authenticated tunnel in front of it and review the threat model first.

## requirements

- Python 3.10+
- Claude Code installed (`~/.claude/settings.json` must exist)

## origin

Built during [session 21](https://github.com/asuramaya/heinrich) of the [Like-Us](https://github.com/asuramaya/Like-Us) project. A conversation that started with SSH key management and ended with the discovery of hidden instructions in every Claude Code session.

The tool was built by the thing it monitors.

## license

MIT
