"""Validation helpers for public submission inputs."""

import os
from urllib import parse as urlparse
from pathlib import Path


def validate_file(area, file_storage):
    """Validate an uploaded file against its configured type and size limits."""
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


def validate_url(area, url_value):
    """Validate that a submission URL is a complete HTTP or HTTPS link."""
    value = str(url_value or "").strip()
    if not value:
        return f"Please provide a URL for '{area['label']}'."

    parsed = urlparse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return f"'{value}' is not a valid URL for '{area['label']}'. Use a full http(s) link."
    return None
