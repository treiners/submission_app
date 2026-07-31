"""Extract non-destructive metadata from uploaded submission files."""
import hashlib
import json
import mimetypes
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree


CORE_PROPERTIES = {
    "title": "title",
    "subject": "subject",
    "creator": "creator",
    "keywords": "keywords",
    "description": "description",
    "lastModifiedBy": "last_modified_by",
    "revision": "revision",
    "created": "created",
    "modified": "modified",
    "category": "category",
    "contentStatus": "content_status",
    "language": "language",
    "version": "version",
}


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(element):
    return (element.text or "").strip()


def _word_metadata(path):
    """Read Word core properties and document structure from OOXML parts."""
    result = {}
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        result["package_entries"] = len(names)
        result["has_macros"] = any(
            name.lower().endswith("vbaproject.bin") for name in names
        )

        if "docProps/core.xml" in names:
            root = ElementTree.fromstring(archive.read("docProps/core.xml"))
            for element in root:
                key = CORE_PROPERTIES.get(element.tag.rsplit("}", 1)[-1])
                if key and _text(element):
                    result[key] = _text(element)

        if "word/document.xml" in names:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
            tags = [element.tag.rsplit("}", 1)[-1] for element in root.iter()]
            result["paragraph_count"] = tags.count("p")
            result["table_count"] = tags.count("tbl")
            result["image_count"] = sum(
                tag in {"blip", "imagedata"} for tag in tags
            )
            result["hyperlink_count"] = tags.count("hyperlink")
            result["word_count"] = sum(
                len(_text(element).split())
                for element in root.iter()
                if element.tag.rsplit("}", 1)[-1] == "t"
            )

    return result


def extract_file_metadata(path, original_filename, area_key):
    """Return JSON-serializable metadata without changing the uploaded file."""
    path = Path(path)
    stat = path.stat()
    metadata = {
        "original_filename": original_filename,
        "stored_filename": path.name,
        "area_key": area_key,
        "extension": path.suffix.lower(),
        "mime_type": mimetypes.guess_type(original_filename)[0] or "application/octet-stream",
        "size_bytes": stat.st_size,
        "sha256": _sha256(path),
        "file_created_at": datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat(),
        "file_modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "metadata_collected_at": datetime.now(timezone.utc).isoformat(),
    }

    if path.suffix.lower() == ".docx":
        try:
            metadata["word"] = _word_metadata(path)
        except (ElementTree.ParseError, KeyError, zipfile.BadZipFile) as error:
            metadata["word_error"] = str(error)

    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                metadata["archive"] = {
                    "entry_count": len(archive.infolist()),
                    "entries": [info.filename for info in archive.infolist()],
                }
        except zipfile.BadZipFile as error:
            metadata["archive_error"] = str(error)

    return metadata


def write_metadata(path, metadata):
    """Write metadata as readable UTF-8 JSON to a local sidecar file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
