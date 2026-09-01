import unittest
from unittest.mock import patch

from src import metadata


class MetadataExtractionTests(unittest.TestCase):
    def test_inline_prompt_answer_lines_are_split_per_question(self):
        q1_prompt = "Please mention the enrolled course and if you take the unit as a mandatory or elective one (2M)."
        q2_prompt = "This question is about your expectations on what you learn in this unit and if it helps to secure later an industry position(5M)"
        q3_prompt = "Explain the following terms (4 MARKS): Model, Abstraction, Constraint, Infeasible Solution Use your own words and provide a short example."

        template_lines = [q1_prompt, q2_prompt, q3_prompt]
        submission_lines = [
            q1_prompt + " I am enrolled in Master of Commerce.",
            q2_prompt + " I expect to learn optimization methods.",
            q3_prompt + " A model is a simplified representation of reality.",
        ]

        with patch("src.metadata._docx_paragraphs", side_effect=[template_lines, submission_lines]):
            extraction = metadata.extract_answers_with_template("submission.docx", "template.docx")

        answers = {item["template_question_id"]: item for item in extraction["answers"]}
        self.assertEqual(3, len(answers))
        self.assertIn("master of commerce", answers["Q1"]["answer"].lower())
        self.assertIn("optimization methods", answers["Q2"]["answer"].lower())
        self.assertIn("simplified representation", answers["Q3"]["answer"].lower())

    def test_fuzzy_prompt_boundary_splits_variant_heading(self):
        q2_prompt = (
            "This question is about your expectations on what you learn in this unit "
            "and if it helps to secure later an industry position(5M)"
        )
        q3_prompt = (
            "Explain the following terms (4 MARKS): Model, Abstraction, Constraint, "
            "Infeasible Solution Use your own words and provide a short example."
        )
        q4_prompt = (
            "Write a short statement about AMPL and its application in the industry, "
            "using information on their Website and Google. (6M)"
        )

        template_lines = [q2_prompt, q3_prompt, q4_prompt]
        submission_lines = [
            q2_prompt,
            "I expect to learn optimization modelling and practical analytics.",
            "Explain the following terms (4 MARKS): Model, Abstraction, Constraint, Infeasible Solution",
            "Model is a simplified representation of a real system.",
            q4_prompt,
            "AMPL is useful in logistics and operations planning.",
        ]

        with patch("src.metadata._docx_paragraphs", side_effect=[template_lines, submission_lines]):
            extraction = metadata.extract_answers_with_template("submission.docx", "template.docx")

        answers_by_template = {
            item["template_question_id"]: item for item in extraction["answers"]
        }

        self.assertIn("Q1", answers_by_template)
        self.assertIn("Q2", answers_by_template)
        self.assertIn("Q3", answers_by_template)

        self.assertIn("I expect to learn optimization", answers_by_template["Q1"]["answer"])
        self.assertNotIn("Model is a simplified representation", answers_by_template["Q1"]["answer"])
        self.assertIn("Model is a simplified representation", answers_by_template["Q2"]["answer"])

    def test_cross_prompt_drift_is_flagged_in_confidence(self):
        answers = [
            {
                "question_id": "Q2",
                "prompt": "This question is about expectations (5M)",
                "answer_paragraphs": [
                    "This question is about expectations (5M)",
                    "Explain the following terms (4 MARKS): Model, Abstraction, Constraint, Infeasible Solution",
                ],
            },
            {
                "question_id": "Q3",
                "prompt": "Explain the following terms (4 MARKS): Model, Abstraction, Constraint, Infeasible Solution",
                "answer_paragraphs": ["AMPL is widely used in industry."],
            },
        ]

        flagged = metadata._detect_cross_prompt_drift(answers)
        self.assertIn("Q2", flagged)

    def test_finalize_answers_sets_placeholder_for_image_only(self):
        answers = [
            {
                "question_id": "Q5",
                "template_question_id": "Q5",
                "prompt": "Include an image (10M)",
                "answer": "",
                "answer_paragraphs": [],
                "images": [{"filename": "img1.png"}],
            },
            {
                "question_id": "Q6",
                "template_question_id": "Q6",
                "prompt": "Another question",
                "answer": "",
                "answer_paragraphs": [],
                "images": [],
            },
        ]

        finalized = metadata._finalize_answers_for_rendering(answers)
        self.assertEqual(1, len(finalized))
        self.assertEqual("Q5", finalized[0]["question_id"])
        self.assertEqual(metadata.IMAGE_ONLY_DEFAULT_ANSWER, finalized[0]["answer"])
        self.assertEqual([metadata.IMAGE_ONLY_DEFAULT_ANSWER], finalized[0]["answer_paragraphs"])

    def test_rebalance_moves_spillover_from_image_prompt(self):
        long_q6_fragment = "Assumption made " + ("capacity limit details " * 20)
        q6_text = "Result summary " + ("additional explanation " * 10)

        answers = [
            {
                "question_id": "Q5",
                "template_question_id": "Q5",
                "prompt": "Include an image (photo, scan, screenshot) of the graph in this document (10M)",
                "answer": long_q6_fragment,
                "answer_paragraphs": [long_q6_fragment],
                "images": [{"filename": "graph.png"}],
            },
            {
                "question_id": "Q6",
                "template_question_id": "Q6",
                "prompt": "Due to environmental restrictions ... (10M)",
                "answer": q6_text,
                "answer_paragraphs": [q6_text],
                "images": [],
            },
        ]

        rebalanced = metadata._rebalance_image_prompt_spillover(answers)
        finalized = metadata._finalize_answers_for_rendering(rebalanced)

        by_qid = {item["question_id"]: item for item in finalized}
        self.assertEqual(metadata.IMAGE_ONLY_DEFAULT_ANSWER, by_qid["Q5"]["answer"])
        self.assertIn("Assumption made", by_qid["Q6"]["answer"])
        self.assertIn("Result summary", by_qid["Q6"]["answer"])


if __name__ == "__main__":
    unittest.main()
