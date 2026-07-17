import unittest

from interview_feedback import RiskFinding, build_placeholder_feedback


class InterviewFeedbackTests(unittest.TestCase):
    def test_feedback_shape_has_explicit_risk_categories(self):
        feedback = build_placeholder_feedback(
            {
                "profile": {
                    "skills": {
                        "question_id": "skills",
                        "attribute": "Skills",
                        "status": "captured",
                        "value": "Python, customer support, and reporting.",
                    }
                },
                "turns": [],
            }
        )
        data = feedback.to_dict()

        self.assertIn("red_flags", data)
        self.assertIn("contradictions", data)
        self.assertIn("missed_opportunities", data)
        self.assertIn("strengths", data)
        self.assertIn("suggested_improvements", data)
        self.assertIsInstance(feedback.contradictions[0], RiskFinding)
        self.assertEqual(feedback.contradictions[0].category, "contradiction")

    def test_skipped_answer_becomes_missed_opportunity(self):
        feedback = build_placeholder_feedback(
            {
                "profile": {
                    "projects": {
                        "question_id": "projects",
                        "attribute": "Projects",
                        "status": "skipped",
                        "value": None,
                    }
                },
                "turns": [],
            }
        )

        self.assertEqual(feedback.missed_opportunities[0].category, "missed_opportunity")
        self.assertIn("skipped", feedback.missed_opportunities[0].summary.lower())


if __name__ == "__main__":
    unittest.main()
