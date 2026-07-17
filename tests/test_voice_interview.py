import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from questionnaire import QUESTIONNAIRE
from voice_interview import InterviewError, OpenRouterClient, VoiceInterviewService


class FakeTranscriber:
    def __init__(self, transcript="Ada raw transcript"):
        self.transcript = transcript

    def transcribe(self, _audio_path):
        return self.transcript


class FakeLLM:
    configured = True

    def __init__(self, evaluations=None, proposed_id=None):
        self.evaluations = list(
            evaluations
            or [
                {
                    "outcome": "captured",
                    "normalized_value": "Ada Lovelace",
                    "assistant_reply": None,
                }
            ]
        )
        self.proposed_id = proposed_id
        self.evaluation_calls = []
        self.selection_calls = []

    def evaluate_answer(self, current, asked_question, transcript, attempts):
        self.evaluation_calls.append((current, asked_question, transcript, attempts))
        if len(self.evaluations) > 1:
            return self.evaluations.pop(0)
        return dict(self.evaluations[0])

    def select_next_question(self, profile, pending, last_resolution):
        self.selection_calls.append((dict(profile), list(pending), last_resolution))
        if not pending:
            return {
                "transition": "Your questionnaire is complete.",
                "next_question_id": None,
                "question": None,
            }
        item = next(
            (candidate for candidate in pending if candidate["id"] == self.proposed_id),
            pending[0],
        )
        return {
            "transition": "Let's continue.",
            "next_question_id": item["id"],
            "question": f"LLM asks about {item['title']}?",
        }


class FailingEvaluatorLLM(FakeLLM):
    def evaluate_answer(self, current, asked_question, transcript, attempts):
        self.evaluation_calls.append((current, asked_question, transcript, attempts))
        raise InterviewError("OpenRouter HTTP 429: rate limit reached")


class FailingSecondSelectorLLM(FakeLLM):
    def select_next_question(self, profile, pending, last_resolution):
        if self.selection_calls:
            raise InterviewError("OpenRouter HTTP 503: provider unavailable")
        return super().select_next_question(profile, pending, last_resolution)


class VoiceInterviewServiceTests(unittest.TestCase):
    def make_service(self, directory, llm=None, transcript="Ada raw transcript"):
        service = VoiceInterviewService(directory)
        service.llm = llm or FakeLLM()
        service.transcriber = FakeTranscriber(transcript)
        return service

    def test_start_uses_selector_and_creates_versioned_empty_state(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(directory)
            turn = service.start("a" * 32)

            self.assertEqual(turn["attribute"], QUESTIONNAIRE[0]["title"])
            self.assertIn("Full name", turn["question"])
            self.assertIn("Let's continue", turn["response"])
            self.assertFalse(turn["complete"])
            self.assertEqual(len(service.llm.selection_calls), 1)
            saved = json.loads(Path(directory, f"{'a' * 32}.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["version"], 2)
            self.assertEqual(saved["profile"], {})
            self.assertEqual(saved["turns"], [])

    def test_captured_answer_saves_normalized_value_and_raw_turn_then_selects(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(directory)
            session_id = "b" * 32
            service.start(session_id)
            turn = service.answer(session_id, "unused.webm")

            saved_answer = turn["saved_answer"]
            self.assertEqual(turn["outcome"], "captured")
            self.assertEqual(saved_answer["value"], "Ada Lovelace")
            self.assertEqual(saved_answer["raw_transcript"], "Ada raw transcript")
            self.assertEqual(len(service.llm.selection_calls), 2)
            saved = json.loads(Path(directory, f"{session_id}.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["profile"]["full_name"]["value"], "Ada Lovelace")
            self.assertEqual(saved["turns"][0]["raw_transcript"], "Ada raw transcript")
            self.assertEqual(saved["turns"][0]["outcome"], "captured")

    def test_clarification_is_logged_as_turn_but_not_profile_and_skips_second_call(self):
        evaluation = {
            "outcome": "clarify",
            "normalized_value": None,
            "assistant_reply": "I mean the name you want shown on your CV. What should I use?",
        }
        with tempfile.TemporaryDirectory() as directory:
            llm = FakeLLM([evaluation])
            service = self.make_service(directory, llm, "Explain the question better")
            session_id = "c" * 32
            service.start(session_id)
            turn = service.answer(session_id, "unused.webm")

            self.assertEqual(turn["outcome"], "clarify")
            self.assertIsNone(turn["saved_answer"])
            self.assertEqual(service.sessions[session_id].profile, {})
            self.assertEqual(service.sessions[session_id].current_question_id, "full_name")
            self.assertEqual(len(llm.selection_calls), 1)
            self.assertEqual(service.sessions[session_id].turns[0]["outcome"], "clarify")
            self.assertIn("name you want", turn["response"])

    def test_second_clarification_offers_skip(self):
        evaluation = {
            "outcome": "clarify",
            "normalized_value": None,
            "assistant_reply": "Please tell me the name you want displayed.",
        }
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(directory, FakeLLM([evaluation]))
            session_id = "d" * 32
            service.start(session_id)
            service.answer(session_id, "unused.webm")
            turn = service.answer(session_id, "unused.webm")

            self.assertIn("say skip", turn["response"].lower())
            self.assertEqual(turn["answered"], 0)

    def test_skipped_answer_resolves_item_without_value_and_selects_next(self):
        evaluation = {"outcome": "skipped", "normalized_value": None, "assistant_reply": None}
        with tempfile.TemporaryDirectory() as directory:
            llm = FakeLLM([evaluation])
            service = self.make_service(directory, llm, "I prefer not to say")
            session_id = "e" * 32
            service.start(session_id)
            turn = service.answer(session_id, "unused.webm")

            self.assertEqual(turn["outcome"], "skipped")
            self.assertEqual(turn["saved_answer"]["status"], "skipped")
            self.assertIsNone(turn["saved_answer"]["value"])
            self.assertEqual(len(llm.selection_calls), 2)
            self.assertEqual(turn["answered"], 1)

    def test_evaluator_failure_does_not_store_or_advance(self):
        with tempfile.TemporaryDirectory() as directory:
            llm = FailingEvaluatorLLM()
            service = self.make_service(directory, llm)
            session_id = "f" * 32
            service.start(session_id)
            turn = service.answer(session_id, "unused.webm")

            self.assertEqual(turn["outcome"], "processing_error")
            self.assertEqual(service.sessions[session_id].profile, {})
            self.assertEqual(service.sessions[session_id].current_question_id, "full_name")
            self.assertEqual(len(llm.selection_calls), 1)
            self.assertIn("HTTP 429", turn["warning"])

    def test_selector_failure_happens_after_profile_save_and_uses_outline_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            llm = FailingSecondSelectorLLM()
            service = self.make_service(directory, llm)
            session_id = "1" * 32
            service.start(session_id)
            turn = service.answer(session_id, "unused.webm")

            self.assertIn("full_name", service.sessions[session_id].profile)
            self.assertEqual(service.sessions[session_id].current_question_id, "professional_title")
            self.assertEqual(turn["question"], QUESTIONNAIRE[1]["question"])
            self.assertIn("HTTP 503", turn["warning"])

    def test_last_resolved_item_completes_questionnaire(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(directory)
            session_id = "2" * 32
            service.start(session_id)

            for _ in QUESTIONNAIRE:
                turn = service.answer(session_id, "unused.webm")

            self.assertTrue(turn["complete"])
            self.assertIsNone(turn["question"])
            self.assertEqual(turn["answered"], len(QUESTIONNAIRE))
            self.assertEqual(len(service.sessions[session_id].profile), len(QUESTIONNAIRE))

    def test_missing_key_is_reported_before_interview_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            service = VoiceInterviewService(directory)
            service.llm.api_key = ""
            with self.assertRaisesRegex(InterviewError, "OPENROUTER_API_KEY"):
                service.start("3" * 32)


class OpenRouterParsingTests(unittest.TestCase):
    def test_parses_json_inside_markdown_fence(self):
        parsed = OpenRouterClient._parse_json_object(
            '```json\n{"outcome":"captured","normalized_value":"Ada","assistant_reply":null}\n```'
        )
        self.assertEqual(parsed["outcome"], "captured")

    def test_evaluation_validation_rejects_missing_captured_value(self):
        with self.assertRaisesRegex(InterviewError, "invalid captured"):
            OpenRouterClient._validate_evaluation(
                {"outcome": "captured", "normalized_value": None, "assistant_reply": None}
            )

    def test_completion_requests_strict_structured_output(self):
        client = OpenRouterClient()
        client.api_key = "test-key"
        response = MagicMock()
        response.read.return_value = b'{"choices":[{"message":{"content":"{\\"outcome\\":\\"skipped\\"}"}}]}'
        context = MagicMock()
        context.__enter__.return_value = response

        with patch("urllib.request.urlopen", return_value=context) as urlopen:
            content = client._completion(
                [{"role": "user", "content": "Evaluate"}],
                max_tokens=50,
                schema_name="test_schema",
                schema={
                    "type": "object",
                    "properties": {"outcome": {"type": "string"}},
                    "required": ["outcome"],
                    "additionalProperties": False,
                },
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(content, '{"outcome":"skipped"}')
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertTrue(payload["provider"]["require_parameters"])
        self.assertEqual(payload["plugins"], [{"id": "response-healing"}])

    def test_http_error_extracts_safe_openrouter_details(self):
        body = io.BytesIO(
            b'{"error":{"code":429,"message":"Rate limit reached",'
            b'"metadata":{"error_type":"rate_limit_exceeded","provider_name":"Example"}}}'
        )
        error = urllib.error.HTTPError("https://example.invalid", 429, "error", {}, body)

        detail = OpenRouterClient._http_error_detail(error)

        self.assertIn("429", detail)
        self.assertIn("rate_limit_exceeded", detail)
        self.assertIn("Example", detail)
        self.assertIn("Rate limit reached", detail)


if __name__ == "__main__":
    unittest.main()
