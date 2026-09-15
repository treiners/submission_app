"""Local filesystem path resolution for stored submissions."""

from pathlib import Path

from werkzeug.utils import secure_filename


def submission_metadata_folder(submission_record):
    """Return the local metadata folder for a submission, if available."""
    local_files = [Path(file["storage_location"]) for file in submission_record.get("files", [])]
    if not local_files:
        return None
    return local_files[0].parents[1] / "metadata"


def submission_root_folder(submission_record):
    """Return the local root folder for a submission, if available."""
    local_files = [Path(file["storage_location"]) for file in submission_record.get("files", [])]
    if not local_files:
        return None
    return local_files[0].parents[1]


def submission_folder_name(submission_record):
    """Build the local folder name used for a submission."""
    name = str(submission_record.get("name") or "").strip()
    student_id = str(submission_record.get("student_id") or "").strip()
    code = str(submission_record.get("code") or "").strip()
    if not student_id:
        student_id = "unknown_student"
    if not code:
        code = "unknown_code"
    folder_name = f"{student_id}_{secure_filename(name) or 'student'}_{code}"
    return folder_name.strip("_") or "submission"


def resolve_submission_upload_root(submission_record, base_upload_root, project_root):
    """Resolve the existing local upload root or derive its expected path."""
    base_upload_root = Path(base_upload_root).resolve()
    project_root = Path(project_root)
    for file_record in submission_record.get("files", []):
        storage_location = str(file_record.get("storage_location") or "").strip()
        if not storage_location:
            continue

        candidate = Path(storage_location)
        if not candidate.is_absolute():
            candidate = (project_root / candidate).resolve()
        else:
            candidate = candidate.resolve()

        try:
            resolved_parent = candidate.parents[1]
        except IndexError:
            resolved_parent = candidate.parent

        if resolved_parent.exists() or candidate.name:
            return resolved_parent

    return base_upload_root / submission_folder_name(submission_record)


def resolve_submission_relative_file(submission_record, relative_path):
    """Resolve a submission-relative file while preventing path traversal."""
    submission_root = submission_root_folder(submission_record)
    if not submission_root:
        return None

    try:
        resolved_root = submission_root.resolve()
        candidate = (resolved_root / relative_path).resolve()
        candidate.relative_to(resolved_root)
    except (OSError, ValueError):
        return None

    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate
