import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"
DB_PATH = INSTANCE_DIR / "submissions.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    student_id TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    ip_address TEXT,
    user_agent TEXT,
    submitted_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    failure_reason TEXT,
    marking_excluded INTEGER NOT NULL DEFAULT 0,
    marking_excluded_reason TEXT,
    marking_excluded_at TEXT,
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

CREATE TABLE IF NOT EXISTS marking_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL REFERENCES submissions(id),
    question_id TEXT NOT NULL,
    score TEXT,
    comment TEXT,
    comment_source TEXT NOT NULL DEFAULT 'human',
    ai_reasoning TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(submission_id, question_id)
);

CREATE TABLE IF NOT EXISTS eval_case_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL REFERENCES submissions(id),
    question_id TEXT NOT NULL,
    question_prompt TEXT NOT NULL,
    student_answer TEXT NOT NULL,
    marks_label TEXT,
    reference_score TEXT,
    reference_comment TEXT,
    ai_draft_used INTEGER NOT NULL DEFAULT 0,
    include_in_eval INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    UNIQUE(submission_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_submissions_student_id ON submissions(student_id);
CREATE INDEX IF NOT EXISTS idx_submissions_code ON submissions(code);
CREATE INDEX IF NOT EXISTS idx_marking_assessments_submission ON marking_assessments(submission_id);
CREATE INDEX IF NOT EXISTS idx_eval_case_candidates_include ON eval_case_candidates(include_in_eval);
"""


def get_connection():
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)

    # Lightweight schema migration for existing databases created before
    # status/failure tracking was introduced.
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(submissions)").fetchall()
    }
    if "status" not in columns:
        conn.execute("ALTER TABLE submissions ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'")
    if "failure_reason" not in columns:
        conn.execute("ALTER TABLE submissions ADD COLUMN failure_reason TEXT")
    if "marking_excluded" not in columns:
        conn.execute("ALTER TABLE submissions ADD COLUMN marking_excluded INTEGER NOT NULL DEFAULT 0")
    if "marking_excluded_reason" not in columns:
        conn.execute("ALTER TABLE submissions ADD COLUMN marking_excluded_reason TEXT")
    if "marking_excluded_at" not in columns:
        conn.execute("ALTER TABLE submissions ADD COLUMN marking_excluded_at TEXT")

    marking_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(marking_assessments)").fetchall()
    }
    if "comment_source" not in marking_columns:
        conn.execute("ALTER TABLE marking_assessments ADD COLUMN comment_source TEXT NOT NULL DEFAULT 'human'")
    if "ai_reasoning" not in marking_columns:
        conn.execute("ALTER TABLE marking_assessments ADD COLUMN ai_reasoning TEXT")

    conn.commit()
    conn.close()


def code_exists(code):
    conn = get_connection()
    row = conn.execute("SELECT 1 FROM submissions WHERE code = ?", (code,)).fetchone()
    conn.close()
    return row is not None


def create_submission(name, student_id, code, ip_address, user_agent, email,
                       storage_backend, storage_note="", status="processing",
                       failure_reason=None):
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO submissions
           (name, student_id, code, ip_address, user_agent, submitted_at,
                status, failure_reason, email, email_sent, storage_backend, storage_note)
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
        (name, student_id, code, ip_address, user_agent,
            datetime.now(timezone.utc).isoformat(), status, failure_reason,
            email, storage_backend, storage_note),
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


def update_submission_status(submission_id, status, failure_reason=None):
    conn = get_connection()
    conn.execute(
        "UPDATE submissions SET status = ?, failure_reason = ? WHERE id = ?",
        (status, failure_reason, submission_id),
    )
    conn.commit()
    conn.close()


def list_submissions(search=None, marking_filter="all"):
    normalized_filter = str(marking_filter or "all").strip().lower()
    if normalized_filter not in {"all", "included", "excluded"}:
        normalized_filter = "all"

    conn = get_connection()
    conditions = []
    params = []

    if search:
        like = f"%{search}%"
        conditions.append("(name LIKE ? OR student_id LIKE ? OR code LIKE ?)")
        params.extend([like, like, like])

    if normalized_filter == "included":
        conditions.append("COALESCE(marking_excluded, 0) = 0")
    elif normalized_filter == "excluded":
        conditions.append("COALESCE(marking_excluded, 0) = 1")

    where_clause = ""
    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)

    rows = conn.execute(
        f"SELECT * FROM submissions{where_clause} ORDER BY submitted_at DESC",
        tuple(params),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_marking_submission_ids():
    conn = get_connection()
    rows = conn.execute(
        """SELECT id
           FROM submissions
           WHERE COALESCE(marking_excluded, 0) = 0
           ORDER BY submitted_at DESC"""
    ).fetchall()
    conn.close()
    return [int(row["id"]) for row in rows]


def update_marking_exclusion(submission_id, excluded, reason=None):
    excluded_value = 1 if excluded else 0
    normalized_reason = (reason or "").strip() or None
    excluded_at = datetime.now(timezone.utc).isoformat() if excluded_value else None

    conn = get_connection()
    conn.execute(
        """UPDATE submissions
           SET marking_excluded = ?,
               marking_excluded_reason = ?,
               marking_excluded_at = ?
           WHERE id = ?""",
        (excluded_value, normalized_reason if excluded_value else None, excluded_at, submission_id),
    )
    conn.commit()
    conn.close()


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


def get_submission_preview_by_code(code):
    conn = get_connection()
    submission = conn.execute(
        "SELECT id, code, submitted_at FROM submissions WHERE code = ?",
        (code.upper(),),
    ).fetchone()
    if submission is None:
        conn.close()
        return None

    files = conn.execute(
        """SELECT area_key, area_label, original_filename
           FROM submission_files
           WHERE submission_id = ?
           ORDER BY area_label, id""",
        (submission["id"],),
    ).fetchall()
    declarations = conn.execute(
        """SELECT area_key, area_label
           FROM submission_declarations
           WHERE submission_id = ?
           ORDER BY area_label, id""",
        (submission["id"],),
    ).fetchall()
    conn.close()

    return {
        "code": submission["code"],
        "submitted_at": submission["submitted_at"],
        "files": [dict(row) for row in files],
        "declarations": [dict(row) for row in declarations],
    }


def delete_submission(submission_id):
    conn = get_connection()
    conn.execute("DELETE FROM eval_case_candidates WHERE submission_id = ?", (submission_id,))
    conn.execute("DELETE FROM marking_assessments WHERE submission_id = ?", (submission_id,))
    conn.execute("DELETE FROM analysis_runs WHERE submission_id = ?", (submission_id,))
    conn.execute("DELETE FROM submission_files WHERE submission_id = ?", (submission_id,))
    conn.execute("DELETE FROM submission_declarations WHERE submission_id = ?", (submission_id,))
    conn.execute("DELETE FROM submissions WHERE id = ?", (submission_id,))
    # Reset numbering when all submissions have been removed.
    remaining = conn.execute("SELECT COUNT(*) AS c FROM submissions").fetchone()["c"]
    if remaining == 0:
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'submissions'")
    conn.commit()
    conn.close()


def delete_all_submissions(reset_ids=True):
    conn = get_connection()
    conn.execute("DELETE FROM eval_case_candidates")
    conn.execute("DELETE FROM marking_assessments")
    conn.execute("DELETE FROM analysis_runs")
    conn.execute("DELETE FROM submission_files")
    conn.execute("DELETE FROM submission_declarations")
    conn.execute("DELETE FROM submissions")
    if reset_ids:
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'submissions'")
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


def save_marking_assessment(submission_id, question_id, score, comment, comment_source="human", ai_reasoning=""):
    normalized_source = str(comment_source or "human").strip().lower()
    if normalized_source not in {"ai", "ai_human_approved", "human"}:
        normalized_source = "human"

    normalized_reasoning = (ai_reasoning or "").strip()
    if normalized_source == "human":
        normalized_reasoning = ""

    conn = get_connection()
    conn.execute(
        """INSERT INTO marking_assessments
           (submission_id, question_id, score, comment, comment_source, ai_reasoning, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(submission_id, question_id)
           DO UPDATE SET
             score = excluded.score,
             comment = excluded.comment,
             comment_source = excluded.comment_source,
             ai_reasoning = excluded.ai_reasoning,
             updated_at = excluded.updated_at""",
        (
            submission_id,
            question_id,
            score,
            comment,
            normalized_source,
            normalized_reasoning,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def list_marking_assessments(submission_id):
    conn = get_connection()
    rows = conn.execute(
        """SELECT question_id, score, comment, comment_source, ai_reasoning, updated_at
           FROM marking_assessments
           WHERE submission_id = ?""",
        (submission_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_marking_assessment(submission_id, question_id):
    conn = get_connection()
    conn.execute(
        """DELETE FROM marking_assessments
           WHERE submission_id = ? AND question_id = ?""",
        (submission_id, question_id),
    )
    conn.commit()
    conn.close()


def has_marking_assessments(submission_id):
    conn = get_connection()
    row = conn.execute(
        """SELECT 1
           FROM marking_assessments
           WHERE submission_id = ?
             AND (TRIM(COALESCE(score, '')) != '' OR TRIM(COALESCE(comment, '')) != '')
           LIMIT 1""",
        (submission_id,),
    ).fetchone()
    conn.close()
    return row is not None


def save_eval_case_candidate(
    submission_id,
    question_id,
    question_prompt,
    student_answer,
    marks_label,
    reference_score,
    reference_comment,
    ai_draft_used,
    include_in_eval,
):
    conn = get_connection()
    conn.execute(
        """INSERT INTO eval_case_candidates
           (submission_id, question_id, question_prompt, student_answer, marks_label,
            reference_score, reference_comment, ai_draft_used, include_in_eval, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(submission_id, question_id)
           DO UPDATE SET
             question_prompt = excluded.question_prompt,
             student_answer = excluded.student_answer,
             marks_label = excluded.marks_label,
             reference_score = excluded.reference_score,
             reference_comment = excluded.reference_comment,
             ai_draft_used = excluded.ai_draft_used,
             include_in_eval = excluded.include_in_eval,
             updated_at = excluded.updated_at""",
        (
            submission_id,
            question_id,
            question_prompt,
            student_answer,
            marks_label,
            reference_score,
            reference_comment,
            1 if ai_draft_used else 0,
            1 if include_in_eval else 0,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_eval_case_candidate(submission_id, question_id):
    conn = get_connection()
    row = conn.execute(
        """SELECT submission_id, question_id, include_in_eval, ai_draft_used,
                  reference_score, reference_comment, updated_at
           FROM eval_case_candidates
           WHERE submission_id = ? AND question_id = ?""",
        (submission_id, question_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_eval_case_candidate(submission_id, question_id):
    conn = get_connection()
    conn.execute(
        """DELETE FROM eval_case_candidates
           WHERE submission_id = ? AND question_id = ?""",
        (submission_id, question_id),
    )
    conn.commit()
    conn.close()
