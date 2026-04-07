"""
harnesster smoke tests — verify core paths without nuking state
"""

import io
import os
import sys

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

print("\ndb.py")
import db

check("get_db returns connection", db.get_db() is not None)
conn = db.get_db()
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
for table in ["telemetry", "sessions", "agents", "messages", "memory_files", "hook_events", "tasks", "system_reminders"]:
    check(f"table {table} exists", table in tables)
conn.close()
check("summary returns dict", isinstance(db.summary(), dict))
check("query works", isinstance(db.query("SELECT 1 as x"), list))

print("\nharnesster.py")
import harnesster
check("hook command uses installed probe path", str(harnesster.INSTALLED_PROBE_PATH) in harnesster.build_hook_command(harnesster.INSTALLED_PROBE_PATH, "notification"))
check("escape_like escapes percent", harnesster.escape_like("100%") == "100\\%")

print("\nharness_probe.py")
import harness_probe
old_stdin = sys.stdin
sys.stdin = io.StringIO("not json at all{{{")
harness_probe.log_event("test_corrupt")
sys.stdin = old_stdin
check("corrupt JSON doesn't crash probe", True)

print("\ndashboard.html")
dash_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
with open(dash_path, encoding="utf-8") as fh:
    content = fh.read()
check("dashboard exists", os.path.exists(dash_path))
check("dashboard checks fetch status", "if (!r.ok)" in content)
check("dashboard uses no-store fetches", "cache: 'no-store'" in content)

print(f"\n{'=' * 40}")
print(f"passed: {PASS}  failed: {FAIL}")
if FAIL > 0:
    sys.exit(1)
