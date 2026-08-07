"""Extract non-destructive metadata from uploaded submission files."""
import base64
import difflib
import hashlib
import json
import mimetypes
import re
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

MARKS_PATTERN = re.compile(r"\((?:\d+\s*M|\d+\s*MARKS?)\)", re.IGNORECASE)
DOCX_MEDIA_PREFIX = "word/media/"
DOCX_NAMESPACE = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
DOCX_REL_NAMESPACE = {
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
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


def extract_ampl_archive(path, destination):
    """Extract an AMPL ZIP without allowing paths to escape destination."""
    path = Path(path)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    extracted = []
    used_names = set()
    allowed_extensions = {".mod", ".dat", ".run"}

    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue

            source_name = Path(info.filename)
            filename = source_name.name
            if not filename or any(part.startswith(".") for part in source_name.parts):
                continue

            folder = destination if source_name.suffix.lower() in allowed_extensions else destination / "other"
            folder.mkdir(parents=True, exist_ok=True)
            safe_name = filename
            stem = Path(safe_name).stem
            suffix = Path(safe_name).suffix
            counter = 1
            while (str(folder), safe_name) in used_names or (folder / safe_name).exists():
                safe_name = f"{stem}_{counter}{suffix}"
                counter += 1

            target = folder / safe_name
            with archive.open(info) as source, target.open("wb") as output:
                output.write(source.read())
            used_names.add((str(folder), safe_name))
            extracted.append((target, info.filename))

    return extracted


def _docx_paragraph_records(path):
    """Return paragraph records with text and embedded image filenames."""
    records = []
    with zipfile.ZipFile(path) as archive:
        rel_map = {}
        if "word/_rels/document.xml.rels" in archive.namelist():
            rel_root = ElementTree.fromstring(archive.read("word/_rels/document.xml.rels"))
            for rel in rel_root.findall("rel:Relationship", DOCX_REL_NAMESPACE):
                rel_map[rel.attrib.get("Id", "")] = rel.attrib.get("Target", "")

        root = ElementTree.fromstring(archive.read("word/document.xml"))
        for paragraph in root.findall(".//w:p", DOCX_NAMESPACE):
            text_parts = [
                node.text for node in paragraph.findall(".//w:t", DOCX_NAMESPACE)
                if node.text and node.text.strip()
            ]
            joined = "".join(text_parts).strip()

            image_filenames = []
            for blip in paragraph.findall(".//a:blip", DOCX_NAMESPACE):
                rid = blip.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                target = rel_map.get(rid or "", "")
                if not target:
                    continue
                image_name = Path(target).name
                if image_name:
                    image_filenames.append(image_name)

            if joined or image_filenames:
                records.append({
                    "text": joined,
                    "images": image_filenames,
                })
    return records


def _docx_paragraphs(path):
    """Return non-empty paragraph text from a DOCX document body."""
    return [record["text"] for record in _docx_paragraph_records(path) if record["text"]]


def _docx_images(path, max_images=12, max_total_bytes=8 * 1024 * 1024):
    """Extract embedded DOCX images as base64 payloads for preview rendering."""
    images = []
    total_bytes = 0
    with zipfile.ZipFile(path) as archive:
        media_entries = [
            item for item in archive.infolist()
            if item.filename.startswith(DOCX_MEDIA_PREFIX) and not item.is_dir()
        ]
        media_entries.sort(key=lambda item: item.filename.lower())

        for info in media_entries:
            if len(images) >= max_images:
                break

            raw = archive.read(info.filename)
            if not raw:
                continue

            if total_bytes + len(raw) > max_total_bytes:
                break
            total_bytes += len(raw)

            extension = Path(info.filename).suffix.lower()
            content_type = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".bmp": "image/bmp",
                ".tif": "image/tiff",
                ".tiff": "image/tiff",
                ".webp": "image/webp",
            }.get(extension, "application/octet-stream")

            images.append({
                "filename": Path(info.filename).name,
                "content_type": content_type,
                "size_bytes": len(raw),
                "data_base64": base64.b64encode(raw).decode("ascii"),
            })

    return images


def _is_question_prompt(line):
    line = line.strip()
    if not line:
        return False

    lowered = line.lower()
    if lowered.startswith(("question ", "note:", "naming of files:", "submission:", "important:")):
        return False

    return line.endswith("?") or bool(MARKS_PATTERN.search(line))


def _extract_marks_label(prompt):
    match = MARKS_PATTERN.search(prompt or "")
    if not match:
        return None
    return match.group(0).strip("()")


def _estimate_answer_confidence(answer_paragraphs, unmatched_count):
    """Return a simple confidence estimate for answer extraction quality."""
    char_count = sum(len(line.strip()) for line in answer_paragraphs)
    paragraph_count = len([line for line in answer_paragraphs if line.strip()])

    score = 1.0
    reasons = []

    if paragraph_count == 0:
        score = 0.2
        reasons.append("No non-empty answer paragraph was found.")
    elif char_count < 40:
        score -= 0.35
        reasons.append("Answer text is short; mapping may be weak.")
    elif char_count < 120:
        score -= 0.15
        reasons.append("Answer text is moderate length.")

    if unmatched_count > 0:
        score -= min(0.3, 0.1 * unmatched_count)
        reasons.append("Some inserted text could not be tied to a question.")

    score = max(0.0, min(1.0, score))
    if score >= 0.85:
        level = "high"
    elif score >= 0.6:
        level = "medium"
    else:
        level = "low"

    return {
        "score": round(score, 3),
        "level": level,
        "reasons": reasons,
        "char_count": char_count,
        "paragraph_count": paragraph_count,
    }


def resolve_marking_template_docx(project_root, submission_config):
    """Locate the active DOCX template used for extraction."""
    project_root = Path(project_root)
    configured = submission_config.get("marking_template_docx")
    if configured:
        configured_path = Path(configured)
        if not configured_path.is_absolute():
            configured_path = project_root / configured_path
        return configured_path if configured_path.exists() else None

    for folder_name in ("making_template", "marking_template"):
        folder = project_root / folder_name
        if not folder.exists():
            continue
        matches = sorted(folder.glob("marking_template*.docx"))
        if matches:
            return matches[0]
    return None


def extract_answers_with_template(submission_docx, template_docx):
    """Extract free-text answers by comparing a filled DOCX to a template DOCX."""
    template_lines = _docx_paragraphs(template_docx)
    submission_lines = _docx_paragraphs(submission_docx)

    def normalize_prompt_line(value):
        value = (value or "").strip().lower()
        value = re.sub(r"\s+", " ", value)
        value = re.sub(r"\s+\(", "(", value)
        return value

    matcher = difflib.SequenceMatcher(a=template_lines, b=submission_lines, autojunk=False)
    prompt_order = []
    prompt_index = {}
    answer_blocks = {}
    unmatched_insertions = []
    pending_prompts = []
    known_prompts = [line for line in template_lines if _is_question_prompt(line)]
    prompt_lookup = {
        normalize_prompt_line(prompt): prompt
        for prompt in known_prompts
    }

    def register_prompt(line):
        if line not in prompt_index:
            prompt_index[line] = len(prompt_order) + 1
            prompt_order.append(line)

    def consume_inserted_lines(inserted_lines):
        if not inserted_lines:
            return

        current_target = pending_prompts.pop(0) if pending_prompts else None
        chunk = []

        def flush_chunk(target_prompt, lines):
            if not lines:
                return
            if target_prompt:
                answer_blocks.setdefault(target_prompt, []).append(lines[:])
            else:
                unmatched_insertions.append(lines[:])

        for line in inserted_lines:
            normalized = normalize_prompt_line(line)
            matched_prompt = prompt_lookup.get(normalized)
            if matched_prompt:
                flush_chunk(current_target, chunk)
                chunk = []
                register_prompt(matched_prompt)
                current_target = matched_prompt
                if matched_prompt in pending_prompts:
                    pending_prompts.remove(matched_prompt)
                continue

            chunk.append(line)

        flush_chunk(current_target, chunk)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"equal", "replace", "delete"}:
            for line in template_lines[i1:i2]:
                if _is_question_prompt(line):
                    register_prompt(line)
                    pending_prompts.append(line)

        if tag in {"insert", "replace"}:
            inserted = [line for line in submission_lines[j1:j2] if line.strip()]
            if not inserted:
                continue
            consume_inserted_lines(inserted)

    answers = []
    for prompt in prompt_order:
        blocks = answer_blocks.get(prompt)
        if not blocks:
            continue
        flat = []
        for block in blocks:
            flat.extend(block)
        answers.append({
            "question_id": f"Q{len(answers) + 1}",
            "template_question_id": f"Q{prompt_index[prompt]}",
            "prompt": prompt,
            "marks_label": _extract_marks_label(prompt),
            "answer": "\n".join(flat),
            "answer_paragraphs": flat,
        })

    unmatched = ["\n".join(block) for block in unmatched_insertions]

    unmatched_count = len(unmatched_insertions)
    for answer in answers:
        answer["confidence"] = _estimate_answer_confidence(
            answer.get("answer_paragraphs", []),
            unmatched_count,
        )

    return {
        "answer_count": len(answers),
        "answers": answers,
        "unmatched_insertions": unmatched,
    }


def _attach_images_to_answers(submission_docx, answers, images):
    """Attach image references to the answer whose prompt appears above the image."""
    if not answers or not images:
        return

    records = _docx_paragraph_records(submission_docx)
    normalize = lambda value: " ".join((value or "").split()).lower()
    prompt_to_question = {
        normalize(answer["prompt"]): answer["question_id"]
        for answer in answers
    }

    image_by_name = {image["filename"]: image for image in images}
    question_to_image_names = {answer["question_id"]: [] for answer in answers}

    active_question = None
    for record in records:
        norm_text = normalize(record.get("text", ""))
        if norm_text in prompt_to_question:
            active_question = prompt_to_question[norm_text]
        if active_question and record.get("images"):
            question_to_image_names[active_question].extend(record["images"])

    for answer in answers:
        seen = set()
        linked = []
        for filename in question_to_image_names.get(answer["question_id"], []):
            if filename in seen:
                continue
            image = image_by_name.get(filename)
            if image:
                linked.append(image)
                seen.add(filename)
        answer["images"] = linked


def extract_marking_preview(submission_docx, submission_config, project_root):
    """Build the JSON payload consumed by the admin marking preview page."""
    template_docx = resolve_marking_template_docx(project_root, submission_config)
    if not template_docx:
        return {
            "status": "skipped",
            "reason": "No marking template DOCX was found.",
        }

    extraction = extract_answers_with_template(submission_docx, template_docx)
    max_images = int(submission_config.get("marking_preview_max_images", 12))
    images = _docx_images(submission_docx, max_images=max_images)
    _attach_images_to_answers(submission_docx, extraction.get("answers", []), images)
    return {
        "status": "ok",
        "template_file": str(template_docx),
        "submission_file": str(Path(submission_docx)),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "image_count": len(images),
        "images": images,
        **extraction,
    }
