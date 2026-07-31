import json
import os
import random
import shutil
import string
import subprocess
import sys
import tempfile
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, jsonify, session, redirect,
    url_for, send_file, abort, flash
)
from werkzeug.utils import secure_filename

from src import db, storage, email_util, metadata

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-key-change-me")
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # hard ceiling, per-field limits enforced below

with open(Path(__file__).parent / "config.json") as f:
    SUBMISSION_CONFIG = json.load(f)

db.init_db()

AREAS_BY_KEY = {a["key"]: a for a in SUBMISSION_CONFIG["areas"]}

STORAGE_ENV = {
    "STORAGE_BACKEND": os.environ.get("STORAGE_BACKEND", "local"),
    "LOCAL_UPLOAD_ROOT": os.environ.get("LOCAL_UPLOAD_ROOT", "uploads"),
    "DROPBOX_APP_KEY": os.environ.get("DROPBOX_APP_KEY"),
    "DROPBOX_APP_SECRET": os.environ.get("DROPBOX_APP_SECRET"),
    "DROPBOX_REFRESH_TOKEN": os.environ.get("DROPBOX_REFRESH_TOKEN"),
    "DROPBOX_ROOT_FOLDER": os.environ.get("DROPBOX_ROOT_FOLDER", "/Submissions"),
    "ONEDRIVE_TENANT_ID": os.environ.get("ONEDRIVE_TENANT_ID"),
    "ONEDRIVE_CLIENT_ID": os.environ.get("ONEDRIVE_CLIENT_ID"),
    "ONEDRIVE_CLIENT_SECRET": os.environ.get("ONEDRIVE_CLIENT_SECRET"),
    "ONEDRIVE_DRIVE_ID": os.environ.get("ONEDRIVE_DRIVE_ID"),
    "ONEDRIVE_ROOT_FOLDER": os.environ.get("ONEDRIVE_ROOT_FOLDER", "/Submissions"),
}

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # excludes 0/O, 1/I to avoid confusion


def generate_code():
    for _ in range(50):
        code = "".join(random.choices(CODE_ALPHABET, k=4))
        if not db.code_exists(code):
            return code
    raise RuntimeError("Could not generate a unique code, database may be full of codes.")


def get_client_ip():
    # Respect X-Forwarded-For if the app sits behind a reverse proxy (Nginx),
    # otherwise fall back to the direct connection IP.
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


def validate_file(area, file_storage):
    ext = Path(file_storage.filename).suffix.lower()
    if ext not in area["allowed_extensions"]:
        return f"'{file_storage.filename}' has an invalid file type for {area['label']} (allowed: {', '.join(area['allowed_extensions'])})."

    file_storage.stream.seek(0, os.SEEK_END)
    size_bytes = file_storage.stream.tell()
    file_storage.stream.seek(0)
    max_bytes = area["max_size_mb"] * 1024 * 1024
    if size_bytes > max_bytes:
        return f"'{file_storage.filename}' exceeds the {area['max_size_mb']}MB limit for {area['label']}."
    if size_bytes == 0:
        return f"'{file_storage.filename}' is empty."
    return None


# ---------- Public submission routes ----------

@app.route("/")
def index():
    return render_template(
        "index.html",
        assignment_title=SUBMISSION_CONFIG["assignment_title"],
        areas=SUBMISSION_CONFIG["areas"],
    )


@app.route("/api/config")
def api_config():
    return jsonify(SUBMISSION_CONFIG)


@app.route("/api/submit", methods=["POST"])
def api_submit():
    name = request.form.get("name", "").strip()
    student_id = request.form.get("student_id", "").strip()
    email = request.form.get("email", "").strip()

    errors = []
    if not name:
        errors.append("Name is required.")
    if not student_id:
        errors.append("Student ID is required.")
    if not email:
        errors.append("Email is required for the confirmation email.")

    # Validate every configured area: satisfied by either an attached file, or
    # the "I declare that I did not upload this file" checkbox.
    files_by_area = {}
    declared_areas = []
    for area in SUBMISSION_CONFIG["areas"]:
        key = area["key"]
        declared = request.form.get(f"{key}_declared") == "true"
        uploaded = request.files.getlist(key)
        uploaded = [f for f in uploaded if f and f.filename]

        if declared:
            if uploaded:
                errors.append(
                    f"You attached a file for '{area['label']}' but also marked it as "
                    f"not submitted. Please remove the file or untick the box."
                )
                continue
            declared_areas.append(area)
            continue

        if len(uploaded) == 0:
            errors.append(
                f"Please attach a file for '{area['label']}', or tick the box "
                f"confirming you did not submit it."
            )
            continue
        if len(uploaded) > area["max_files"]:
            errors.append(f"Only {area['max_files']} file(s) allowed for '{area['label']}'.")
            continue

        for f in uploaded:
            err = validate_file(area, f)
            if err:
                errors.append(err)

        files_by_area[key] = uploaded

    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    # Everything valid - persist to a temp dir, then hand off to storage backend
    code = generate_code()
    dest_folder = f"{student_id}_{secure_filename(name)}_{code}"
    primary_backend, fallback_backend = storage.get_storage_backend(STORAGE_ENV)

    submission_id = db.create_submission(
        name=name, student_id=student_id, code=code,
        ip_address=get_client_ip(), user_agent=request.headers.get("User-Agent", ""),
        email=email, storage_backend=primary_backend.name,
    )

    saved_filenames = []
    used_fallback = False

    with tempfile.TemporaryDirectory() as tmpdir:
        for area_key, files in files_by_area.items():
            area = AREAS_BY_KEY[area_key]
            for f in files:
                safe_name = secure_filename(f.filename)
                tmp_path = Path(tmpdir) / safe_name
                f.save(tmp_path)

                area_folder = f"{dest_folder}/{area_key}"
                try:
                    result = primary_backend.upload_file(tmp_path, area_folder, safe_name)
                except storage.StorageError:
                    result = fallback_backend.upload_file(tmp_path, area_folder, safe_name)
                    used_fallback = True

                file_metadata = metadata.extract_file_metadata(
                    tmp_path, f.filename, area_key
                )
                metadata_path = (
                    Path(STORAGE_ENV["LOCAL_UPLOAD_ROOT"])
                    / dest_folder
                    / "metadata"
                    / f"{area_key}_{safe_name}.json"
                )
                metadata.write_metadata(metadata_path, file_metadata)

                db.add_submission_file(
                    submission_id=submission_id, area_key=area_key, area_label=area["label"],
                    original_filename=f.filename, stored_filename=safe_name,
                    storage_location=result["location"], size_bytes=tmp_path.stat().st_size,
                )
                saved_filenames.append(f.filename)

                if area_key == "ampl_code" and tmp_path.suffix.lower() == ".zip":
                    extract_root = Path(tmpdir) / "ampl_extracted"
                    try:
                        extracted_files = metadata.extract_ampl_archive(tmp_path, extract_root)
                    except (metadata.zipfile.BadZipFile, OSError) as error:
                        app.logger.warning("AMPL archive extraction failed for submission %s: %s", submission_id, error)
                        extracted_files = []

                    for extracted_path, archive_name in extracted_files:
                        relative_path = extracted_path.relative_to(extract_root)
                        extracted_folder = f"{area_folder}/{relative_path.parent.as_posix()}"
                        extracted_name = extracted_path.name
                        try:
                            extracted_result = primary_backend.upload_file(
                                extracted_path, extracted_folder, extracted_name
                            )
                        except storage.StorageError:
                            extracted_result = fallback_backend.upload_file(
                                extracted_path, extracted_folder, extracted_name
                            )
                            used_fallback = True

                        extracted_metadata = metadata.extract_file_metadata(
                            extracted_path, archive_name, area_key
                        )
                        extracted_metadata["extracted_from"] = f.filename
                        extracted_metadata_path = (
                            Path(STORAGE_ENV["LOCAL_UPLOAD_ROOT"])
                            / dest_folder
                            / "metadata"
                            / f"{area_key}_{relative_path.as_posix().replace('/', '_')}.json"
                        )
                        metadata.write_metadata(extracted_metadata_path, extracted_metadata)
                        db.add_submission_file(
                            submission_id=submission_id, area_key=area_key, area_label=area["label"],
                            original_filename=archive_name, stored_filename=extracted_name,
                            storage_location=extracted_result["location"],
                            size_bytes=extracted_path.stat().st_size,
                        )

    for area in declared_areas:
        db.add_declaration(submission_id, area["key"], area["label"])

    if used_fallback:
        conn = db.get_connection()
        conn.execute(
            "UPDATE submissions SET storage_backend = ?, storage_note = ? WHERE id = ?",
            (fallback_backend.name, "Primary storage backend failed; saved locally instead.", submission_id),
        )
        conn.commit()
        conn.close()

    email_sent = False
    try:
        email_util.send_confirmation_email(
            gmail_address=os.environ.get("GMAIL_ADDRESS"),
            gmail_app_password=os.environ.get("GMAIL_APP_PASSWORD"),
            from_name=os.environ.get("EMAIL_FROM_NAME", "Assignment Submission System"),
            to_address=email, name=name, student_id=student_id, code=code,
            filenames=saved_filenames, assignment_title=SUBMISSION_CONFIG["assignment_title"],
            declared_labels=[a["label"] for a in declared_areas],
        )
        email_sent = True
        db.mark_email_sent(submission_id, True)
    except Exception as e:
        app.logger.warning(f"Email send failed for submission {submission_id}: {e}")

    return jsonify({
        "ok": True,
        "code": code,
        "email_sent": email_sent,
        "storage_note": "Saved locally (cloud storage unavailable)." if used_fallback else None,
    })


# ---------- Admin auth ----------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if (username == os.environ.get("ADMIN_USERNAME") and
                password == os.environ.get("ADMIN_PASSWORD") and
                os.environ.get("ADMIN_PASSWORD")):
            session["admin_logged_in"] = True
            next_url = request.args.get("next") or url_for("admin_dashboard")
            return redirect(next_url)
        flash("Invalid username or password.")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# ---------- Admin dashboard ----------

@app.route("/admin")
@login_required
def admin_dashboard():
    search = request.args.get("q", "").strip()
    submissions = db.list_submissions(search=search or None)
    return render_template(
        "admin_dashboard.html", submissions=submissions, search=search,
        assignment_title=SUBMISSION_CONFIG["assignment_title"],
    )


@app.route("/admin/submission/<int:submission_id>")
@login_required
def admin_submission_detail(submission_id):
    submission = db.get_submission(submission_id)
    if not submission:
        abort(404)
    return render_template("admin_detail.html", submission=submission)


@app.route("/admin/submission/<int:submission_id>/analysis", methods=["GET", "POST"])
@login_required
def admin_submission_analysis(submission_id):
    submission = db.get_submission(submission_id)
    if not submission:
        abort(404)

    if request.method == "POST":
        run_files = []
        seen_paths = set()
        for file in submission["files"]:
            path = Path(file["storage_location"])
            if path.suffix.lower() == ".run" and not path.name.startswith(".") and path.exists():
                resolved = path.resolve()
                if resolved not in seen_paths:
                    run_files.append(resolved)
                    seen_paths.add(resolved)

        if not run_files:
            flash("No runnable .run files were found in this submission.")
            return redirect(url_for("admin_submission_analysis", submission_id=submission_id))

        timeout_seconds = int(os.environ.get("AMPL_RUN_TIMEOUT_SECONDS", "120"))
        runner = Path(__file__).parent / "analysis_runner.py"
        ampl_python = os.environ.get("AMPL_PYTHON", sys.executable)
        submission_root = run_files[0].parents[1]
        result_root = submission_root / "analysis"
        for run_path in run_files:
            result_directory = result_root / secure_filename(run_path.stem)
            result_directory.mkdir(parents=True, exist_ok=True)
            run_id = db.create_analysis_run(
                submission_id, run_path.name, str(result_directory)
            )
            result = {}
            try:
                completed = subprocess.run(
                    [ampl_python, str(runner), str(run_path), str(run_path.parent), str(result_directory)],
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=False,
                )
                try:
                    result = json.loads(completed.stdout.strip().splitlines()[-1])
                except (json.JSONDecodeError, IndexError):
                    result = {
                        "stderr": completed.stderr,
                        "error": "The AMPL worker returned an invalid result.",
                        "statistics": {},
                    }
                status = "completed" if result.get("status") == "completed" else "failed"
            except subprocess.TimeoutExpired as error:
                timeout_stdout = error.stdout or ""
                timeout_stderr = error.stderr or ""
                if isinstance(timeout_stdout, bytes):
                    timeout_stdout = timeout_stdout.decode(errors="replace")
                if isinstance(timeout_stderr, bytes):
                    timeout_stderr = timeout_stderr.decode(errors="replace")
                result = {
                    "error": f"AMPL execution exceeded the {timeout_seconds}-second timeout.",
                    "stdout": timeout_stdout,
                    "stderr": timeout_stderr,
                    "statistics": {},
                }
                status = "timed_out"
            except OSError as error:
                result = {
                    "error": f"Could not start AMPL Python interpreter '{ampl_python}'.",
                    "stderr": str(error),
                    "statistics": {},
                    "diagnostics": {"python_executable": ampl_python},
                }
                status = "failed"
            db.update_analysis_run(run_id, status, result)

        flash(f"AMPL analysis completed for {len(run_files)} run file(s).")
        return redirect(url_for("admin_submission_analysis", submission_id=submission_id))

    return render_template("admin_analysis.html", submission=submission)


@app.route("/admin/submission/<int:submission_id>/analysis/<int:run_id>/delete", methods=["POST"])
@login_required
def admin_delete_analysis_run(submission_id, run_id):
    submission = db.get_submission(submission_id)
    if not submission:
        abort(404)

    run = next((item for item in submission["analysis_runs"] if item["id"] == run_id), None)
    if not run:
        abort(404)

    result_location = Path(run["result_location"]).resolve()
    submission_root = Path(STORAGE_ENV["LOCAL_UPLOAD_ROOT"]).resolve()
    db.delete_analysis_run(run_id, submission_id)
    if submission_root in result_location.parents:
        shutil.rmtree(result_location)

    flash(f"Analysis run '{run['run_filename']}' was deleted.")
    return redirect(url_for("admin_submission_analysis", submission_id=submission_id))


@app.route("/admin/submission/<int:submission_id>/metadata")
@login_required
def admin_submission_metadata(submission_id):
    submission = db.get_submission(submission_id)
    if not submission:
        abort(404)

    metadata_entries = []
    local_files = [Path(file["storage_location"]) for file in submission["files"]]
    if local_files:
        metadata_folder = local_files[0].parents[1] / "metadata"
        for metadata_path in sorted(metadata_folder.glob("*.json")):
            try:
                data = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata_entries.append({
                    "filename": data.get("original_filename", metadata_path.name),
                    "data": data,
                })
            except (OSError, json.JSONDecodeError):
                continue

    return render_template(
        "admin_metadata.html", submission=submission, metadata_entries=metadata_entries
    )


@app.route("/admin/submission/<int:submission_id>/delete", methods=["POST"])
@login_required
def admin_delete_submission(submission_id):
    submission = db.get_submission(submission_id)
    if not submission:
        abort(404)

    local_files = [Path(file["storage_location"]) for file in submission["files"]]
    db.delete_submission(submission_id)

    if local_files:
        upload_root = Path(STORAGE_ENV["LOCAL_UPLOAD_ROOT"]).resolve()
        submission_folder = local_files[0].resolve().parents[1]
        if upload_root in submission_folder.parents:
            shutil.rmtree(submission_folder)

    flash(f"Submission #{submission_id} was deleted.")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/download/<int:file_id>")
@login_required
def admin_download_file(file_id):
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM submission_files WHERE id = ?", (file_id,)).fetchone()
    conn.close()
    if not row:
        abort(404)
    row = dict(row)
    # Only local-backend files can be served directly; cloud files are opened via the provider.
    path = Path(row["storage_location"])
    if not path.exists():
        abort(404, "File not found on local storage (it may be stored in the cloud backend instead).")
    return send_file(path, as_attachment=True, download_name=row["original_filename"])


if __name__ == "__main__":
    db.init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
