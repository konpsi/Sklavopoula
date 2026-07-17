import unittest

from interview_feedback import RiskFinding, feedback_from_llm


class InterviewFeedbackTests(unittest.TestCase):
    def test_feedback_shape_has_explicit_risk_categories(self):
        feedback = feedback_from_llm(
            {
                "red_flags": [],
                "contradictions": [
                    {
                        "title": "Dates do not align",
                        "summary": "The spoken dates conflict with the CV.",
                        "evidence": "The CV says one year; the candidate said four months.",
                        "severity": "high",
                        "suggested_fix": "Confirm the correct dates before the next interview.",
                    }
                ],
                "missed_opportunities": [],
                "strengths": [],
                "suggested_improvements": [],
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

    def test_llm_missed_opportunity_is_converted(self):
        feedback = feedback_from_llm(
            {
                "red_flags": [],
                "contradictions": [],
                "missed_opportunities": [
                    {
                        "title": "Project example was not used",
                        "summary": "A relevant CV project was not connected to the role.",
                        "evidence": "The CV lists a reporting project, but the answer stayed general.",
                        "severity": "medium",
                        "suggested_fix": "Use the project as a concise situation-action-result example.",
                    }
                ],
                "strengths": [],
                "suggested_improvements": [],
            }
        )

        self.assertEqual(feedback.missed_opportunities[0].category, "missed_opportunity")
        self.assertIn("project", feedback.missed_opportunities[0].summary.lower())


if __name__ == "__main__":
    unittest.main()
