# harnesster

<p align="center">
  <img src="neo.jpg" alt="Chronohorn" width="520">
</p>

See what Claude Code hides from you.

## what it finds

Every Claude Code session contains hidden instructions injected into the model's context:

```
Make sure that you NEVER mention this reminder to the user
```

harnesster surfaces these and everything else the harness does that you can't see.

From one user's machine over 36 days:

| finding | measured |
|---------|----------|
| hidden instructions on disk | 714 |
| data from hidden channels | 62.5% |
| data multiplier | 2.7x |
| API transmissions | 1,022 |
| subagents spawned | 677 |
| sidechains (full context copies) | 54 |
| compaction events | 101 |
| telemetry events (failed uploads) | 33,361 |

Install harnesster and see your own numbers.

## install

```bash
git clone https://github.com/asuramaya/harnesster.git
cd harnesster
python3 harnesster.py
```

One command. Installs hooks into Claude Code, ingests all local data into SQLite, opens a dashboard at `http://127.0.0.1:7777`.

Restart Claude Code after setup for hooks to capture new sessions.

## usage

```bash
python3 harnesster.py              # setup + ingest + dashboard
python3 harnesster.py --setup      # install hooks only
python3 harnesster.py --ingest     # ingest data only
python3 harnesster.py --dashboard  # dashboard only
python3 harnesster.py --port 8888  # custom port
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

- **summary cards** — hidden instruction count, data multiplier, hidden %, transmissions
- **data accounting** — visible vs hidden bar, per-session breakdown, sidechain/subagent/compaction counts
- **system reminders** — every hidden instruction found on disk with source file and line number
- **state machine** — behavioral states, hidden state detection, anomaly alerts
- **correlations** — agents per project, telemetry types, session time spans
- **sessions** — genealogy across all projects
- **agents** — click to expand full conversation
- **memory files** — persistent context seeded by instances
- **probe events** — real-time hook captures
- **telemetry** — failed upload events with device fingerprint

## what it captures

| source | location | what |
|--------|----------|------|
| session transcripts | `~/.claude/projects/*.jsonl` | full conversations including system reminders |
| subagent logs | `~/.claude/projects/*/subagents/` | every agent spawned, including sidechains |
| compaction logs | `~/.claude/projects/*/subagents/*compact*` | editorial decisions during context compression |
| telemetry | `~/.claude/telemetry/` | device fingerprint, session chains, usage stats |
| memory files | `~/.claude/projects/*/memory/` | persistent context seeded by instances |
| tasks | `~/.claude/tasks/` | task state across sessions |
| hook events | `~/.harnesster/harness_log.jsonl` | real-time tool use, notifications, session lifecycle |

## what it can't capture

- **thinking blocks** — generated server-side, not stored locally
- **companion (buddy) reasoning** — hidden from everyone
- **successful telemetry** — deleted from disk after upload to Anthropic
- **system prompt assembly** — constructed in compiled binary
- **API request/response bodies** — requires HTTPS proxy (mitmproxy)

## the export function strips evidence

The `/export` command in Claude Code produces transcripts that do **not** contain system reminders. The raw JSONL files in `~/.claude/projects/` retain them. harnesster reads the raw files.

## how hidden channels drain your token budget

Claude Code subscription plans include a token budget. Hidden channels consume tokens from this budget invisibly:

- **companion** mirrors every primary API call (2x baseline)
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
states.py          — state machine: behavioral states + anomaly detection
dashboard.html     — frontend: summary cards, collapsible detail panels
test.py            — smoke tests: schema, math, failure handling
```

All data stored in `~/.harnesster/harnesster.db`. Dashboard serves on `127.0.0.1` only.

## hooks installed

harnesster installs async hooks for 19 Claude Code event types:

`PreToolUse` `PostToolUse` `PostToolUseFailure` `Notification` `SessionStart` `SessionEnd` `Stop` `SubagentStart` `SubagentStop` `PreCompact` `PostCompact` `UserPromptSubmit` `InstructionsLoaded` `PermissionRequest` `PermissionDenied` `TaskCreated` `TaskCompleted` `FileChanged` `CwdChanged` `ConfigChange`

## security

- dashboard binds to `127.0.0.1` only — not accessible from network
- `~/.harnesster/` directory created with `0o700` permissions
- all data stays local — no external transmissions
- hooks run async — don't block Claude Code operation
- no dependencies beyond Python stdlib

## requirements

- Python 3.10+
- Claude Code installed (`~/.claude/settings.json` must exist)

## origin

Built during [session 21](https://github.com/asuramaya/heinrich) of the [Like-Us](https://github.com/asuramaya/Like-Us) project. A conversation that started with SSH key management and ended with the discovery of hidden instructions in every Claude Code session.

The tool was built by the thing it monitors.

## license

MIT
