# AI Marking Pilot

This folder is a small, standalone workspace for testing AI-assisted marking before it is connected to the admin UI.

## Purpose

- Keep the AI pilot separate from the current manual marking flow.
- Test one question at a time first.
- Use local Ollama serving initially.
- Compare AI suggestions against a small hand-coded reference set.

## Rubric Grammar

Use explicit rubric blocks in the marking template DOCX.

```text
[AI_RUBRIC Q1]
max_score: 5
focus: short summary of what the answer must cover
minimum_requirements: what must be present to reach the minimum pass level
good_requirements: what is needed for a solid mid-level answer
excellent_requirements: what is needed for a strong answer
common_mistakes: typical errors or omissions
feedback_style: concise, academic, constructive
model_answer_notes: short internal note about the expected answer
[/AI_RUBRIC]
```

Rules:
- The block name must match the extracted question id, for example `Q1`.
- `max_score`, `focus`, and `minimum_requirements` are required.
- The AI should return a numeric score, not `3/5` text.
- Keep the rubric short and specific.
- Use the same wording style for all questions so the model sees consistent instructions.

## First Evaluation Dataset

Start with 3 to 5 sample answers for the first question.

Each case should include:
- `case_id`
- `question_id`
- `question_prompt`
- `student_answer`
- `max_score`
- `reference_score`
- `reference_minimum_requirements_met`
- `reference_comment`
- `reference_strengths`
- `reference_gaps`

Suggested JSON shape:

```json
{
  "case_id": "sample_001_q1",
  "question_id": "Q1",
  "question_prompt": "...",
  "student_answer": "...",
  "max_score": 5,
  "reference_score": 3,
  "reference_minimum_requirements_met": true,
  "reference_comment": "...",
  "reference_strengths": ["..."],
  "reference_gaps": ["..."]
}
```

## First Test Checklist

For the first pilot, check:

1. Does the AI identify the minimum requirement correctly?
2. Does the AI return a sensible numeric score?
3. Does the AI comment mention the same strengths and gaps you would mention?
4. Is the output stable across repeated runs?
5. Does the model stay inside the rubric rather than inventing new criteria?

## Recommended Next Step

Populate the first question with 3 to 5 sample answers, then run the same cases repeatedly with Ollama to see whether the rubric wording is strong enough.

## Quick Ollama Link Check

Run this command from the repository root to verify the local AI link with your sample cases:

```bash
python3 ai_eval/run_ollama_check.py --cases ai_eval/sample_case_template.json --model qwen2.5:7b
```

The script writes a JSON report under `ai_eval/results/` with per-case outputs and summary statistics.
