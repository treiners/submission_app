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
QUESTION_HEADING_PATTERN = re.compile(r"^\s*(?:q(?:uestion)?\s*)?\d{1,2}\s*[\).:-]\s*")
DOCX_MEDIA_PREFIX = "word/media/"
DOCX_NAMESPACE = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
DOCX_REL_NAMESPACE = {
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
IMAGE_ONLY_DEFAULT_ANSWER = "The answer contained only an image"
IMAGE_PROMPT_KEYWORDS = ("image", "photo", "screenshot", "scan")
TEMPLATE_MARKER_START_PATTERN = re.compile(
    r"^\[(Q\d+)\s*:\s*(.*?)\s*M\s*:\s*(\d+)\]$",
    re.IGNORECASE,
)
TEMPLATE_MARKER_END_PATTERN = re.compile(
    r"^\[(Q\d+)\s*:?[\s]+END\]$",
    re.IGNORECASE,
)
SUBMISSION_MARKER_START_PATTERN = re.compile(
    r"^\[(Q\d+)\s*:\s*.*\]$",
    re.IGNORECASE,
)
SUBMISSION_MARKER_END_PATTERN = re.compile(
    r"^\[(Q\d+)\s*:?[\s]+END\]$",
    re.IGNORECASE,
)


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


def _normalize_prompt_line(value):
    value = (value or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+\(", "(", value)
    return value


def _canonicalize_text(value):
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value


def _tokenize_text(value):
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def _looks_like_question_boundary(line):
    stripped = (line or "").strip()
    if not stripped:
        return False
    if QUESTION_HEADING_PATTERN.match(stripped):
        return True
    if MARKS_PATTERN.search(stripped):
        return True
    if stripped.endswith("?"):
        return True
    return False


def _best_fuzzy_prompt_match(line, known_prompts, minimum_ratio=0.86):
    """Return the closest template prompt for a boundary-like line, if reliable."""
    if not _looks_like_question_boundary(line):
        return None

    candidate = _canonicalize_text(line)
    if not candidate:
        return None

    best_prompt = None
    best_ratio = 0.0
    for prompt in known_prompts:
        prompt_canonical = _canonicalize_text(prompt)
        if not prompt_canonical:
            continue

        # Handle common student edits where only the first part of the prompt is kept.
        shorter = min(len(candidate), len(prompt_canonical))
        longer = max(len(candidate), len(prompt_canonical))
        if shorter >= 30 and longer > 0:
            if candidate in prompt_canonical or prompt_canonical in candidate:
                coverage = shorter / longer
                if coverage >= 0.6:
                    return prompt

        ratio = difflib.SequenceMatcher(a=prompt_canonical, b=candidate, autojunk=False).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_prompt = prompt

    if best_ratio >= minimum_ratio:
        return best_prompt
    return None


def _match_prompt_boundary(line, prompt_lookup, known_prompts):
    normalized = _normalize_prompt_line(line)
    exact = prompt_lookup.get(normalized)
    if exact:
        return exact, ""

    line_tokens = _tokenize_text(line)
    best_prefix_prompt = None
    best_prefix_remainder = ""
    best_prefix_token_count = -1

    for prompt in known_prompts:
        prompt_tokens = _tokenize_text(prompt)
        if len(prompt_tokens) < 6:
            continue
        if len(line_tokens) <= len(prompt_tokens):
            continue

        matched = 0
        max_compare = min(len(line_tokens), len(prompt_tokens))
        while matched < max_compare and line_tokens[matched] == prompt_tokens[matched]:
            matched += 1

        coverage = matched / len(prompt_tokens)
        if coverage < 0.85:
            continue

        if matched > best_prefix_token_count:
            best_prefix_token_count = matched
            best_prefix_prompt = prompt
            best_prefix_remainder = " ".join(line_tokens[matched:]).strip()

    if best_prefix_prompt:
        return best_prefix_prompt, best_prefix_remainder

    fuzzy = _best_fuzzy_prompt_match(line, known_prompts)
    if fuzzy:
        return fuzzy, ""
    return None, ""


def _apply_confidence_penalty(confidence, penalty, reason):
    score = max(0.0, min(1.0, float(confidence.get("score", 0.0)) - penalty))
    confidence["score"] = round(score, 3)
    if reason and reason not in confidence.get("reasons", []):
        confidence.setdefault("reasons", []).append(reason)

    if score >= 0.85:
        confidence["level"] = "high"
    elif score >= 0.6:
        confidence["level"] = "medium"
    else:
        confidence["level"] = "low"


def _detect_cross_prompt_drift(answers):
    """Flag answers that appear to include a different question prompt."""
    prompt_map = {
        answer.get("question_id"): answer.get("prompt", "")
        for answer in answers
        if answer.get("question_id") and answer.get("prompt")
    }
    prompt_lookup = {
        _normalize_prompt_line(prompt): qid
        for qid, prompt in prompt_map.items()
        if _normalize_prompt_line(prompt)
    }

    flagged = set()
    for answer in answers:
        current_qid = answer.get("question_id")
        if not current_qid:
            continue
        for line in answer.get("answer_paragraphs", []):
            normalized_line = _normalize_prompt_line(line)
            if len(normalized_line) < 20:
                continue

            exact_qid = prompt_lookup.get(normalized_line)
            if exact_qid and exact_qid != current_qid:
                flagged.add(current_qid)
                break

            fuzzy_match = _best_fuzzy_prompt_match(line, list(prompt_map.values()), minimum_ratio=0.9)
            if fuzzy_match and fuzzy_match != prompt_map.get(current_qid):
                flagged.add(current_qid)
                break

    return flagged


def _finalize_answers_for_rendering(answers):
    """Apply display-safe defaults and remove entries with no text and no image."""
    finalized = []
    for answer in answers:
        text = (answer.get("answer") or "").strip()
        has_images = bool(answer.get("images"))
        if not text and has_images:
            answer["answer"] = IMAGE_ONLY_DEFAULT_ANSWER
            answer["answer_paragraphs"] = [IMAGE_ONLY_DEFAULT_ANSWER]
        elif not text and not has_images:
            # Skip placeholder-only entries where neither text nor image exists.
            continue
        finalized.append(answer)
    return finalized


def _strip_submission_markers(paragraphs):
    """Remove submission tag lines from captured answer paragraphs."""
    cleaned = []
    for paragraph in paragraphs or []:
        text = str(paragraph or "").strip()
        if not text:
            continue

        text = re.sub(r"^\[(Q\d+)\s*:\s*[^\]]*\]\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*\[(Q\d+)\s*:?[\s]+END\]\s*$", "", text, flags=re.IGNORECASE)
        text = text.strip()
        if text:
            cleaned.append(text)

    return cleaned


def _is_image_capture_prompt(prompt):
    lowered = (prompt or "").strip().lower()
    return any(keyword in lowered for keyword in IMAGE_PROMPT_KEYWORDS)


def _rebalance_image_prompt_spillover(answers):
    """Move likely spillover text from image-only prompts to the next question.

    This is intentionally conservative: it only triggers when the current prompt
    looks image-focused, has an attached image, and both current/next answers
    contain substantial text.
    """
    if len(answers) < 2:
        return answers

    for idx in range(len(answers) - 1):
        current = answers[idx]
        nxt = answers[idx + 1]

        if not _is_image_capture_prompt(current.get("prompt", "")):
            continue
        if not current.get("images"):
            continue

        current_text = (current.get("answer") or "").strip()
        next_text = (nxt.get("answer") or "").strip()
        if len(current_text) < 200 or len(next_text) < 60:
            continue

        current_paragraphs = [line for line in current.get("answer_paragraphs", []) if str(line).strip()]
        next_paragraphs = [line for line in nxt.get("answer_paragraphs", []) if str(line).strip()]
        merged_paragraphs = current_paragraphs + next_paragraphs
        if not merged_paragraphs:
            merged_paragraphs = [line for line in (current_text + "\n" + next_text).splitlines() if line.strip()]

        nxt["answer_paragraphs"] = merged_paragraphs
        nxt["answer"] = "\n".join(merged_paragraphs)
        current["answer_paragraphs"] = []
        current["answer"] = ""

    return answers


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

    active_template = project_root / "marking_template" / "active_template.docx"
    if active_template.exists():
        return active_template

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

    matcher = difflib.SequenceMatcher(a=template_lines, b=submission_lines, autojunk=False)
    prompt_order = []
    prompt_index = {}
    answer_blocks = {}
    unmatched_insertions = []
    pending_prompts = []
    known_prompts = [line for line in template_lines if _is_question_prompt(line)]
    prompt_lookup = {
        _normalize_prompt_line(prompt): prompt
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
            matched_prompt, inline_remainder = _match_prompt_boundary(
                line, prompt_lookup, known_prompts
            )
            if matched_prompt:
                flush_chunk(current_target, chunk)
                chunk = []
                register_prompt(matched_prompt)
                current_target = matched_prompt
                if matched_prompt in pending_prompts:
                    pending_prompts.remove(matched_prompt)
                if inline_remainder:
                    chunk.append(inline_remainder)
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
        flat = []
        for block in blocks or []:
            flat.extend(block)
        flat = _strip_submission_markers(flat)
        answers.append({
            "question_id": f"Q{prompt_index[prompt]}",
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

    drifted_questions = _detect_cross_prompt_drift(answers)
    for answer in answers:
        if answer.get("question_id") in drifted_questions:
            _apply_confidence_penalty(
                answer["confidence"],
                0.2,
                "Possible question-boundary drift detected; verify this answer manually.",
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

    image_by_name = {image["filename"]: image for image in images}
    question_to_image_names = {answer["question_id"]: [] for answer in answers}

    active_question = None
    for record in records:
        norm_text = normalize(record.get("text", ""))
        start_match = SUBMISSION_MARKER_START_PATTERN.match(norm_text)
        end_match = SUBMISSION_MARKER_END_PATTERN.match(norm_text)

        if start_match:
            active_question = start_match.group(1).upper()
            continue

        if end_match:
            if active_question == end_match.group(1).upper():
                active_question = None
            continue

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
    extraction["answers"] = _rebalance_image_prompt_spillover(extraction.get("answers", []))
    extraction["answers"] = _finalize_answers_for_rendering(extraction.get("answers", []))
    extraction["answer_count"] = len(extraction["answers"])
    return {
        "status": "ok",
        "template_file": str(template_docx),
        "submission_file": str(Path(submission_docx)),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "image_count": len(images),
        "images": images,
        **extraction,
    }


def parse_template_markers(template_docx):
    """Parse strict [Qx: QUESTION M:n] ... [Qx: END] markers from a DOCX template."""
    lines = _docx_paragraphs(template_docx)
    errors = []
    questions = []
    seen_questions = set()

    active_question_id = None
    active_marks = None
    active_prompt_lines = []

    for line_index, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue

        start_match = TEMPLATE_MARKER_START_PATTERN.match(line)
        end_match = TEMPLATE_MARKER_END_PATTERN.match(line)

        if start_match:
            question_id = start_match.group(1).upper()
            prompt_head = (start_match.group(2) or "").strip()
            max_score = int(start_match.group(3))

            if active_question_id:
                errors.append(
                    f"Line {line_index}: nested start marker for {question_id} while {active_question_id} is still open."
                )
                continue

            if question_id in seen_questions:
                errors.append(
                    f"Line {line_index}: duplicate start marker for {question_id}."
                )
                continue

            active_question_id = question_id
            active_marks = max_score
            active_prompt_lines = []
            if prompt_head and prompt_head.upper() != "QUESTION":
                active_prompt_lines.append(prompt_head)
            continue

        if end_match:
            question_id = end_match.group(1).upper()
            if not active_question_id:
                errors.append(
                    f"Line {line_index}: end marker for {question_id} appears without a matching start marker."
                )
                continue

            if question_id != active_question_id:
                errors.append(
                    f"Line {line_index}: end marker {question_id} does not match open question {active_question_id}."
                )
                continue

            prompt_text = " ".join(active_prompt_lines).strip()
            if not prompt_text:
                errors.append(
                    f"Line {line_index}: {question_id} has no prompt text between start and end markers."
                )
            else:
                questions.append({
                    "question_id": active_question_id,
                    "question_prompt": prompt_text,
                    "max_score": active_marks,
                })
                seen_questions.add(active_question_id)

            active_question_id = None
            active_marks = None
            active_prompt_lines = []
            continue

        if active_question_id:
            active_prompt_lines.append(line)

    if active_question_id:
        errors.append(f"Missing end marker for {active_question_id}.")

    if not questions:
        errors.append(
            "No valid question markers found. Use markers like [Q1: inline prompt M:6] and [Q1 END], or [Q1: QUESTION M:6] with prompt text before [Q1 END]."
        )

    return {
        "questions": questions,
        "errors": errors,
        "line_count": len(lines),
    }


def build_active_template_case_file(template_docx):
    """Build active_template.json payload from strict marker parsing."""
    parsed = parse_template_markers(template_docx)
    questions = parsed["questions"]

    cases = []
    for question in questions:
        qid = question["question_id"]
        qnum = qid[1:].strip() if qid.upper().startswith("Q") else qid
        cases.append({
            "case_id": f"template_{qid.lower()}",
            "question_id": qid,
            "question_prompt": question["question_prompt"],
            "student_answer": "",
            "max_score": question["max_score"],
            "reference_score": "",
            "reference_minimum_requirements_met": False,
            "reference_comment": "",
            "reference_strengths": [],
            "reference_gaps": [],
            "notes_for_edge_cases": f"Generated from marker template for Q{qnum}.",
        })

    return {
        "template": {
            "source_docx": str(Path(template_docx)),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "marker_format": "[Qx: inline prompt M:n] ... [Qx END]",
            "line_count": parsed["line_count"],
            "question_count": len(questions),
        },
        "questions": questions,
        "cases": cases,
        "errors": parsed["errors"],
    }
