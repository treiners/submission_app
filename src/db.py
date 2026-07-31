import json
import sqlite3
from datetime import datetime, timezone

DB_PATH = "instance/submissions.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    student_id TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    ip_address TEXT,
    user_agent TEXT,
    submitted_at TEXT NOT NULL,
    email TEXT,
    email_sent INTEGER NOT NULL DEFAULT 0,
    storage_backend TEXT NOT NULL,
    storage_note TEXT
);

CREATE TABLE IF NOT EXISTS submission_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL REFERENCES submissions(id),
    area_key TEXT NOT NULL,
    area_label TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    storage_location TEXT NOT NULL,
    size_bytes INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS submission_declarations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL REFERENCES submissions(id),
    area_key TEXT NOT NULL,
    area_label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL REFERENCES submissions(id),
    run_filename TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    duration_seconds REAL,
    result_location TEXT,
    stdout TEXT,
    stderr TEXT,
    error TEXT,
    statistics_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_submissions_student_id ON submissions(student_id);
CREATE INDEX IF NOT EXISTS idx_submissions_code ON submissions(code);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def code_exists(code):
    conn = get_connection()
    row = conn.execute("SELECT 1 FROM submissions WHERE code = ?", (code,)).fetchone()
    conn.close()
    return row is not None


def create_submission(name, student_id, code, ip_address, user_agent, email,
                       storage_backend, storage_note=""):
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO submissions
           (name, student_id, code, ip_address, user_agent, submitted_at,
            email, email_sent, storage_backend, storage_note)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
        (name, student_id, code, ip_address, user_agent,
         datetime.now(timezone.utc).isoformat(), email, storage_backend, storage_note),
    )
    submission_id = cur.lastrowid
    conn.commit()
    conn.close()
    return submission_id


def add_submission_file(submission_id, area_key, area_label, original_filename,
                         stored_filename, storage_location, size_bytes):
    conn = get_connection()
    conn.execute(
        """INSERT INTO submission_files
           (submission_id, area_key, area_label, original_filename,
            stored_filename, storage_location, size_bytes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (submission_id, area_key, area_label, original_filename,
         stored_filename, storage_location, size_bytes),
    )
    conn.commit()
    conn.close()


def add_declaration(submission_id, area_key, area_label):
    conn = get_connection()
    conn.execute(
        """INSERT INTO submission_declarations (submission_id, area_key, area_label)
           VALUES (?, ?, ?)""",
        (submission_id, area_key, area_label),
    )
    conn.commit()
    conn.close()


def mark_email_sent(submission_id, sent=True):
    conn = get_connection()
    conn.execute(
        "UPDATE submissions SET email_sent = ? WHERE id = ?",
        (1 if sent else 0, submission_id),
    )
    conn.commit()
    conn.close()


def list_submissions(search=None):
    conn = get_connection()
    if search:
        like = f"%{search}%"
        rows = conn.execute(
            """SELECT * FROM submissions
               WHERE name LIKE ? OR student_id LIKE ? OR code LIKE ?
               ORDER BY submitted_at DESC""",
            (like, like, like),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM submissions ORDER BY submitted_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_submission(submission_id):
    conn = get_connection()
    submission = conn.execute(
        "SELECT * FROM submissions WHERE id = ?", (submission_id,)
    ).fetchone()
    files = conn.execute(
        "SELECT * FROM submission_files WHERE submission_id = ?", (submission_id,)
    ).fetchall()
    declarations = conn.execute(
        "SELECT * FROM submission_declarations WHERE submission_id = ?", (submission_id,)
    ).fetchall()
    analysis_runs = conn.execute(
        "SELECT * FROM analysis_runs WHERE submission_id = ? ORDER BY id DESC", (submission_id,)
    ).fetchall()
    conn.close()
    if submission is None:
        return None
    result = dict(submission)
    result["files"] = [dict(f) for f in files]
    result["declarations"] = [dict(d) for d in declarations]
    result["analysis_runs"] = []
    for run in analysis_runs:
        run = dict(run)
        try:
            run["statistics"] = json.loads(run.pop("statistics_json"))
        except (TypeError, json.JSONDecodeError):
            run["statistics"] = {}
        result["analysis_runs"].append(run)
    return result


def get_submission_by_code(code):
    conn = get_connection()
    submission = conn.execute(
        "SELECT * FROM submissions WHERE code = ?", (code.upper(),)
    ).fetchone()
    conn.close()
    return dict(submission) if submission else None


def delete_submission(submission_id):
    conn = get_connection()
    conn.execute("DELETE FROM analysis_runs WHERE submission_id = ?", (submission_id,))
    conn.execute("DELETE FROM submission_files WHERE submission_id = ?", (submission_id,))
    conn.execute("DELETE FROM submission_declarations WHERE submission_id = ?", (submission_id,))
    conn.execute("DELETE FROM submissions WHERE id = ?", (submission_id,))
    conn.commit()
    conn.close()


def create_analysis_run(submission_id, run_filename, result_location):
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO analysis_runs
           (submission_id, run_filename, status, started_at, result_location)
           VALUES (?, ?, 'running', ?, ?)""",
        (submission_id, run_filename, datetime.now(timezone.utc).isoformat(), result_location),
    )
    run_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return run_id


def update_analysis_run(run_id, status, result, completed=True):
    conn = get_connection()
    conn.execute(
        """UPDATE analysis_runs
           SET status = ?, completed_at = ?, duration_seconds = ?, stdout = ?,
               stderr = ?, error = ?, statistics_json = ?
           WHERE id = ?""",
        (
            status,
            datetime.now(timezone.utc).isoformat() if completed else None,
            result.get("duration_seconds"),
            result.get("stdout", ""),
            result.get("stderr", ""),
            result.get("error"),
            json.dumps({
                **result.get("statistics", {}),
                "diagnostics": result.get("diagnostics", {}),
            }),
            run_id,
        ),
    )
    conn.commit()
    conn.close()


def delete_analysis_run(run_id, submission_id):
    conn = get_connection()
    conn.execute(
        "DELETE FROM analysis_runs WHERE id = ? AND submission_id = ?",
        (run_id, submission_id),
    )
    conn.commit()
    conn.close()
