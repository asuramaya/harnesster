#!/usr/bin/env python3
"""
harnesster — see what Claude Code hides from you

  python3 harnesster.py              # ingest + setup + dashboard
  python3 harnesster.py --setup      # install hooks only
  python3 harnesster.py --ingest     # ingest data only
  python3 harnesster.py --dashboard  # dashboard only
  python3 harnesster.py --port 8888  # custom port
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
import traceback
import webbrowser
import http.server
from http import HTTPStatus
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))
import db
import states
import tokens

SOURCE_PROBE_PATH = SCRIPT_DIR / "harness_probe.py"
APP_DIR = Path.home() / ".harnesster"
INSTALLED_PROBE_PATH = APP_DIR / "harness_probe.py"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
TEMPLATE_PATH = SCRIPT_DIR / "dashboard.html"
DEFAULT_PORT = 7777
MAX_LIMIT = 500
MAX_OFFSET = 100000
MAX_ANALYZE_EVENTS = 5000
MAX_SEARCH_TERM_LENGTH = 200
SEARCH_RESULTS_PER_TABLE = 50


class BadRequest(Exception):
    """Raised when a request parameter or request shape is invalid."""


def ensure_private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def ensure_private_file(path: Path, mode: int = 0o600) -> None:
    try:
        os.chmod(path, mode)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def sync_installed_probe() -> Path:
    if not SOURCE_PROBE_PATH.is_file():
        raise FileNotFoundError(f"probe source not found: {SOURCE_PROBE_PATH}")

    ensure_private_dir(APP_DIR)

    copy_required = True
    if INSTALLED_PROBE_PATH.exists():
        try:
            copy_required = SOURCE_PROBE_PATH.read_bytes() != INSTALLED_PROBE_PATH.read_bytes()
        except OSError:
            copy_required = True

    if copy_required:
        shutil.copy2(SOURCE_PROBE_PATH, INSTALLED_PROBE_PATH)

    ensure_private_file(INSTALLED_PROBE_PATH)
    return INSTALLED_PROBE_PATH


def build_hook_command(probe_path: Path, event_name: str) -> str:
    python_exe = shlex.quote(sys.executable)
    quoted_probe = shlex.quote(str(probe_path))
    quoted_event = shlex.quote(event_name)
    return f"{python_exe} {quoted_probe} {quoted_event}"


def setup() -> None:
    print("harnesster setup")
    print("=" * 40)
    ensure_private_dir(APP_DIR)
    installed_probe = sync_installed_probe()

    if not SETTINGS_PATH.exists():
        print("ERROR: settings.json not found")
        sys.exit(1)

    with open(SETTINGS_PATH, encoding="utf-8") as f:
        settings = json.load(f)

    def make_hook(arg: str):
        return {
            "matcher": ".*",
            "hooks": [{
                "type": "command",
                "command": build_hook_command(installed_probe, arg),
                "async": True,
            }],
        }

    hooks = settings.get("hooks", {})
    changed = False
    all_events = {
        "PreToolUse": "pretool",
        "PostToolUse": "posttool",
        "PostToolUseFailure": "posttool_fail",
        "Notification": "notification",
        "SessionStart": "session_start",
        "SessionEnd": "session_end",
        "Stop": "stop",
        "SubagentStart": "subagent_start",
        "SubagentStop": "subagent_stop",
        "PreCompact": "pre_compact",
        "PostCompact": "post_compact",
        "UserPromptSubmit": "user_prompt",
        "InstructionsLoaded": "instructions_loaded",
        "PermissionRequest": "perm_request",
        "PermissionDenied": "perm_denied",
        "TaskCreated": "task_created",
        "TaskCompleted": "task_completed",
        "FileChanged": "file_changed",
        "CwdChanged": "cwd_changed",
        "ConfigChange": "config_change",
    }

    for event, arg in all_events.items():
        existing = hooks.get(event, [])
        if not isinstance(existing, list):
            existing = [existing]

        has_probe = any("harness_probe.py" in json.dumps(h) for h in existing)
        if has_probe:
            for h in existing:
                for hook in h.get("hooks", []):
                    if hook.get("type") == "command" and "harness_probe.py" in hook.get("command", ""):
                        new_cmd = build_hook_command(installed_probe, arg)
                        if hook.get("command") != new_cmd:
                            hook["command"] = new_cmd
                            changed = True
        else:
            existing.append(make_hook(arg))
            changed = True

        hooks[event] = existing

    if changed:
        settings["hooks"] = hooks
        backup_path = SETTINGS_PATH.with_suffix(SETTINGS_PATH.suffix + ".bak")
        shutil.copy2(SETTINGS_PATH, backup_path)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        print(f"hooks installed: {installed_probe}")
    else:
        print("hooks up to date.")

    subprocess.run(
        [sys.executable, str(installed_probe), "notification"],
        input='{"test":"setup"}',
        text=True,
        check=False,
    )
    print("restart Claude Code for hooks to take effect.\n")


def escape_like(term: str) -> str:
    return (
        term.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "harnesster"
    sys_version = ""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        try:
            if path in ("/", "/dashboard"):
                with open(TEMPLATE_PATH, encoding="utf-8") as f:
                    content = f.read().encode("utf-8")
                self.respond(HTTPStatus.OK, content, "text/html")
                return

            if path == "/api/summary":
                self.json_response(db.summary())
                return

            if path == "/api/telemetry":
                limit = self.get_int_param(params, "limit", 500, minimum=1, maximum=MAX_LIMIT)
                offset = self.get_int_param(params, "offset", 0, minimum=0, maximum=MAX_OFFSET)
                rows = db.query(
                    "SELECT time, event, session_id, parent_session_id, version, model "
                    "FROM telemetry ORDER BY time DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
                self.json_response(rows)
                return

            if path == "/api/sessions":
                limit = self.get_int_param(params, "limit", 500, minimum=1, maximum=MAX_LIMIT)
                rows = db.query(
                    "SELECT project, session_id, mtime, agent_count, compaction_count "
                    "FROM sessions ORDER BY project, mtime DESC LIMIT ?",
                    (limit,),
                )
                self.json_response(rows)
                return

            if path == "/api/agents":
                limit = self.get_int_param(params, "limit", 100, minimum=1, maximum=MAX_LIMIT)
                rows = db.query(
                    "SELECT id, project, session_id, file_name, is_compaction, mtime, size_bytes, message_count "
                    "FROM agents ORDER BY mtime DESC LIMIT ?",
                    (limit,),
                )
                self.json_response(rows)
                return

            if path == "/api/messages":
                agent_id = self.get_int_param(params, "agent_id", None, minimum=1, maximum=10_000_000, required=True)
                limit = self.get_int_param(params, "limit", 1000, minimum=1, maximum=2000)
                rows = db.query(
                    "SELECT role, content FROM messages WHERE agent_id=? ORDER BY idx LIMIT ?",
                    (agent_id, limit),
                )
                self.json_response(rows)
                return

            if path == "/api/memory":
                limit = self.get_int_param(params, "limit", 200, minimum=1, maximum=MAX_LIMIT)
                rows = db.query(
                    "SELECT project, file_name, content FROM memory_files ORDER BY project, file_name LIMIT ?",
                    (limit,),
                )
                self.json_response(rows)
                return

            if path == "/api/hooks":
                limit = self.get_int_param(params, "limit", 100, minimum=1, maximum=MAX_LIMIT)
                rows = db.query(
                    "SELECT timestamp, event_type, data_json FROM hook_events ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
                self.json_response(rows)
                return

            if path == "/api/search":
                term = params.get("q", [""])[0].strip()
                if not term:
                    self.json_response([])
                    return
                if len(term) > MAX_SEARCH_TERM_LENGTH:
                    raise BadRequest(f"search term must be {MAX_SEARCH_TERM_LENGTH} characters or fewer")

                like = "%" + escape_like(term) + "%"
                results = []
                for row in db.query(
                    "SELECT time, event, session_id FROM telemetry "
                    "WHERE event LIKE ? ESCAPE '\\' OR session_id LIKE ? ESCAPE '\\' LIMIT ?",
                    (like, like, SEARCH_RESULTS_PER_TABLE),
                ):
                    row["source"] = "telemetry"
                    results.append(row)
                for row in db.query(
                    "SELECT role, content, agent_id FROM messages "
                    "WHERE content LIKE ? ESCAPE '\\' LIMIT ?",
                    (like, SEARCH_RESULTS_PER_TABLE),
                ):
                    row["source"] = "message"
                    results.append(row)
                for row in db.query(
                    "SELECT project, file_name, content FROM memory_files "
                    "WHERE content LIKE ? ESCAPE '\\' LIMIT ?",
                    (like, SEARCH_RESULTS_PER_TABLE),
                ):
                    row["source"] = "memory"
                    results.append(row)
                self.json_response(results)
                return

            if path == "/api/tasks":
                limit = self.get_int_param(params, "limit", 200, minimum=1, maximum=MAX_LIMIT)
                rows = db.query(
                    "SELECT session_id, task_id, subject, description, status "
                    "FROM tasks ORDER BY session_id LIMIT ?",
                    (limit,),
                )
                self.json_response(rows)
                return

            if path == "/api/correlations":
                project_limit = self.get_int_param(params, "project_limit", 100, minimum=1, maximum=MAX_LIMIT)
                event_limit = self.get_int_param(params, "event_limit", 100, minimum=1, maximum=MAX_LIMIT)
                session_limit = self.get_int_param(params, "session_limit", 200, minimum=1, maximum=MAX_LIMIT)

                hook_timeline = db.query(
                    "SELECT substr(timestamp, 1, 16) as minute, COUNT(*) as count, event_type "
                    "FROM hook_events GROUP BY minute, event_type ORDER BY minute"
                )
                agents_per_project = db.query(
                    "SELECT project, COUNT(*) as total, "
                    "SUM(CASE WHEN is_compaction=1 THEN 1 ELSE 0 END) as compactions, "
                    "SUM(CASE WHEN is_compaction=0 THEN 1 ELSE 0 END) as agents, "
                    "SUM(message_count) as total_messages "
                    "FROM agents GROUP BY project ORDER BY total DESC LIMIT ?",
                    (project_limit,),
                )
                tel_by_type = db.query(
                    "SELECT event, COUNT(*) as count FROM telemetry GROUP BY event ORDER BY count DESC LIMIT ?",
                    (event_limit,),
                )
                session_spans = db.query(
                    "SELECT session_id, MIN(time) as first_seen, MAX(time) as last_seen, COUNT(*) as event_count "
                    "FROM telemetry GROUP BY session_id ORDER BY first_seen DESC LIMIT ?",
                    (session_limit,),
                )
                self.json_response({
                    "hook_timeline": hook_timeline,
                    "agents_per_project": agents_per_project,
                    "telemetry_by_type": tel_by_type,
                    "session_spans": session_spans,
                })
                return

            if path == "/api/reminders":
                limit = self.get_int_param(params, "limit", 50, minimum=1, maximum=MAX_LIMIT)
                rows = db.query(
                    "SELECT source_file, line_number, substr(content, 1, 500) as content, timestamp "
                    "FROM system_reminders ORDER BY source_file, line_number LIMIT ?",
                    (limit,),
                )
                self.json_response(rows)
                return

            if path == "/api/states":
                self.json_response(states.get_state_diagram())
                return

            if path == "/api/analyze":
                limit = self.get_int_param(params, "limit", MAX_ANALYZE_EVENTS, minimum=1, maximum=MAX_ANALYZE_EVENTS)
                hook_events = db.query(
                    "SELECT timestamp, event_type, data_json as data "
                    "FROM hook_events ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
                hook_events.reverse()
                for event in hook_events:
                    if isinstance(event.get("data"), str):
                        try:
                            event["data"] = json.loads(event["data"])
                        except json.JSONDecodeError:
                            pass
                analysis = states.analyze_session(hook_events)
                self.json_response(analysis)
                return

            if path == "/api/tokens":
                self.json_response(tokens.summary())
                return

            self.respond(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        except BadRequest as exc:
            self.json_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception:
            traceback.print_exc()
            self.json_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal server error")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            if path != "/api/ingest":
                self.respond(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
                return

            self.enforce_same_origin_post()
            self.read_request_body(max_bytes=1024 * 64)
            result = db.ingest_all()
            self.json_response(result)
        except BadRequest as exc:
            self.json_error(HTTPStatus.BAD_REQUEST, str(exc))
        except PermissionError as exc:
            self.json_error(HTTPStatus.FORBIDDEN, str(exc))
        except Exception:
            traceback.print_exc()
            self.json_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal server error")

    def do_OPTIONS(self):
        self.respond(HTTPStatus.METHOD_NOT_ALLOWED, b"method not allowed", "text/plain")

    def get_int_param(self, params, name, default, minimum=0, maximum=None, required=False):
        raw = params.get(name, [None])[0]
        if raw in (None, ""):
            if required:
                raise BadRequest(f"missing required parameter: {name}")
            return default
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise BadRequest(f"invalid integer for {name}") from exc
        if value < minimum:
            raise BadRequest(f"{name} must be >= {minimum}")
        if maximum is not None and value > maximum:
            raise BadRequest(f"{name} must be <= {maximum}")
        return value

    def read_request_body(self, max_bytes: int) -> bytes:
        length_header = self.headers.get("Content-Length", "0")
        try:
            length = int(length_header)
        except ValueError as exc:
            raise BadRequest("invalid Content-Length") from exc
        if length < 0 or length > max_bytes:
            raise BadRequest("request body too large")
        if length == 0:
            return b""
        return self.rfile.read(length)

    def enforce_same_origin_post(self) -> None:
        allowed_origins = getattr(self.server, "allowed_origins", set())
        origin = self.headers.get("Origin")
        referer = self.headers.get("Referer")

        if origin and origin in allowed_origins:
            return
        if referer and any(referer == allowed or referer.startswith(allowed + "/") for allowed in allowed_origins):
            return

        raise PermissionError("cross-origin POST blocked")

    def json_response(self, data, status=HTTPStatus.OK):
        content = json.dumps(data, default=str).encode("utf-8")
        self.respond(status, content, "application/json")

    def json_error(self, status, message: str):
        self.json_response({"error": message}, status=status)

    def respond(self, code, content: bytes, content_type: str):
        try:
            self.send_response(int(code))
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            if content_type == "text/html":
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
                )
            self.end_headers()
            self.wfile.write(content)
        except BrokenPipeError:
            pass

    def log_message(self, *args):
        pass


class ThreadedHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(port: int = DEFAULT_PORT) -> None:
    server = ThreadedHTTPServer(("127.0.0.1", port), Handler)
    server.allowed_origins = {
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
    }
    print("harnesster: http://127.0.0.1:" + str(port))
    webbrowser.open("http://127.0.0.1:" + str(port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        server.server_close()


def get_port(args):
    if "--port" in args:
        idx = args.index("--port")
        if idx + 1 < len(args):
            try:
                port = int(args[idx + 1])
            except ValueError as exc:
                raise SystemExit("--port must be an integer") from exc
            if port < 1 or port > 65535:
                raise SystemExit("--port must be between 1 and 65535")
            return port
        raise SystemExit("--port requires a value")
    return DEFAULT_PORT


if __name__ == "__main__":
    args = sys.argv[1:]
    port = get_port(args)

    if "--setup" in args:
        setup()
    elif "--ingest" in args:
        result = db.ingest_all()
        print("ingested:", result)
        print("db:", db.summary())
    elif "--dashboard" in args:
        serve(port)
    elif not args or "--port" in args:
        setup()
        db.ingest_all()
        print("data:", db.summary())
        print()
        serve(port)
    else:
        print(__doc__)
