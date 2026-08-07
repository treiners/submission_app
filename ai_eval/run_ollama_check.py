#!/usr/bin/env python3
"""Run a quick local Ollama connectivity and scoring check on sample cases."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b"


@dataclass
class CaseResult:
    case_id: str
    question_id: str
    reference_score: float | None
    ai_score: float | None
    score_delta: float | None
    ok: bool
    error: str | None
    raw_response: str
    parsed_response: dict[str, Any] | None


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        return payload["cases"]
    raise ValueError("Cases file must be a list or object with a 'cases' list.")


def extract_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None

    # First attempt: plain JSON text.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fallback: find the first top-level {...} span.
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
                candidate = text[start : idx + 1]
                try:
                    parsed = json.loads(candidate)
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None

    return None


def coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def build_prompt(case: dict[str, Any]) -> str:
    return (
        "You are assisting with academic marking. "
        "Return strict JSON only, no markdown and no extra text. "
        "Output keys: score, minimum_requirements_met, rationale, feedback_comment, strengths, gaps. "
        "score must be numeric in [0, max_score]. "
        "minimum_requirements_met must be true/false. "
        "strengths and gaps must be arrays of short strings.\n\n"
        f"Question ID: {case.get('question_id', '')}\n"
        f"Question: {case.get('question_prompt', '')}\n"
        f"Student answer: {case.get('student_answer', '')}\n"
        f"Max score: {case.get('max_score', 5)}\n"
    )


def ollama_generate(endpoint: str, model: str, prompt: str, timeout: int) -> str:
    url = endpoint.rstrip("/") + "/api/generate"
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
        },
    }

    req = request.Request(
        url=url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return str(payload.get("response", ""))


def run_case(case: dict[str, Any], endpoint: str, model: str, timeout: int) -> CaseResult:
    case_id = str(case.get("case_id", "unknown"))
    question_id = str(case.get("question_id", ""))
    reference_score = coerce_float(case.get("reference_score"))

    try:
        raw = ollama_generate(endpoint=endpoint, model=model, prompt=build_prompt(case), timeout=timeout)
        parsed = extract_json_object(raw)
        ai_score = coerce_float((parsed or {}).get("score"))
        delta = None
        if reference_score is not None and ai_score is not None:
            delta = round(ai_score - reference_score, 3)
        return CaseResult(
            case_id=case_id,
            question_id=question_id,
            reference_score=reference_score,
            ai_score=ai_score,
            score_delta=delta,
            ok=parsed is not None and ai_score is not None,
            error=None if parsed is not None else "Model output could not be parsed as JSON.",
            raw_response=raw,
            parsed_response=parsed,
        )
    except error.URLError as exc:
        return CaseResult(
            case_id=case_id,
            question_id=question_id,
            reference_score=reference_score,
            ai_score=None,
            score_delta=None,
            ok=False,
            error=f"Connection error: {exc}",
            raw_response="",
            parsed_response=None,
        )
    except Exception as exc:  # pragma: no cover - defensive path for pilot tooling
        return CaseResult(
            case_id=case_id,
            question_id=question_id,
            reference_score=reference_score,
            ai_score=None,
            score_delta=None,
            ok=False,
            error=str(exc),
            raw_response="",
            parsed_response=None,
        )


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    total = len(results)
    ok_count = sum(1 for item in results if item.ok)

    deltas = [abs(item.score_delta) for item in results if item.score_delta is not None]
    within_1 = sum(1 for d in deltas if d <= 1.0)
    exact = sum(1 for d in deltas if d == 0.0)

    return {
        "total_cases": total,
        "ok_cases": ok_count,
        "failed_cases": total - ok_count,
        "exact_score_matches": exact,
        "within_one_score_matches": within_1,
        "has_reference_pairs": len(deltas),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Ollama link check with sample marking cases.")
    parser.add_argument(
        "--cases",
        default="ai_eval/sample_case_template.json",
        help="Path to case JSON file (list or object with 'cases').",
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("OLLAMA_ENDPOINT", DEFAULT_ENDPOINT),
        help="Ollama endpoint base URL.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL),
        help="Ollama model name.",
    )
    parser.add_argument(
        "--timeout",
        default=60,
        type=int,
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output JSON path. Defaults to ai_eval/results/ollama_check_<timestamp>.json",
    )
    args = parser.parse_args()

    case_path = Path(args.cases)
    if not case_path.exists():
        print(f"Cases file not found: {case_path}", file=sys.stderr)
        return 2

    cases = load_cases(case_path)
    results = [run_case(case, endpoint=args.endpoint, model=args.model, timeout=args.timeout) for case in cases]
    summary = summarize(results)

    out_path = Path(args.output) if args.output else Path(
        "ai_eval/results/ollama_check_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    output_payload = {
        "generated_at": datetime.now().isoformat(),
        "endpoint": args.endpoint,
        "model": args.model,
        "cases_file": str(case_path),
        "summary": summary,
        "results": [
            {
                "case_id": item.case_id,
                "question_id": item.question_id,
                "reference_score": item.reference_score,
                "ai_score": item.ai_score,
                "score_delta": item.score_delta,
                "ok": item.ok,
                "error": item.error,
                "parsed_response": item.parsed_response,
                "raw_response": item.raw_response,
            }
            for item in results
        ],
    }
    out_path.write_text(json.dumps(output_payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    print("Ollama case check complete")
    print(f"Output: {out_path}")
    print(json.dumps(summary, indent=2, ensure_ascii=True))

    return 0 if summary["ok_cases"] == summary["total_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
