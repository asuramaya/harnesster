# Security Best Practices Report

## Executive Summary

No unresolved critical findings remain for the current local-only deployment model.

Before a repo push, I fixed the highest-value hardening gaps:

1. The dashboard server now validates local `Host` headers and keeps same-origin protection on the ingest endpoint.
2. Claude settings writes are now validated and atomically replaced instead of being overwritten in place.
3. Ingest is serialized, and the correlations API no longer requires the frontend to pull an oversized hook timeline just to compute totals.
4. Token accounting now parses real reminder payloads and follows the same no-symlink posture as the main ingest path.
5. README guidance is more explicit about what is measured, what is only local, and what is not suitable for remote exposure.

## Fixed Findings

### High

#### H-01: Local dashboard accepted arbitrary `Host` headers

Impact: without host validation, a localhost-only bind still left unnecessary room for hostile local routing or DNS-rebinding-style abuse.

Fixed in:
- [harnesster.py](/Users/asuramaya/harnesster/harnesster.py#L242)
- [harnesster.py](/Users/asuramaya/harnesster/harnesster.py#L495)
- [harnesster.py](/Users/asuramaya/harnesster/harnesster.py#L593)

What changed:
- Every request now validates the `Host` header against the expected local hostnames for the current port.
- `POST /api/ingest` still requires same-origin `Origin` or `Referer`.
- Additional response headers were added to keep the browser surface tighter.

### Medium

#### M-01: `settings.json` rewrites were not atomic

Impact: an interrupted write could leave Claude Code settings partially written or corrupted.

Fixed in:
- [harnesster.py](/Users/asuramaya/harnesster/harnesster.py#L106)
- [harnesster.py](/Users/asuramaya/harnesster/harnesster.py#L170)

What changed:
- `settings.json` is now validated before mutation.
- Hook installation writes to a temporary file, fsyncs it, and uses `os.replace` for atomic replacement.

#### M-02: Ingest could run concurrently

Impact: concurrent ingests could compete for SQLite and produce avoidable latency or unstable request behavior.

Fixed in:
- [db.py](/Users/asuramaya/harnesster/db.py#L31)
- [db.py](/Users/asuramaya/harnesster/db.py#L715)

What changed:
- Full ingest now runs under a process-local lock so only one ingest executes at a time.

#### M-03: Correlations API pushed more hook timeline data than the dashboard needed

Impact: larger payloads increase latency and make the UI more fragile as local history grows.

Fixed in:
- [harnesster.py](/Users/asuramaya/harnesster/harnesster.py#L370)
- [dashboard.html](/Users/asuramaya/harnesster/dashboard.html#L1070)

What changed:
- The API now returns bounded `hook_timeline` data plus a summarized `hook_totals` rollup.
- The dashboard prefers the summarized totals path.

### Low

#### L-01: Token accounting reminder detection lagged behind the main ingest parser

Impact: session-level reminder counts in token accounting could under-report real reminder activity.

Fixed in:
- [tokens.py](/Users/asuramaya/harnesster/tokens.py#L16)
- [tokens.py](/Users/asuramaya/harnesster/tokens.py#L69)
- [tokens.py](/Users/asuramaya/harnesster/tokens.py#L139)

What changed:
- Token accounting now parses tagged and legacy reminder payloads instead of depending on the `NEVER mention` substring.
- File iteration now avoids symlinks, matching the hardened ingest path.

#### L-02: Repo hygiene did not ignore local scratch artifacts

Impact: local junk could leak into `git status` and make a push noisier than necessary.

Fixed in:
- [.gitignore](/Users/asuramaya/harnesster/.gitignore#L1)

What changed:
- Added ignores for `.pytest_cache/` and the local scratch file `local`.

## Residual Risks

### R-01: This is still a localhost workstation tool, not a hosted service

Relevant docs:
- [README.md](/Users/asuramaya/harnesster/README.md#L163)
- [README.md](/Users/asuramaya/harnesster/README.md#L172)

Notes:
- There is no authentication layer because the intended trust boundary is `127.0.0.1`.
- If someone later wants remote access, they should add an authenticated tunnel or reverse proxy and revisit the threat model.

### R-02: The local database is sensitive

Relevant docs:
- [README.md](/Users/asuramaya/harnesster/README.md#L155)
- [README.md](/Users/asuramaya/harnesster/README.md#L176)

Notes:
- `~/.harnesster/harnesster.db` contains transcripts, reminder rows, hook events, and retained telemetry.
- The code hardens file permissions where the OS allows it, but there is no encryption at rest.

### R-03: State and correlation views remain heuristic

Relevant docs:
- [README.md](/Users/asuramaya/harnesster/README.md#L98)
- [dashboard.html](/Users/asuramaya/harnesster/dashboard.html#L999)

Notes:
- The UI now labels these sections clearly, but they are still modelled interpretations of local artifacts, not direct proof of server-side behavior.

## Verification

Validated locally with:

- `python3 test.py`
- `python3 -m py_compile harnesster.py db.py states.py tokens.py harness_probe.py test.py`
- Live server checks for:
  - valid local `Host`
  - rejected unexpected `Host`
  - bounded correlations response including `hook_totals`
