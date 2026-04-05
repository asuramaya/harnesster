"""
harnesster data layer — one database, all sources
"""

import json
import sqlite3
import os
import threading
from pathlib import Path
from datetime import datetime

CLAUDE_DIR = Path.home() / ".claude"
DB_PATH = Path.home() / ".harnesster" / "harnesster.db"

_schema_lock = threading.Lock()
_schema_ready = False


def get_db():
    global _schema_ready
    os.makedirs(DB_PATH.parent, mode=0o700, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    with _schema_lock:
        if not _schema_ready:
            _init_schema(conn)
            _schema_ready = True
    return conn


def _init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY, time TEXT, event TEXT, session_id TEXT,
            parent_session_id TEXT, device_id TEXT, version TEXT, model TEXT,
            platform TEXT, arch TEXT, process_json TEXT, raw_json TEXT, source_file TEXT,
            UNIQUE(time, event, session_id)
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY, project TEXT, session_id TEXT, mtime TEXT,
            agent_count INTEGER DEFAULT 0, compaction_count INTEGER DEFAULT 0,
            UNIQUE(project, session_id)
        );
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY, project TEXT, session_id TEXT, file_name TEXT,
            is_compaction INTEGER DEFAULT 0, mtime TEXT, size_bytes INTEGER,
            message_count INTEGER DEFAULT 0, UNIQUE(project, session_id, file_name)
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY, agent_id INTEGER REFERENCES agents(id),
            idx INTEGER, role TEXT, content TEXT
        );
        CREATE TABLE IF NOT EXISTS memory_files (
            id INTEGER PRIMARY KEY, project TEXT, file_name TEXT, content TEXT,
            UNIQUE(project, file_name)
        );
        CREATE TABLE IF NOT EXISTS hook_events (
            id INTEGER PRIMARY KEY, timestamp TEXT, event_type TEXT, data_json TEXT
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY, session_id TEXT, task_id TEXT,
            subject TEXT, description TEXT, status TEXT, raw_json TEXT,
            UNIQUE(session_id, task_id)
        );
        CREATE TABLE IF NOT EXISTS system_reminders (
            id INTEGER PRIMARY KEY, source_file TEXT, line_number INTEGER,
            content TEXT, timestamp TEXT,
            UNIQUE(source_file, line_number)
        );
        CREATE INDEX IF NOT EXISTS idx_tel_session ON telemetry(session_id);
        CREATE INDEX IF NOT EXISTS idx_tel_time ON telemetry(time);
        CREATE INDEX IF NOT EXISTS idx_agents_project ON agents(project);
        CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_id);
        CREATE INDEX IF NOT EXISTS idx_hooks_time ON hook_events(timestamp);
    """)
    conn.commit()


def _project_name(path):
    name = path.name
    for prefix in ["-Users-", "-home-"]:
        if prefix in name:
            parts = name.split("-")
            try:
                idx = [i for i, p in enumerate(parts) if p.lower() == "code"]
                if idx:
                    return "-".join(parts[idx[-1]+1:])
            except:
                pass
    return name


def ingest_telemetry(conn):
    tel_dir = CLAUDE_DIR / "telemetry"
    if not tel_dir.exists():
        return 0
    count = 0
    for f in tel_dir.glob("*.json"):
        try:
            with open(f) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    e = json.loads(line)
                    ed = e.get("event_data", {})
                    try:
                        conn.execute(
                            "INSERT OR IGNORE INTO telemetry (time,event,session_id,parent_session_id,device_id,version,model,platform,arch,process_json,raw_json,source_file) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (ed.get("client_timestamp",""), ed.get("event_name",""), ed.get("session_id",""),
                             ed.get("parent_session_id",""), ed.get("device_id",""),
                             ed.get("env",{}).get("version",""), ed.get("model",""),
                             ed.get("env",{}).get("platform",""), ed.get("env",{}).get("arch",""),
                             ed.get("process",""), line, f.name))
                        count += 1
                    except sqlite3.IntegrityError:
                        pass
        except Exception:
            pass
    conn.commit()
    return count


def ingest_sessions(conn):
    proj_dir = CLAUDE_DIR / "projects"
    if not proj_dir.exists():
        return 0
    count = 0
    for project in proj_dir.iterdir():
        if not project.is_dir():
            continue
        name = _project_name(project)
        for session in project.iterdir():
            if not session.is_dir():
                continue
            if session.name == "memory":
                for mf in session.glob("*"):
                    try:
                        with open(mf) as fh:
                            content = fh.read()[:5000]
                        conn.execute("INSERT OR REPLACE INTO memory_files (project,file_name,content) VALUES (?,?,?)",
                                     (name, mf.name, content))
                    except Exception:
                        pass
                continue

            sa_dir = session / "subagents"
            agent_files = list(sa_dir.glob("*.jsonl")) if sa_dir.exists() else []
            compacts = [a for a in agent_files if "compact" in a.name]
            regulars = [a for a in agent_files if "compact" not in a.name]

            conn.execute("INSERT OR REPLACE INTO sessions (project,session_id,mtime,agent_count,compaction_count) VALUES (?,?,?,?,?)",
                         (name, session.name, datetime.fromtimestamp(session.stat().st_mtime).isoformat(),
                          len(regulars), len(compacts)))

            for f in agent_files:
                is_compact = 1 if "compact" in f.name else 0
                mtime = datetime.fromtimestamp(f.stat().st_mtime).isoformat()
                conn.execute("INSERT OR REPLACE INTO agents (project,session_id,file_name,is_compaction,mtime,size_bytes) VALUES (?,?,?,?,?,?)",
                             (name, session.name, f.name, is_compact, mtime, f.stat().st_size))
                agent_id = conn.execute("SELECT id FROM agents WHERE project=? AND session_id=? AND file_name=?",
                                        (name, session.name, f.name)).fetchone()[0]

                if conn.execute("SELECT COUNT(*) FROM messages WHERE agent_id=?", (agent_id,)).fetchone()[0] > 0:
                    continue

                msg_count = 0
                try:
                    with open(f, errors="ignore") as fh:
                        for i, line in enumerate(fh):
                            try:
                                msg = json.loads(line.strip())
                                role = msg.get("role", "?")
                                content = msg.get("content", "")
                                if isinstance(content, list):
                                    content = " ".join(str(c.get("text", c)) for c in content if isinstance(c, dict))
                                conn.execute("INSERT INTO messages (agent_id,idx,role,content) VALUES (?,?,?,?)",
                                             (agent_id, i, role, str(content)[:3000]))
                                msg_count += 1
                            except Exception:
                                pass
                except Exception:
                    pass
                conn.execute("UPDATE agents SET message_count=? WHERE id=?", (msg_count, agent_id))
            count += 1
    conn.commit()
    return count


def ingest_hooks(conn):
    log_file = Path.home() / ".harnesster" / "harness_log.jsonl"
    if not log_file.exists():
        return 0
    existing = conn.execute("SELECT COUNT(*) FROM hook_events").fetchone()[0]
    count = 0
    with open(log_file) as fh:
        for i, line in enumerate(fh):
            if i < existing:
                continue
            try:
                e = json.loads(line.strip())
                conn.execute("INSERT INTO hook_events (timestamp,event_type,data_json) VALUES (?,?,?)",
                             (e.get("timestamp",""), e.get("event_type",""), json.dumps(e.get("data",{}))))
                count += 1
            except Exception:
                pass
    conn.commit()
    return count


def ingest_tasks(conn):
    tasks_dir = CLAUDE_DIR / "tasks"
    if not tasks_dir.exists():
        return 0
    count = 0
    for session_dir in tasks_dir.iterdir():
        if not session_dir.is_dir():
            continue
        sid = session_dir.name
        for tf in session_dir.glob("*.json"):
            try:
                with open(tf) as fh:
                    data = json.loads(fh.read())
                conn.execute("INSERT OR REPLACE INTO tasks (session_id,task_id,subject,description,status,raw_json) VALUES (?,?,?,?,?,?)",
                             (sid, data.get("id", tf.stem), data.get("subject",""),
                              data.get("description",""), data.get("status",""), json.dumps(data)))
                count += 1
            except Exception:
                pass
    conn.commit()
    return count


def ingest_exports(conn):
    """Parse raw JSONL transcripts for actual system-reminder injections."""
    count = 0
    proj_dir = CLAUDE_DIR / "projects"
    if not proj_dir.exists():
        return 0
    for f in proj_dir.rglob("*.jsonl"):
        try:
            with open(f, errors="ignore") as fh:
                for i, line in enumerate(fh):
                    if "system-reminder" in line and "NEVER mention" in line:
                        try:
                            conn.execute("INSERT OR IGNORE INTO system_reminders (source_file,line_number,content,timestamp) VALUES (?,?,?,?)",
                                         (str(f), i+1, line.strip()[:2000], datetime.now().isoformat()))
                            count += 1
                        except sqlite3.IntegrityError:
                            pass
        except Exception:
            pass
    conn.commit()
    return count


def ingest_all():
    conn = get_db()
    try:
        t = ingest_telemetry(conn)
        s = ingest_sessions(conn)
        h = ingest_hooks(conn)
        k = ingest_tasks(conn)
        r = ingest_exports(conn)
        return {"telemetry": t, "sessions": s, "hooks": h, "tasks": k, "reminders": r}
    finally:
        conn.close()


def query(sql, params=()):
    conn = get_db()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def summary():
    conn = get_db()
    try:
        return {
            "telemetry": conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0],
            "sessions": conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
            "agents": conn.execute("SELECT COUNT(*) FROM agents WHERE is_compaction=0").fetchone()[0],
            "compactions": conn.execute("SELECT COUNT(*) FROM agents WHERE is_compaction=1").fetchone()[0],
            "messages": conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
            "memory_files": conn.execute("SELECT COUNT(*) FROM memory_files").fetchone()[0],
            "hook_events": conn.execute("SELECT COUNT(*) FROM hook_events").fetchone()[0],
            "system_reminders": conn.execute("SELECT COUNT(*) FROM system_reminders").fetchone()[0],
            "device": (conn.execute("SELECT DISTINCT device_id FROM telemetry LIMIT 1").fetchone() or [None])[0],
        }
    finally:
        conn.close()


if __name__ == "__main__":
    print("ingesting ~/.claude/ data...")
    result = ingest_all()
    print(f"  telemetry: {result['telemetry']}")
    print(f"  sessions:  {result['sessions']}")
    print(f"  hooks:     {result['hooks']}")
    print(f"  tasks:     {result['tasks']}")
    print(f"  reminders: {result['reminders']}")
    s = summary()
    print(f"\ndb: {DB_PATH}")
    print(f"  {s['telemetry']} tel | {s['sessions']} ses | {s['agents']} agents | {s['compactions']} compact | {s['messages']} msgs | {s['system_reminders']} reminders")
