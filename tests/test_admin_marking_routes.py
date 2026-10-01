import unittest
from unittest.mock import patch

import app


class AdminMarkingRouteTests(unittest.TestCase):
    def setUp(self):
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()
        self.submission = {"id": 42, "files": []}
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True

    def test_marking_route_requires_admin(self):
        client = app.app.test_client()

        response = client.get("/admin/submission/42/marking")

        self.assertEqual(302, response.status_code)
        self.assertIn("/admin/login", response.headers["Location"])

    def test_marking_route_returns_not_found_for_missing_submission(self):
        with patch.object(app.db, "get_submission", return_value=None):
            response = self.client.get("/admin/submission/42/marking")

        self.assertEqual(404, response.status_code)

    def test_assessment_route_validates_question_id_for_async_save(self):
        with patch.object(app.db, "get_submission", return_value=self.submission), patch.object(
            app.db, "save_marking_assessment"
        ) as save_assessment:
            response = self.client.post(
                "/admin/submission/42/marking/assessment",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )

        self.assertEqual(400, response.status_code)
        self.assertEqual("Question ID is required for saving marking.", response.json["error"])
        save_assessment.assert_not_called()

    def test_assessment_route_saves_human_marking_and_eval_candidate(self):
        form_data = {
            "question_id": "Q1",
            "score": "4",
            "comment": "Clear explanation.",
            "view": "student",
            "question_prompt": "Explain the method.",
            "student_answer": "The student answer.",
            "marks_label": "5M",
            "include_eval_case": "true",
            "comment_source": "human",
        }
        with patch.object(app.db, "get_submission", return_value=self.submission), patch.object(
            app.db, "save_marking_assessment"
        ) as save_assessment, patch.object(app.db, "save_eval_case_candidate") as save_candidate:
            response = self.client.post(
                "/admin/submission/42/marking/assessment",
                data=form_data,
                headers={"X-Requested-With": "XMLHttpRequest"},
            )

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json["ok"])
        save_assessment.assert_called_once_with(
            42,
            "Q1",
            "4",
            "Clear explanation.",
            comment_source="human",
            ai_reasoning="",
        )
        save_candidate.assert_called_once_with(
            submission_id=42,
            question_id="Q1",
            question_prompt="Explain the method.",
            student_answer="The student answer.",
            marks_label="5M",
            reference_score="4",
            reference_comment="Clear explanation.",
            ai_draft_used=False,
            include_in_eval=True,
        )

    def test_ai_suggestion_route_validates_required_fields(self):
        with patch.object(app.db, "get_submission", return_value=self.submission), patch.object(
            app, "_generate_ai_marking_suggestion"
        ) as generate_suggestion:
            response = self.client.post(
                "/admin/submission/42/marking/ai-suggest",
                json={"question_id": "Q1", "question_prompt": "Prompt only."},
            )

        self.assertEqual(400, response.status_code)
        self.assertIn("student_answer", response.json["error"])
        generate_suggestion.assert_not_called()

    def test_ai_suggestion_route_delegates_valid_request(self):
        expected = {"ok": True, "suggestion": {"score": 4.0}}
        payload = {
            "question_id": "Q1",
            "question_prompt": "Explain the method.",
            "student_answer": "The student answer.",
            "marks_label": "5M",
        }
        with patch.object(app.db, "get_submission", return_value=self.submission), patch.object(
            app, "_generate_ai_marking_suggestion", return_value=expected
        ) as generate_suggestion:
            response = self.client.post(
                "/admin/submission/42/marking/ai-suggest",
                json=payload,
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(expected, response.json)
        generate_suggestion.assert_called_once_with("Q1", "Explain the method.", "The student answer.", "5M")

    def test_reextract_route_blocks_when_assessment_exists(self):
        with patch.object(app.db, "get_submission", return_value=self.submission), patch.object(
            app.db, "has_marking_assessments", return_value=True
        ), patch.object(app, "_extract_marking_preview_for_submission_file") as extract_preview:
            response = self.client.post(
                "/admin/submission/42/marking/reextract",
                data={"view": "student"},
            )

        self.assertEqual(302, response.status_code)
        self.assertIn("/admin/submission/42/marking", response.headers["Location"])
        extract_preview.assert_not_called()


if __name__ == "__main__":
    unittest.main()