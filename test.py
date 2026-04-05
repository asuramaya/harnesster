"""
harnesster smoke tests — verify core paths without nuking state
"""

import sys
import os
import json
import tempfile
import sqlite3

# run from harnesster directory
sys.path.insert(0, os.path.dirname(__file__))

PASS = 0
FAIL = 0

def check(name, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


print("harnesster smoke tests")
print("=" * 40)

# --- db.py ---
print("\ndb.py")
import db

check("get_db returns connection", db.get_db() is not None)

conn = db.get_db()
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
for t in ["telemetry", "sessions", "agents", "messages", "memory_files", "hook_events", "tasks", "system_reminders"]:
    check(f"table {t} exists", t in tables)
conn.close()

check("summary returns dict", isinstance(db.summary(), dict))
check("summary has all keys", all(k in db.summary() for k in ["telemetry", "sessions", "agents", "system_reminders", "device"]))
check("query works", isinstance(db.query("SELECT 1 as x"), list))

# --- tokens.py ---
print("\ntokens.py")
import tokens

check("imports clean", True)
s = tokens.summary()
check("summary returns dict", isinstance(s, dict))
check("has totals", "totals" in s)
check("has sessions", "sessions" in s)
t = s["totals"]
check("has data_multiplier", "data_multiplier" in t)
check("has hidden_data_pct", "hidden_data_pct" in t)
check("has system_reminders", "system_reminders" in t)
check("multiplier >= 1", t["data_multiplier"] >= 1.0)
check("hidden pct 0-100", 0 <= t["hidden_data_pct"] <= 100)

# --- states.py ---
print("\nstates.py")
import states

check("imports clean", True)
d = states.get_state_diagram()
check("has states", "states" in d)
check("has transitions", "transitions" in d)
check("has hidden", "hidden" in d)
check("has anomalies", "anomalies" in d)
check("REMINDER_INJECT is hidden", "REMINDER_INJECT" in d["hidden"])

# test state inference
event = {"event_type": "pretool", "data": {"tool_name": "Bash"}}
state, detail = states.infer_state(event)
check("infer_state pretool", state == "TOOL_PRE")

event2 = {"event_type": "notification", "data": {"notification_type": "idle_prompt"}}
state2, detail2 = states.infer_state(event2)
check("infer_state idle", state2 == "IDLE")

# --- harness_probe.py ---
print("\nharness_probe.py")
check("probe file exists", os.path.exists(os.path.join(os.path.dirname(__file__), "harness_probe.py")))

# --- dashboard.html ---
print("\ndashboard.html")
dash_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
check("dashboard exists", os.path.exists(dash_path))
with open(dash_path) as f:
    content = f.read()
check("has api calls", "/api/summary" in content)
check("has state machine", "/api/states" in content)
check("has correlations", "/api/correlations" in content)
check("has token accounting", "/api/tokens" in content)
check("no template literals", "${" not in content)
check("no f-string artifacts", "f'" not in content and 'f"' not in content)

# --- integration ---
print("\nintegration")
check("reminder count > 0", db.summary()["system_reminders"] > 0)
check("sessions > 0", db.summary()["sessions"] > 0)
check("tokens reminders match db", tokens.summary()["totals"]["system_reminders"] == db.summary()["system_reminders"])

# --- failure cases ---
print("\nfailure handling")

# bad SQL
try:
    db.query("SELECT * FROM nonexistent_table")
    check("bad SQL raises", False)
except Exception:
    check("bad SQL raises", True)

# empty file analysis
import tokens as tok
empty_stats = tok.analyze_session_file(type('P', (), {"stat": lambda s: type('S', (), {"st_size": 0})(), "name": "fake.jsonl", "__str__": lambda s: "/dev/null"})())
check("empty file returns zero messages", empty_stats["messages"] == 0)
check("empty file returns zero reminders", empty_stats["system_reminders"] == 0)

# missing directory
import tokens
old_claude = tokens.CLAUDE_DIR
tokens.CLAUDE_DIR = type('P', (), {"exists": lambda s: False, "home": lambda: type('P', (), {"__truediv__": lambda s,o: s})()})()
try:
    result = tokens.analyze_all_projects()
    check("missing claude dir returns empty", result == [])
except Exception:
    check("missing claude dir returns empty", False)
tokens.CLAUDE_DIR = old_claude

# corrupt JSON in probe
import harness_probe
import io
old_stdin = sys.stdin
sys.stdin = io.StringIO("not json at all{{{")
harness_probe.log_event("test_corrupt")
sys.stdin = old_stdin
check("corrupt JSON doesn't crash probe", True)

# state inference on garbage
state, detail = states.infer_state({"event_type": "unknown_garbage", "data": "not a dict"})
check("garbage event returns IDLE", state == "IDLE")

# db connection with nonexistent parent
old_path = db.DB_PATH
db.DB_PATH = type('P', (), {
    "parent": type('P', (), {"__str__": lambda s: "/tmp/harnesster_test_" + str(os.getpid())})(),
    "__str__": lambda s: "/tmp/harnesster_test_" + str(os.getpid()) + "/test.db"
})()
db._schema_ready = False
try:
    conn = db.get_db()
    conn.close()
    check("creates db in new directory", True)
except Exception:
    check("creates db in new directory", False)
db.DB_PATH = old_path
db._schema_ready = False

# --- results ---
print(f"\n{'=' * 40}")
print(f"passed: {PASS}  failed: {FAIL}")
if FAIL > 0:
    sys.exit(1)
