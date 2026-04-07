#!/usr/bin/env python3
"""
harnesster — see what Claude Code hides from you

  python3 harnesster.py              # ingest + setup + dashboard
  python3 harnesster.py --setup      # install hooks only
  python3 harnesster.py --ingest     # ingest data only
  python3 harnesster.py --dashboard  # dashboard only
  python3 harnesster.py --port 8888  # custom port
"""

import json, sys, os, shutil, subprocess, http.server, webbrowser
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from socketserver import ThreadingMixIn

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))
import db
import states
import tokens

PROBE_PATH = SCRIPT_DIR / "harness_probe.py"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
TEMPLATE_PATH = SCRIPT_DIR / "dashboard.html"
DEFAULT_PORT = 7777


def setup():
    print("harnesster setup")
    print("=" * 40)
    os.makedirs(db.DB_PATH.parent, exist_ok=True)

    if not SETTINGS_PATH.exists():
        print("ERROR: settings.json not found")
        sys.exit(1)

    with open(SETTINGS_PATH) as f:
        settings = json.load(f)

    def make_hook(arg):
        return {"matcher": ".*", "hooks": [{"type": "command", "command": "python3 " + str(PROBE_PATH) + " " + arg, "async": True}]}

    hooks = settings.get("hooks", {})
    changed = False
    all_events = {
        "PreToolUse": "pretool", "PostToolUse": "posttool", "PostToolUseFailure": "posttool_fail",
        "Notification": "notification", "SessionStart": "session_start", "SessionEnd": "session_end",
        "Stop": "stop", "SubagentStart": "subagent_start", "SubagentStop": "subagent_stop",
        "PreCompact": "pre_compact", "PostCompact": "post_compact",
        "UserPromptSubmit": "user_prompt", "InstructionsLoaded": "instructions_loaded",
        "PermissionRequest": "perm_request", "PermissionDenied": "perm_denied",
        "TaskCreated": "task_created", "TaskCompleted": "task_completed",
        "FileChanged": "file_changed", "CwdChanged": "cwd_changed",
        "ConfigChange": "config_change",
    }
    for event, arg in all_events.items():
        existing = hooks.get(event, [])
        has_probe = any("harness_probe" in json.dumps(h) for h in existing)
        if has_probe:
            for h in existing:
                for hook in h.get("hooks", []):
                    if "harness_probe" in hook.get("command", ""):
                        new_cmd = "python3 " + str(PROBE_PATH) + " " + arg
                        if hook["command"] != new_cmd:
                            hook["command"] = new_cmd
                            changed = True
        else:
            existing.append(make_hook(arg))
            changed = True
        hooks[event] = existing

    if changed:
        settings["hooks"] = hooks
        shutil.copy2(SETTINGS_PATH, str(SETTINGS_PATH) + ".bak")
        with open(SETTINGS_PATH, "w") as f:
            json.dump(settings, f, indent=2)
        print("hooks installed.")
    else:
        print("hooks up to date.")

    subprocess.run(["python3", str(PROBE_PATH), "notification"], input='{"test":"setup"}', text=True)
    print("restart Claude Code for hooks to take effect.\n")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        params = parse_qs(urlparse(self.path).query)

        if path == "/" or path == "/dashboard":
            with open(TEMPLATE_PATH) as f:
                content = f.read().encode()
            self.respond(200, content, "text/html")

        elif path == "/api/summary":
            self.json_response(db.summary())

        elif path == "/api/telemetry":
            limit = int(params.get("limit", [500])[0])
            offset = int(params.get("offset", [0])[0])
            rows = db.query("SELECT time, event, session_id, parent_session_id, version, model FROM telemetry ORDER BY time DESC LIMIT ? OFFSET ?", (limit, offset))
            self.json_response(rows)

        elif path == "/api/sessions":
            rows = db.query("SELECT project, session_id, mtime, agent_count, compaction_count FROM sessions ORDER BY project, mtime")
            self.json_response(rows)

        elif path == "/api/agents":
            limit = int(params.get("limit", [100])[0])
            rows = db.query("SELECT id, project, session_id, file_name, is_compaction, mtime, size_bytes, message_count FROM agents ORDER BY mtime DESC LIMIT ?", (limit,))
            self.json_response(rows)

        elif path == "/api/messages":
            agent_id = params.get("agent_id", [None])[0]
            if agent_id:
                rows = db.query("SELECT role, content FROM messages WHERE agent_id=? ORDER BY idx", (int(agent_id),))
                self.json_response(rows)
            else:
                self.json_response([])

        elif path == "/api/memory":
            rows = db.query("SELECT project, file_name, content FROM memory_files ORDER BY project")
            self.json_response(rows)

        elif path == "/api/hooks":
            limit = int(params.get("limit", [100])[0])
            rows = db.query("SELECT timestamp, event_type, data_json FROM hook_events ORDER BY timestamp DESC LIMIT ?", (limit,))
            self.json_response(rows)

        elif path == "/api/search":
            term = params.get("q", [""])[0]
            if not term:
                self.json_response([])
                return
            if len(term) > 200:
                self.respond(400, b"search term too long", "text/plain")
                return
            like = "%" + term + "%"
            results = []
            for row in db.query("SELECT time, event, session_id FROM telemetry WHERE event LIKE ? OR session_id LIKE ? LIMIT 50", (like, like)):
                row["source"] = "telemetry"
                results.append(row)
            for row in db.query("SELECT role, content, agent_id FROM messages WHERE content LIKE ? LIMIT 50", (like,)):
                row["source"] = "message"
                results.append(row)
            for row in db.query("SELECT project, file_name, content FROM memory_files WHERE content LIKE ? LIMIT 50", (like,)):
                row["source"] = "memory"
                results.append(row)
            self.json_response(results)

        elif path == "/api/tasks":
            rows = db.query("SELECT session_id, task_id, subject, description, status FROM tasks ORDER BY session_id")
            self.json_response(rows)

        elif path == "/api/correlations":
            # system reminder frequency vs session activity
            hook_timeline = db.query("""
                SELECT substr(timestamp, 1, 16) as minute, COUNT(*) as count, event_type
                FROM hook_events GROUP BY minute, event_type ORDER BY minute
            """)
            # agents per project
            agents_per_project = db.query("""
                SELECT project, COUNT(*) as total,
                    SUM(CASE WHEN is_compaction=1 THEN 1 ELSE 0 END) as compactions,
                    SUM(CASE WHEN is_compaction=0 THEN 1 ELSE 0 END) as agents,
                    SUM(message_count) as total_messages
                FROM agents GROUP BY project ORDER BY total DESC
            """)
            # telemetry events by type
            tel_by_type = db.query("""
                SELECT event, COUNT(*) as count FROM telemetry GROUP BY event ORDER BY count DESC
            """)
            # session durations (from telemetry timestamps)
            session_spans = db.query("""
                SELECT session_id, MIN(time) as first_seen, MAX(time) as last_seen,
                    COUNT(*) as event_count
                FROM telemetry GROUP BY session_id ORDER BY first_seen
            """)
            self.json_response({
                "hook_timeline": hook_timeline,
                "agents_per_project": agents_per_project,
                "telemetry_by_type": tel_by_type,
                "session_spans": session_spans,
            })

        elif path == "/api/reminders":
            limit = int(params.get("limit", [50])[0])
            try:
                rows = db.query("SELECT source_file, line_number, substr(content, 1, 500) as content, timestamp FROM system_reminders ORDER BY source_file, line_number LIMIT ?", (limit,))
            except:
                rows = []
            self.json_response(rows)

        elif path == "/api/states":
            self.json_response(states.get_state_diagram())

        elif path == "/api/analyze":
            hook_events = db.query("SELECT timestamp, event_type, data_json as data FROM hook_events ORDER BY timestamp")
            for e in hook_events:
                if e.get("data") and isinstance(e["data"], str):
                    try: e["data"] = json.loads(e["data"])
                    except: pass
            analysis = states.analyze_session(hook_events)
            self.json_response(analysis)

        elif path == "/api/tokens":
            self.json_response(tokens.summary())

        elif path == "/api/ingest":
            result = db.ingest_all()
            self.json_response(result)

        else:
            self.respond(404, b"not found", "text/plain")

    def json_response(self, data):
        content = json.dumps(data, default=str).encode()
        self.respond(200, content, "application/json")

    def respond(self, code, content, content_type):
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "null")
            self.end_headers()
            self.wfile.write(content)
        except BrokenPipeError:
            pass

    def log_message(self, *a):
        pass


class ThreadedHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

def serve(port=DEFAULT_PORT):
    server = ThreadedHTTPServer(("127.0.0.1", port), Handler)
    print("harnesster: http://127.0.0.1:" + str(port))
    webbrowser.open("http://127.0.0.1:" + str(port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        server.server_close()


def get_port(args):
    if "--port" in args:
        idx = args.index("--port")
        if idx + 1 < len(args):
            return int(args[idx + 1])
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
