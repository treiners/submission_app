import json
import re
from urllib import request as urlrequest


def normalize_question_id(value):
    raw = str(value or "").strip().upper()
    if not raw:
        return None

    digits = raw[1:] if raw.startswith("Q") else raw
    if not digits.isdigit():
        return None

    number = int(digits)
    return f"Q{number}" if number > 0 else None


def question_sort_key(question_id):
    parts = re.split(r"(\d+)", str(question_id or ""))
    normalized = []
    for part in parts:
        if part.isdigit():
            normalized.append((0, int(part)))
        else:
            normalized.append((1, part.lower()))
    return normalized


def assessment_has_marking(assessment_record):
    if not assessment_record:
        return False
    score = str(assessment_record.get("score", "") or "").strip()
    comment = str(assessment_record.get("comment", "") or "").strip()
    return bool(score and comment)


def extract_answers_by_question(previews):
    ordered = []
    seen = set()
    by_question = {}
    for preview in previews:
        for answer in preview["data"].get("answers", []):
            question_id = normalize_question_id(answer.get("question_id"))
            if not question_id:
                continue

            answer_copy = dict(answer)
            answer_copy["question_id"] = question_id
            answer_copy["template_question_id"] = (
                normalize_question_id(answer_copy.get("template_question_id")) or question_id
            )

            if question_id not in seen:
                seen.add(question_id)
                ordered.append(question_id)

            if question_id not in by_question:
                by_question[question_id] = {
                    "preview_file": preview["file"],
                    "answer": answer_copy,
                    "images": answer_copy.get("images", []),
                }

    return ordered, by_question


def merge_question_ids(*question_id_lists):
    merged = []
    seen = set()
    extras = []
    for index, values in enumerate(question_id_lists):
        for raw in values or []:
            question_id = normalize_question_id(raw)
            if not question_id or question_id in seen:
                continue
            seen.add(question_id)
            if index == 0:
                merged.append(question_id)
            else:
                extras.append(question_id)

    for question_id in sorted(set(extras), key=question_sort_key):
        if question_id not in merged:
            merged.append(question_id)
    return merged


def build_answer_entry(question_id, matched, template_question_map):
    template_meta = template_question_map.get(question_id, {})
    template_prompt = str(template_meta.get("question_prompt", "") or "").strip()
    template_marks_label = str(template_meta.get("marks_label", "") or "").strip()

    source_answer = dict((matched or {}).get("answer") or {})
    extracted_prompt = str(source_answer.get("prompt", "") or "").strip()
    merged_prompt = extracted_prompt or template_prompt

    answer_entry = {
        "question_id": question_id,
        "template_question_id": source_answer.get("template_question_id") or question_id,
        "prompt": merged_prompt,
        "template_prompt": template_prompt,
        "extracted_prompt": extracted_prompt,
        "marks_label": source_answer.get("marks_label") or template_marks_label,
        "answer": str(source_answer.get("answer", "") or ""),
        "answer_paragraphs": source_answer.get("answer_paragraphs") or [],
        "confidence": source_answer.get("confidence"),
        "images": source_answer.get("images") or [],
        "max_score": template_meta.get("max_score"),
    }

    return {
        "preview_file": (matched or {}).get("preview_file"),
        "answer": answer_entry,
        "images": answer_entry["images"],
    }


def has_unmarked_items(previews, assessment_map, template_question_ids):
    extracted_ids, _ = extract_answers_by_question(previews)
    question_ids = merge_question_ids(template_question_ids, extracted_ids, assessment_map.keys())
    return any(not assessment_has_marking(assessment_map.get(question_id, {})) for question_id in question_ids)


def extract_json_object(text):
    text = (text or "").strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        char = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:idx + 1]
                try:
                    parsed = json.loads(candidate)
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def parse_max_score_from_marks_label(marks_label):
    match = re.search(r"(\d+)", marks_label or "")
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return 5.0
    return 5.0


def build_marking_ai_prompt(question_id, prompt, answer, marks_label):
    max_score = parse_max_score_from_marks_label(marks_label)
    return (
        "You are helping an academic marker draft a provisional mark. "
        "Return strict JSON only and no markdown. "
        "Required keys: score, feedback_comment, rationale, minimum_requirements_met, strengths, gaps. "
        "score must be numeric in [0, max_score]. "
        "minimum_requirements_met must be true or false. "
        "strengths and gaps must be short string arrays.\n\n"
        f"Question ID: {question_id}\n"
        f"Question prompt: {prompt}\n"
        f"Student answer: {answer}\n"
        f"Mark label: {marks_label or 'n/a'}\n"
        f"max_score: {max_score}\n"
    )


def generate_ai_marking_suggestion(
    question_id,
    prompt,
    answer,
    marks_label,
    *,
    endpoint,
    model,
    timeout_seconds,
):
    max_score = parse_max_score_from_marks_label(marks_label)
    payload = {
        "model": model,
        "prompt": build_marking_ai_prompt(question_id, prompt, answer, marks_label),
        "stream": False,
        "options": {"temperature": 0.1},
    }

    req = urlrequest.Request(
        endpoint.rstrip("/") + "/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=timeout_seconds) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    raw_text = str(body.get("response", "")).strip()
    parsed = extract_json_object(raw_text)
    if not parsed:
        return {
            "ok": False,
            "error": "Model output was not valid JSON.",
            "raw_response": raw_text,
        }

    score = parsed.get("score")
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        numeric_score = None

    if numeric_score is not None:
        numeric_score = max(0.0, min(max_score, numeric_score))

    suggestion = {
        "score": numeric_score,
        "feedback_comment": str(parsed.get("feedback_comment", "")).strip(),
        "rationale": str(parsed.get("rationale", "")).strip(),
        "minimum_requirements_met": bool(parsed.get("minimum_requirements_met", False)),
        "strengths": parsed.get("strengths", []) if isinstance(parsed.get("strengths", []), list) else [],
        "gaps": parsed.get("gaps", []) if isinstance(parsed.get("gaps", []), list) else [],
        "max_score": max_score,
        "model": model,
    }
    return {"ok": True, "suggestion": suggestion, "raw_response": raw_text}