"""Prepare extracted file metadata for the admin display."""

from datetime import datetime


_FIELD_LABELS = {
    "original_filename": "Original filename",
    "stored_filename": "Stored filename",
    "area_key": "Submission area",
    "extension": "File type",
    "mime_type": "MIME type",
    "size_bytes": "Size",
    "file_created_at": "Created",
    "file_modified_at": "Modified",
    "metadata_collected_at": "Metadata collected",
    "sha256": "SHA-256",
    "question_scope": "Question scope",
    "extracted_from": "Extracted from",
}

_WORD_FIELD_LABELS = {
    "title": "Title",
    "subject": "Subject",
    "creator": "Author",
    "last_modified_by": "Last modified by",
    "keywords": "Keywords",
    "description": "Description",
    "created": "Document created",
    "modified": "Document modified",
    "language": "Language",
    "word_count": "Word count",
    "paragraph_count": "Paragraphs",
    "table_count": "Tables",
    "image_count": "Images",
    "hyperlink_count": "Hyperlinks",
    "package_entries": "Package entries",
    "has_macros": "Contains macros",
}


def _format_bytes(value):
    try:
        size = float(value)
    except (TypeError, ValueError):
        return str(value)

    units = ("B", "KB", "MB", "GB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return str(value)


def _format_timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return str(value)

    formatted = parsed.strftime("%d %b %Y, %H:%M")
    return f"{formatted} UTC" if parsed.tzinfo else formatted


def _format_value(key, value):
    if key == "size_bytes":
        return _format_bytes(value)
    if key.endswith("_at") or key in {"created", "modified"}:
        return _format_timestamp(value)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "None"
    if value in (None, ""):
        return "Not recorded"
    return str(value)


def _rows(data, fields):
    rows = []
    for key, label in fields.items():
        if key in data and data[key] not in (None, ""):
            rows.append({"label": label, "value": _format_value(key, data[key])})
    return rows


def build_metadata_display(data):
    """Return grouped, human-readable sections for one metadata record."""
    sections = []

    file_rows = _rows(data, _FIELD_LABELS)
    if file_rows:
        sections.append({"title": "File summary", "rows": file_rows})

    word_data = data.get("word")
    if isinstance(word_data, dict):
        word_rows = _rows(word_data, _WORD_FIELD_LABELS)
        if word_rows:
            sections.append({"title": "Word document", "rows": word_rows})

    archive_data = data.get("archive")
    if isinstance(archive_data, dict):
        archive_rows = _rows(archive_data, {"entry_count": "Archive entries"})
        sections.append({
            "title": "Archive",
            "rows": archive_rows,
            "list_title": "Contained files",
            "list_items": archive_data.get("entries", []),
        })

    technical_keys = {"revision", "category", "content_status", "version"}
    technical_data = {key: data[key] for key in technical_keys if key in data}
    technical_rows = _rows(technical_data, {
        "revision": "Revision",
        "category": "Category",
        "content_status": "Content status",
        "version": "Version",
    })
    if technical_rows:
        sections.append({"title": "Additional details", "rows": technical_rows})

    return sections
