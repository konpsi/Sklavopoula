import json
import tempfile
import unittest
from pathlib import Path

from questionnaire import QUESTIONNAIRE
from voice_interview import InterviewError, OpenRouterClient, VoiceInterviewService


class FakeTranscriber:
    def __init__(self, transcript):
        self.transcript = transcript

    def transcribe(self, _audio_path):
        return self.transcript


class FakeLLM:
    configured = True

    def __init__(self, proposed_id=None):
        self.proposed_id = proposed_id
        self.calls = []

    def initial_question(self, first_item):
        return f"LLM: {first_item['question']}"

    def next_question(self, current, transcript, answers, pending):
        self.calls.append((current, transcript, answers, pending))
        item = next(
            (candidate for candidate in pending if candidate["id"] == self.proposed_id),
            pending[0] if pending else None,
        )
        return {
            "acknowledgement": "Got it.",
            "next_question_id": item["id"] if item else None,
            "question": f"Next: {item['title']}?" if item else None,
        }


class VoiceInterviewServiceTests(unittest.TestCase):
    def make_service(self, directory, transcript="Ada Lovelace", proposed_id=None):
        service = VoiceInterviewService(directory)
        service.llm = FakeLLM(proposed_id)
        service.transcriber = FakeTranscriber(transcript)
        return service

    def test_start_returns_first_question_and_creates_local_state(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(directory)
            turn = service.start("a" * 32)

            self.assertEqual(turn["attribute"], QUESTIONNAIRE[0]["title"])
            self.assertTrue(turn["question"].startswith("LLM:"))
            self.assertFalse(turn["complete"])
            saved = json.loads(Path(directory, f"{'a' * 32}.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["answers"], [])

    def test_answer_is_saved_under_question_number_and_attribute(self):
        with tempfile.TemporaryDirectory() as directory:
            target = QUESTIONNAIRE[-1]["id"]
            service = self.make_service(directory, proposed_id=target)
            service.start("b" * 32)
            turn = service.answer("b" * 32, "unused.webm")

            self.assertEqual(turn["saved_answer"]["question_number"], 1)
            self.assertEqual(turn["saved_answer"]["attribute"], "Full name")
            self.assertEqual(turn["saved_answer"]["value"], "Ada Lovelace")
            self.assertEqual(service.sessions["b" * 32].current_question_id, target)

    def test_invalid_llm_question_id_falls_back_to_first_pending_item(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(directory)
            service.llm.proposed_id = "not-in-the-questionnaire"
            service.start("c" * 32)
            turn = service.answer("c" * 32, "unused.webm")

            self.assertEqual(
                service.sessions["c" * 32].current_question_id,
                QUESTIONNAIRE[1]["id"],
            )
            self.assertEqual(turn["answered"], 1)

    def test_last_answer_completes_the_questionnaire(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(directory)
            session_id = "e" * 32
            service.start(session_id)

            for _ in QUESTIONNAIRE:
                turn = service.answer(session_id, "unused.webm")

            self.assertTrue(turn["complete"])
            self.assertIsNone(turn["question"])
            self.assertEqual(turn["answered"], len(QUESTIONNAIRE))
            self.assertEqual(len(service.sessions[session_id].answers), len(QUESTIONNAIRE))

    def test_missing_key_is_reported_before_interview_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            service = VoiceInterviewService(directory)
            service.llm.api_key = ""
            with self.assertRaisesRegex(InterviewError, "OPENROUTER_API_KEY"):
                service.start("d" * 32)


class OpenRouterParsingTests(unittest.TestCase):
    def test_parses_json_inside_markdown_fence(self):
        parsed = OpenRouterClient._parse_json_object(
            '```json\n{"acknowledgement":"Thanks","next_question_id":null,"question":null}\n```'
        )
        self.assertEqual(parsed["acknowledgement"], "Thanks")
        self.assertIsNone(parsed["next_question_id"])


if __name__ == "__main__":
    unittest.main()
