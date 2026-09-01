# New Cohort Switch Checklist

Use this checklist when moving from one assignment cohort to the next.

## Before Switching

1. Finish marking for the current cohort.
2. Avoid re-extracting old submissions after switching templates.
3. Keep a backup copy of the current template and AI case files.

## Update For New Cohort

1. Replace the marking template DOCX in `marking_template/`.
2. Update `config.json`:
- `assignment_title`
- `form_version`
- `marking_template_docx` (if file path changed)
- submission area instructions if needed
3. Reset or archive previous AI case files in `ai_eval/`.
4. Create new sample case files for early calibration (3 to 5 per question/subquestion).

## Validate Setup

1. Run a quick extraction test on one sample submission.
2. Confirm question IDs and marks in previews are correct.
3. Run Ollama link check:

```bash
python3 ai_eval/run_ollama_check.py --cases ai_eval/sample_case_template.json --model qwen2.5:7b
```

4. If using Q2 split files, run checks per file:

```bash
python3 ai_eval/run_ollama_check.py --cases ai_eval/sample_case_template_q2.json --model qwen2.5:7b
```

## First Marking Batch

1. Mark first 3 to 4 submissions manually.
2. Use those records to calibrate AI case references.
3. Compare AI draft score/comment against manual marks.
4. Tighten rubric wording where score deltas are large.

## Operational Note

This project currently assumes one active cohort at a time, so template and rubric changes are expected between cohorts.
