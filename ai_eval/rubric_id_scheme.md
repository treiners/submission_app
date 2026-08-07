# Rubric ID Scheme And Case Naming

This document defines a stable naming scheme so template rubric blocks and JSON sample cases stay aligned.

## Goals

- Avoid confusion when one assignment question has multiple subquestions.
- Keep scoring per subquestion explicit.
- Make automated extraction and evaluation reproducible.

## Rubric ID Format

Use this format for rubric block IDs:

- Q1
- Q2A
- Q2B
- Q2C
- Q3A (if needed later)

Pattern:

- Top-level question only: Qn
- Question with subparts: QnA, QnB, QnC

## Proposed Mapping For Current Template

Based on the current wording in the template:

1. Q1
- Topic: expectation on what is learned and later industry position
- Pilot max score: 5

2. Q2A
- Topic: environmental restriction constraint implementation
- Full assignment mark label in text: 10M
- AI pilot mark (recommended): choose explicit pilot value and keep it in rubric max_score

3. Q2B
- Topic: overall MAXPROCESS capacity limit and demonstration
- Full assignment mark label in text: 10M
- AI pilot mark (recommended): choose explicit pilot value and keep it in rubric max_score

4. Q2C
- Topic: further extension idea
- Full assignment mark label in text: 3M
- AI pilot mark (recommended): choose explicit pilot value and keep it in rubric max_score

Important:
- If you want Q2 to be treated as a single 5-mark pilot item, keep one rubric block as Q2 with max_score: 5.
- If you want granular AI feedback per subpart, split into Q2A, Q2B, Q2C.

## Template Block Example

Use one block per rubric ID:

[AI_RUBRIC Q2A]
max_score: 5
focus: constraint logic and implementation clarity
minimum_requirements: mentions required constraint and shows where it is implemented
good_requirements: explains model/data changes and demonstrates with a valid scenario
excellent_requirements: precise assumptions, correct implementation detail, and clear result interpretation
common_mistakes: vague constraint, no implementation evidence, no demonstration
feedback_style: concise, academic, constructive
model_answer_notes: explain constraint purpose and implementation impact
[/AI_RUBRIC]

## Dataset Naming

File naming:

- ai_eval/cases_q1.json
- ai_eval/cases_q2a.json
- ai_eval/cases_q2b.json
- ai_eval/cases_q2c.json

Case ID naming:

- sample_001_q1
- sample_001_q2a
- sample_001_q2b
- sample_001_q2c

## JSON Field Rules

In each case object:

- question_id must match the rubric ID exactly.
- max_score must match the rubric block max_score used for that question_id.
- reference_score must be numeric and within 0..max_score.

## Pre-Run Validation Checklist

1. Each case has a non-empty case_id.
2. Each case question_id exists in template rubric blocks.
3. max_score in JSON equals max_score in matching rubric block.
4. reference_score is numeric and not above max_score.
5. student_answer is non-empty.

## Migration Path From Current Files

1. Keep current Q1 file as is.
2. For Q2, decide one strategy:
- Single pilot item: keep question_id Q2 and max_score 5.
- Split pilot item: create Q2A/Q2B/Q2C case files and blocks.
3. Run checker separately per file to keep diagnostics clear.
