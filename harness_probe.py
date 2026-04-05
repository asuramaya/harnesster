"""
harness_probe.py — capture Claude Code events to database and log

Hook script for settings.json. Writes to both JSONL (for tail -f)
and SQLite (for dashboard).
"""

import sys
import json
import os
import sqlite3
from datetime import datetime

LOG_DIR = os.path.join(os.path.expanduser("~"), ".harnesster")
LOG_FILE = os.path.join(LOG_DIR, "harness_log.jsonl")
DB_FILE = os.path.join(LOG_DIR, "harnesster.db")


def log_event(event_type):
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"raw": raw}

        ts = datetime.now().isoformat()
        entry = {"timestamp": ts, "event_type": event_type, "data": data}

        os.makedirs(LOG_DIR, mode=0o700, exist_ok=True)

        # jsonl for tail -f
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")

        # sqlite for dashboard
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hook_events (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT,
                    event_type TEXT,
                    data_json TEXT
                )
            """)
            conn.execute(
                "INSERT INTO hook_events (timestamp, event_type, data_json) VALUES (?,?,?)",
                (ts, event_type, json.dumps(data))
            )
            conn.commit()
            conn.close()
        except:
            pass

    except Exception as e:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps({
                "timestamp": datetime.now().isoformat(),
                "event_type": "error",
                "error": str(e)
            }) + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: harness_probe.py <event_type>")
        sys.exit(1)
    log_event(sys.argv[1])
