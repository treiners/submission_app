import json
import unittest
from unittest.mock import MagicMock, patch

from src import marking_service


class MarkingServiceTests(unittest.TestCase):
    def test_normalize_and_merge_question_ids(self):
        self.assertEqual("Q2", marking_service.normalize_question_id("q02"))
        self.assertIsNone(marking_service.normalize_question_id("Q0"))
        self.assertEqual(
            ["Q2", "Q1", "Q3", "Q12"],
            marking_service.merge_question_ids(["Q2"], ["1", "Q12", "Q3", "Q1"]),
        )

    def test_extract_answers_keeps_first_normalized_answer(self):
        previews = [
            {
                "file": "first.answers.json",
                "data": {"answers": [{"question_id": "q01", "prompt": "First", "answer": "A"}]},
            },
            {
                "file": "second.answers.json",
                "data": {"answers": [{"question_id": "Q1", "prompt": "Second", "answer": "B"}]},
            },
        ]

        ordered, answers = marking_service.extract_answers_by_question(previews)

        self.assertEqual(["Q1"], ordered)
        self.assertEqual("first.answers.json", answers["Q1"]["preview_file"])
        self.assertEqual("A", answers["Q1"]["answer"]["answer"])

    def test_build_answer_entry_merges_extracted_and_template_data(self):
        entry = marking_service.build_answer_entry(
            "Q1",
            {"preview_file": "q1.answers.json", "answer": {"answer": "Work shown."}},
            {"Q1": {"question_prompt": "Explain.", "marks_label": "5M", "max_score": 5}},
        )

        self.assertEqual("Explain.", entry["answer"]["prompt"])
        self.assertEqual("5M", entry["answer"]["marks_label"])
        self.assertEqual("Work shown.", entry["answer"]["answer"])
        self.assertEqual("q1.answers.json", entry["preview_file"])

    def test_has_unmarked_items_requires_score_and_comment(self):
        previews = [{"file": "answers.json", "data": {"answers": [{"question_id": "Q1"}]}}]
        self.assertTrue(marking_service.has_unmarked_items(previews, {}, ["Q1"]))
        self.assertTrue(
            marking_service.has_unmarked_items(
                previews,
                {"Q1": {"score": "5", "comment": ""}},
                ["Q1"],
            )
        )
        self.assertFalse(
            marking_service.has_unmarked_items(
                previews,
                {"Q1": {"score": "5", "comment": "Complete."}},
                ["Q1"],
            )
        )

    def test_extract_json_object_reads_nested_json_from_surrounding_text(self):
        parsed = marking_service.extract_json_object(
            'Draft: {"score": 3, "rationale": "a } b", "details": {"ok": true}} trailing'
        )

        self.assertEqual({"score": 3, "rationale": "a } b", "details": {"ok": True}}, parsed)

    def test_generate_suggestion_clamps_score_and_preserves_response(self):
        response_body = {
            "response": json.dumps({
                "score": 8,
                "feedback_comment": " Good work. ",
                "rationale": "Supported.",
                "minimum_requirements_met": True,
                "strengths": ["Evidence"],
                "gaps": "not-an-array",
            })
        }
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(response_body).encode("utf-8")

        with patch("src.marking_service.urlrequest.urlopen", return_value=response):
            result = marking_service.generate_ai_marking_suggestion(
                "Q1",
                "Explain.",
                "Answer.",
                "5M",
                endpoint="http://ollama.local/",
                model="test-model",
                timeout_seconds=12,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(5.0, result["suggestion"]["score"])
        self.assertEqual("Good work.", result["suggestion"]["feedback_comment"])
        self.assertEqual([], result["suggestion"]["gaps"])
        self.assertEqual(response_body["response"], result["raw_response"])


if __name__ == "__main__":
    unittest.main()