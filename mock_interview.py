"""Conversational, CV-aware mock interview orchestration."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from voice_interview import (
    InterviewError,
    LocalSpeechSynthesizer,
    LocalTranscriber,
    OpenRouterClient,
)


MIN_QUESTIONS = 5
MAX_QUESTIONS = 10


@dataclass
class MockInterviewSession:
    session_id: str
    job_title: str
    cv_context: dict[str, str]
    company_context: dict[str, str]
    outline: dict[str, Any]
    turns: list[dict[str, Any]] = field(default_factory=list)
    covered_topics: list[str] = field(default_factory=list)
    complete: bool = False

    @property
    def target_questions(self) -> int:
        proposed = self.outline.get("recommended_question_count", 7)
        try:
            return max(MIN_QUESTIONS, min(MAX_QUESTIONS, int(proposed)))
        except (TypeError, ValueError):
            return 7

    @property
    def answered_questions(self) -> int:
        return sum(1 for turn in self.turns if turn.get("user_transcript"))


class MockInterviewService:
    """Create an interview plan, then conduct a flexible voice conversation."""

    def __init__(self, data_dir: str) -> None:
        self.data_dir = Path(data_dir)
        self.sessions: dict[str, MockInterviewSession] = {}
        self._sessions_lock = threading.Lock()
        self.llm = OpenRouterClient()
        self.transcriber = LocalTranscriber()
        self.synthesizer = LocalSpeechSynthesizer()

    def start(
        self,
        session_id: str,
        job_title: str,
        cv_context: dict[str, str],
        company_context: dict[str, str],
    ) -> dict[str, Any]:
        clean_title = " ".join(job_title.split())
        if not clean_title:
            raise InterviewError("Please enter the job title you want to interview for.")
        if len(clean_title) > 160:
            raise InterviewError("Please keep the job title under 160 characters.")
        if not self.llm.configured:
            raise InterviewError("Set OPENROUTER_API_KEY before starting the mock interview.")

        outline = self._generate_outline(clean_title, cv_context, company_context)
        session = MockInterviewSession(
            session_id=session_id,
            job_title=clean_title,
            cv_context=cv_context,
            company_context=company_context,
            outline=outline,
        )
        first_turn = self._generate_next_turn(session, first_turn=True)
        session.complete = first_turn["complete"]
        session.covered_topics = first_turn["covered_topics"]
        session.turns.append(self._turn_record(session, first_turn))
        with self._sessions_lock:
            self.sessions[session_id] = session
        self._save_transcript(session)
        return self._response(session, first_turn)

    def answer(self, session_id: str, audio_path: str) -> dict[str, Any]:
        session = self._session(session_id)
        if session.complete:
            raise InterviewError("This mock interview is already complete.")
        if not session.turns or session.turns[-1].get("user_transcript") is not None:
            raise InterviewError("There is no active interview question to answer.")

        transcript = self.transcriber.transcribe(audio_path)
        current_turn = session.turns[-1]
        current_turn["user_transcript"] = transcript
        try:
            next_turn = self._generate_next_turn(session, first_turn=False)
        except InterviewError as exc:
            print(f"[OpenRouter mock interview] {exc}", flush=True)
            retry = {
                "response": (
                    "I had a temporary problem continuing the interview. "
                    "Could you briefly repeat your last answer?"
                ),
                "question": "Could you briefly repeat your last answer?",
                "complete": False,
                "covered_topics": session.covered_topics,
            }
            session.turns.append(self._turn_record(session, retry, error=str(exc)))
            self._save_transcript(session)
            result = self._response(session, retry, transcript=transcript)
            result["warning"] = "The AI interviewer was temporarily unavailable."
            return result

        session.complete = next_turn["complete"]
        session.covered_topics = next_turn["covered_topics"]
        session.turns.append(self._turn_record(session, next_turn))
        self._save_transcript(session)
        return self._response(session, next_turn, transcript=transcript)

    def synthesize(self, text: str) -> bytes:
        clean_text = text.strip()
        if not clean_text or len(clean_text) > 1600:
            raise InterviewError("The speech text is empty or too long.")
        return self.synthesizer.synthesize(clean_text)

    def _generate_outline(
        self,
        job_title: str,
        cv_context: dict[str, str],
        company_context: dict[str, str],
    ) -> dict[str, Any]:
        system_prompt = (
            "You design a realistic conversational job interview outline. Use only the supplied "
            "CV and company-page facts, together with reasonable general expectations for the job "
            "title. Do not invent company facts, CV facts, or a detailed job description that was "
            "not supplied. Build a coherent progression from introduction and motivation through "
            "role-relevant experience, behavioral evidence, and candidate questions. Each section "
            "is guidance for a flexible interviewer, not a mandatory script."
        )
        payload = {
            "job_title": job_title,
            "cv": cv_context,
            "company_page": company_context,
        }
        result = self.llm.complete_json(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            max_tokens=1200,
            schema_name="mock_interview_outline",
            schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "recommended_question_count": {
                        "type": "integer",
                        "minimum": MIN_QUESTIONS,
                        "maximum": MAX_QUESTIONS,
                    },
                    "sections": {
                        "type": "array",
                        "minItems": 4,
                        "maxItems": 7,
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "goal": {"type": "string"},
                                "signals_to_assess": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "suggested_questions": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": [
                                "title",
                                "goal",
                                "signals_to_assess",
                                "suggested_questions",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["summary", "recommended_question_count", "sections"],
                "additionalProperties": False,
            },
        )
        summary = str(result.get("summary") or "").strip()
        sections = result.get("sections")
        if not summary or not isinstance(sections, list) or not sections:
            raise InterviewError("OpenRouter returned an invalid interview outline.")
        result["summary"] = summary
        return result

    def _generate_next_turn(
        self, session: MockInterviewSession, first_turn: bool
    ) -> dict[str, Any]:
        must_finish = session.answered_questions >= session.target_questions
        may_finish = session.answered_questions >= MIN_QUESTIONS
        system_prompt = (
            "You are conducting a realistic voice mock interview. Speak warmly, professionally, "
            "and concisely. Use the outline as flexible guidance, not a rigid questionnaire. You "
            "receive the full interview transcript plus the CV, company context, job title, and "
            "outline on every turn. Follow up naturally when an answer contains a useful thread; "
            "otherwise move to an uncovered part of the outline. Never repeat a question already "
            "answered. If the candidate asks what a question means, briefly explain and rephrase it "
            "instead of moving on. Do not coach, score, or critique answers during the interview. "
            "Ask only one question at a time. The response field is the exact text spoken aloud and "
            "must include the question when question is not null. On the first turn, welcome the "
            "candidate to the interview and ask a natural opening question. When must_finish is "
            "true, thank the candidate, close the interview, set complete to true, and ask no "
            "question. While may_finish is false, only finish early if the candidate clearly asks "
            "to end the interview."
        )
        payload = {
            "job_title": session.job_title,
            "cv": session.cv_context,
            "company_page": session.company_context,
            "interview_outline": session.outline,
            "covered_topics": session.covered_topics,
            "transcript": session.turns,
            "first_turn": first_turn,
            "may_finish": may_finish,
            "must_finish": must_finish,
        }
        result = self.llm.complete_json(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            max_tokens=320,
            schema_name="mock_interview_turn",
            schema={
                "type": "object",
                "properties": {
                    "response": {"type": "string"},
                    "question": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                    },
                    "complete": {"type": "boolean"},
                    "covered_topics": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["response", "question", "complete", "covered_topics"],
                "additionalProperties": False,
            },
        )
        response = str(result.get("response") or "").strip()
        question_value = result.get("question")
        question = str(question_value).strip() if question_value is not None else None
        complete = bool(result.get("complete"))
        if must_finish:
            complete = True
            question = None
        elif first_turn and complete:
            raise InterviewError("OpenRouter ended the interview before asking a question.")
        if not response or (not complete and not question) or (complete and question):
            raise InterviewError("OpenRouter returned an invalid interview turn.")
        topics = result.get("covered_topics")
        if not isinstance(topics, list):
            topics = session.covered_topics
        return {
            "response": response,
            "question": question,
            "complete": complete,
            "covered_topics": [str(topic).strip() for topic in topics if str(topic).strip()],
        }

    @staticmethod
    def _turn_record(
        session: MockInterviewSession,
        generated: dict[str, Any],
        error: str | None = None,
    ) -> dict[str, Any]:
        record = {
            "turn_number": len(session.turns) + 1,
            "assistant_response": generated["response"],
            "question": generated["question"],
            "user_transcript": None,
        }
        if error:
            record["error"] = error
        return record

    @staticmethod
    def _response(
        session: MockInterviewSession,
        generated: dict[str, Any],
        transcript: str | None = None,
    ) -> dict[str, Any]:
        result = {
            "response": generated["response"],
            "question": generated["question"],
            "complete": generated["complete"],
            "answered": session.answered_questions,
            "target": session.target_questions,
            "outline_summary": session.outline["summary"],
            "cv_source": session.cv_context.get("label", session.cv_context.get("source", "CV")),
        }
        if transcript is not None:
            result["transcript"] = transcript
        return result

    def _session(self, session_id: str) -> MockInterviewSession:
        with self._sessions_lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise InterviewError("This mock interview expired. Reload the page to start again.")
        return session

    def _save_transcript(self, session: MockInterviewSession) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            path = self.data_dir / f"{session.session_id}.txt"
            lines: list[str] = []
            for turn in session.turns:
                assistant = str(turn.get("assistant_response") or "").strip()
                candidate = str(turn.get("user_transcript") or "").strip()
                if assistant:
                    lines.append(f"Interviewer: {assistant}")
                if candidate:
                    lines.append(f"Candidate: {candidate}")
            transcript = "\n\n".join(lines).strip() + "\n"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(transcript, encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            raise InterviewError(f"The interview transcript could not be saved locally: {exc}") from exc
