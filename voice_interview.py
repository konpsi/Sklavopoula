"""Local speech and OpenRouter orchestration for the CV voice interview."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from questionnaire import QUESTIONNAIRE, QUESTION_BY_ID


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash-lite"


class InterviewError(RuntimeError):
    """A user-safe failure in the interview pipeline."""


@dataclass
class InterviewSession:
    session_id: str
    current_question_id: str | None = None
    current_question_text: str | None = None
    profile: dict[str, dict[str, Any]] = field(default_factory=dict)
    turns: list[dict[str, Any]] = field(default_factory=list)
    clarification_attempts: dict[str, int] = field(default_factory=dict)
    company_context: dict[str, str] | None = None

    @property
    def resolved_ids(self) -> set[str]:
        return set(self.profile)

    def pending_items(self) -> list[dict[str, Any]]:
        return [item for item in QUESTIONNAIRE if item["id"] not in self.resolved_ids]


class OpenRouterClient:
    def __init__(self) -> None:
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        self.model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def evaluate_answer(
        self,
        current_item: dict[str, Any],
        asked_question: str,
        transcript: str,
        clarification_attempts: int,
        company_context: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        system_prompt = (
            "You evaluate one spoken reply in a voice-guided CV interview. Decide whether the "
            "reply supplies usable information for the current questionnaire item. Return captured "
            "when it answers the item, clarify when it asks for an explanation, is ambiguous, or "
            "does not yet contain usable information, and skipped when the user clearly says they "
            "have nothing to add or prefer not to answer. A phrase such as 'explain that', 'what do "
            "you mean', or 'repeat the question' is always clarify, never captured. 'I don't have "
            "any' or 'I prefer not to say' is skipped; 'I don't know what you mean' is clarify. "
            "For captured, normalized_value must faithfully clean up only facts present in the "
            "transcript, without guessing, and assistant_reply must be null. For clarify, "
            "normalized_value must be null and assistant_reply must directly answer the user's "
            "need, then ask for the same information in a simpler way. For skipped, both fields "
            "must be null. Keep spoken replies brief. "
            f"{self._company_instruction(company_context)}"
        )
        user_payload = {
            "questionnaire_item": current_item,
            "question_the_user_heard": asked_question,
            "raw_transcript": transcript,
            "previous_clarification_attempts": clarification_attempts,
            "clarification_guidance": current_item.get("clarification"),
            "company_context": company_context,
        }
        content = self._completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            max_tokens=220,
            schema_name="cv_answer_evaluation",
            schema={
                "type": "object",
                "properties": {
                    "outcome": {"enum": ["captured", "clarify", "skipped"]},
                    "normalized_value": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Grounded CV-ready value for captured, otherwise null.",
                    },
                    "assistant_reply": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "A clarification reply only when outcome is clarify.",
                    },
                },
                "required": ["outcome", "normalized_value", "assistant_reply"],
                "additionalProperties": False,
            },
        )
        try:
            result = self._parse_json_object(content)
        except json.JSONDecodeError as exc:
            raise InterviewError("OpenRouter returned an unexpected response.") from exc
        return self._validate_evaluation(result)

    def select_next_question(
        self,
        profile: dict[str, dict[str, Any]],
        pending_items: list[dict[str, Any]],
        last_resolution: dict[str, Any] | None,
        company_context: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not self.configured:
            raise InterviewError("OPENROUTER_API_KEY is not configured on the server.")

        allowed = [
            {
                "id": item["id"],
                "title": item["title"],
                "goal": item["goal"],
                "outline_question": item["question"],
                "complete_when": item["complete_when"],
            }
            for item in pending_items
        ]
        system_prompt = (
            "You are a warm, concise CV interviewer. Choose exactly one item from pending_items "
            "that is most natural to ask next. Briefly transition from the last resolved answer, "
            "then conversationally ask one question that covers the chosen item's goal. Never ask "
            "for an item outside pending_items and never invent profile facts. If this is the first "
            "question, transition must be a short welcome. If pending_items is empty, return a brief "
            "completion transition and null for next_question_id and question. "
            f"{self._company_instruction(company_context)}"
        )
        user_payload = {
            "saved_profile": profile,
            "last_resolution": last_resolution,
            "pending_items": allowed,
            "company_context": company_context,
        }
        pending_ids = [item["id"] for item in pending_items]
        content = self._completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            max_tokens=220,
            schema_name="cv_interview_turn",
            schema={
                "type": "object",
                "properties": {
                    "transition": {
                        "type": "string",
                        "description": "A brief welcome, acknowledgement, or completion sentence.",
                    },
                    "next_question_id": {
                        "enum": pending_ids + [None],
                        "description": "An ID from pending_items, or null when none remain.",
                    },
                    "question": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "One brief next question, or null when complete.",
                    },
                },
                "required": ["transition", "next_question_id", "question"],
                "additionalProperties": False,
            },
        )
        try:
            return self._parse_json_object(content)
        except json.JSONDecodeError as exc:
            raise InterviewError("OpenRouter returned an unexpected response.") from exc

    @staticmethod
    def _validate_evaluation(result: dict[str, Any]) -> dict[str, Any]:
        outcome = result.get("outcome")
        value = result.get("normalized_value")
        reply = result.get("assistant_reply")
        if outcome not in {"captured", "clarify", "skipped"}:
            raise InterviewError("OpenRouter returned an invalid answer outcome.")
        if outcome == "captured":
            value = str(value or "").strip()
            if not value or reply is not None:
                raise InterviewError("OpenRouter returned an invalid captured answer.")
            return {"outcome": outcome, "normalized_value": value, "assistant_reply": None}
        if outcome == "clarify":
            reply = str(reply or "").strip()
            if not reply or value is not None:
                raise InterviewError("OpenRouter returned an invalid clarification.")
            return {"outcome": outcome, "normalized_value": None, "assistant_reply": reply}
        if value is not None or reply is not None:
            raise InterviewError("OpenRouter returned an invalid skipped answer.")
        return {"outcome": outcome, "normalized_value": None, "assistant_reply": None}

    def _completion(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        schema_name: str,
        schema: dict[str, Any],
    ) -> str:
        if not self.configured:
            raise InterviewError("OPENROUTER_API_KEY is not configured on the server.")
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
            "provider": {"require_parameters": True},
            "plugins": [{"id": "response-healing"}],
        }
        request = urllib.request.Request(
            OPENROUTER_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost",
                "X-Title": "Local Voice CV Builder",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = self._http_error_detail(exc)
            raise InterviewError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise InterviewError(f"OpenRouter could not be reached: {exc}") from exc

        if isinstance(result, dict) and result.get("error"):
            raise InterviewError(f"OpenRouter error: {self._format_api_error(result['error'])}")

        try:
            content = result["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            return str(content)
        except (KeyError, IndexError, TypeError) as exc:
            raise InterviewError("OpenRouter returned an unexpected response.") from exc

    @classmethod
    def _http_error_detail(cls, exc: urllib.error.HTTPError) -> str:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict) and "error" in payload:
                return cls._format_api_error(payload["error"])
        except json.JSONDecodeError:
            pass
        return cls._safe_detail(raw or exc.reason)

    @classmethod
    def _format_api_error(cls, error: Any) -> str:
        if not isinstance(error, dict):
            return cls._safe_detail(error)
        code = error.get("code")
        message = cls._safe_detail(error.get("message") or "Unknown API error")
        metadata = error.get("metadata") if isinstance(error.get("metadata"), dict) else {}
        error_type = metadata.get("error_type")
        provider = metadata.get("provider_name")
        labels = [str(value) for value in (code, error_type, provider) if value not in (None, "")]
        return f"{' / '.join(labels)}: {message}" if labels else message

    @staticmethod
    def _safe_detail(value: Any) -> str:
        detail = " ".join(str(value).split())
        return detail[:240] or "No error details were returned."

    @staticmethod
    def _parse_json_object(content: str) -> dict[str, Any]:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end < start:
            raise json.JSONDecodeError("No JSON object", cleaned, 0)
        return json.loads(cleaned[start : end + 1])

    @staticmethod
    def _company_instruction(company_context: dict[str, str] | None) -> str:
        if not company_context:
            return (
                "No company website context was provided, so gather information for a general CV."
            )
        return (
            "Company website context is available. Use it to ask questions that help create a CV "
            "personalized to that company, while still collecting the questionnaire fields."
        )


class LocalTranscriber:
    """Lazy faster-whisper wrapper; model inference stays on this machine."""

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()

    def _get_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise InterviewError(
                    "Local STT is not installed. Run: pip install -r requirements.txt"
                ) from exc
            model_name = os.environ.get("WHISPER_MODEL", "tiny.en")
            device = os.environ.get("WHISPER_DEVICE", "cpu")
            compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
            self._model = WhisperModel(model_name, device=device, compute_type=compute_type)
        return self._model

    def transcribe(self, audio_path: str) -> str:
        with self._lock:
            model = self._get_model()
            language = os.environ.get("STT_LANGUAGE", "").strip() or None
            segments, _ = model.transcribe(
                audio_path,
                beam_size=1,
                vad_filter=True,
                language=language,
            )
            transcript = " ".join(segment.text.strip() for segment in segments).strip()
        if not transcript:
            raise InterviewError("I could not hear any speech. Please try again.")
        return transcript


class LocalSpeechSynthesizer:
    """Generate speech with the operating system voice through pyttsx3."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def synthesize(self, text: str) -> bytes:
        try:
            import pyttsx3
        except ImportError as exc:
            raise InterviewError(
                "Local TTS is not installed. Run: pip install -r requirements.txt"
            ) from exc

        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_path = temp_file.name
            with self._lock:
                engine = pyttsx3.init()
                engine.setProperty("rate", int(os.environ.get("TTS_RATE", "175")))
                engine.save_to_file(text, temp_path)
                engine.runAndWait()
                engine.stop()
            audio = Path(temp_path).read_bytes()
            if len(audio) < 44:
                raise InterviewError("Local TTS did not produce playable audio.")
            return audio
        except InterviewError:
            raise
        except Exception as exc:
            raise InterviewError(f"Local TTS failed: {exc}") from exc
        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)


class VoiceInterviewService:
    def __init__(self, data_dir: str) -> None:
        self.data_dir = Path(data_dir)
        self.sessions: dict[str, InterviewSession] = {}
        self._sessions_lock = threading.Lock()
        self.llm = OpenRouterClient()
        self.transcriber = LocalTranscriber()
        self.synthesizer = LocalSpeechSynthesizer()

    @property
    def configured(self) -> bool:
        return self.llm.configured

    def start(
        self, session_id: str, company_context: dict[str, str] | None = None
    ) -> dict[str, Any]:
        if not self.configured:
            raise InterviewError("Set OPENROUTER_API_KEY before starting the voice interview.")
        session = InterviewSession(session_id=session_id, company_context=company_context)
        with self._sessions_lock:
            self.sessions[session_id] = session
        warning = None
        try:
            selected = self.llm.select_next_question(
                session.profile,
                session.pending_items(),
                last_resolution=None,
                company_context=session.company_context,
            )
        except InterviewError as exc:
            print(f"[OpenRouter] {exc}", flush=True)
            selected = self._fallback_selection(session.pending_items(), last_resolution=None)
            warning = f"{exc} The first outline question was used instead."
        question, spoken_response, complete = self._apply_selection(session, selected)
        current = QUESTION_BY_ID[session.current_question_id] if session.current_question_id else None
        self._save(session)
        result = {
            "question_number": self._question_number(current["id"]) if current else None,
            "attribute": current["title"] if current else None,
            "question": question,
            "response": spoken_response,
            "complete": complete,
            "company_context": bool(company_context),
        }
        if warning:
            result["warning"] = warning
        return result

    def answer(self, session_id: str, audio_path: str) -> dict[str, Any]:
        session = self._session(session_id)
        if session.current_question_id is None:
            raise InterviewError("This questionnaire is already complete.")
        transcript = self.transcriber.transcribe(audio_path)
        current = QUESTION_BY_ID[session.current_question_id]
        asked_question = session.current_question_text or current["question"]
        attempts = session.clarification_attempts.get(current["id"], 0)
        try:
            evaluation = self.llm.evaluate_answer(
                current,
                asked_question,
                transcript,
                attempts,
                company_context=session.company_context,
            )
        except InterviewError as exc:
            print(f"[OpenRouter] {exc}", flush=True)
            reply = "I couldn't reliably process that response. Please say it again."
            session.current_question_text = reply
            session.turns.append(
                self._turn_record(
                    session,
                    current,
                    asked_question,
                    transcript,
                    "processing_error",
                    None,
                    reply,
                    error=str(exc),
                )
            )
            self._save(session)
            return {
                "transcript": transcript,
                "saved_answer": None,
                "outcome": "processing_error",
                "response": reply,
                "question": reply,
                "complete": False,
                "answered": len(session.profile),
                "total": len(QUESTIONNAIRE),
                "warning": str(exc),
            }

        if evaluation["outcome"] == "clarify":
            reply = evaluation["assistant_reply"]
            attempts += 1
            session.clarification_attempts[current["id"]] = attempts
            if attempts >= 2 and "skip" not in reply.lower():
                reply = f"{reply} You can also say skip if you would rather move on."
            session.current_question_text = reply
            session.turns.append(
                self._turn_record(
                    session,
                    current,
                    asked_question,
                    transcript,
                    "clarify",
                    None,
                    reply,
                )
            )
            self._save(session)
            return {
                "transcript": transcript,
                "saved_answer": None,
                "outcome": "clarify",
                "response": reply,
                "question": reply,
                "complete": False,
                "answered": len(session.profile),
                "total": len(QUESTIONNAIRE),
            }

        outcome = evaluation["outcome"]
        profile_record = {
            "question_number": self._question_number(current["id"]),
            "question_id": current["id"],
            "attribute": current["title"],
            "status": outcome,
            "value": evaluation["normalized_value"],
            "raw_transcript": transcript,
        }
        turn_record = self._turn_record(
            session,
            current,
            asked_question,
            transcript,
            outcome,
            evaluation["normalized_value"],
            None,
        )
        session.profile[current["id"]] = profile_record
        session.turns.append(turn_record)
        try:
            self._save(session)
        except InterviewError:
            session.profile.pop(current["id"], None)
            session.turns.pop()
            raise

        session.clarification_attempts.pop(current["id"], None)
        last_resolution = {
            "question_id": current["id"],
            "attribute": current["title"],
            "status": outcome,
            "value": evaluation["normalized_value"],
        }
        warning = None
        pending = session.pending_items()
        try:
            selected = self.llm.select_next_question(
                session.profile,
                pending,
                last_resolution,
                company_context=session.company_context,
            )
        except InterviewError as exc:
            print(f"[OpenRouter] {exc}", flush=True)
            selected = self._fallback_selection(pending, last_resolution)
            warning = f"{exc} The questionnaire continued in order."

        question, spoken_response, complete = self._apply_selection(session, selected)
        turn_record["assistant_response"] = spoken_response
        self._save(session)
        result = {
            "transcript": transcript,
            "saved_answer": profile_record,
            "outcome": outcome,
            "response": spoken_response,
            "question": question,
            "complete": complete,
            "answered": len(session.profile),
            "total": len(QUESTIONNAIRE),
        }
        if warning:
            result["warning"] = warning
        return result

    def synthesize(self, text: str) -> bytes:
        clean_text = text.strip()
        if not clean_text or len(clean_text) > 1200:
            raise InterviewError("The speech text is empty or too long.")
        return self.synthesizer.synthesize(clean_text)

    def _session(self, session_id: str) -> InterviewSession:
        with self._sessions_lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise InterviewError("This interview session expired. Reload the page to start again.")
        return session

    @staticmethod
    def _validated_next_item(
        proposed_id: Any, pending: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        if not pending:
            return None
        allowed = {item["id"]: item for item in pending}
        return allowed.get(str(proposed_id), pending[0])

    @staticmethod
    def _fallback_selection(
        pending: list[dict[str, Any]], last_resolution: dict[str, Any] | None
    ) -> dict[str, Any]:
        if not pending:
            return {
                "transition": "Thank you. Your CV questionnaire is complete.",
                "next_question_id": None,
                "question": None,
            }
        item = pending[0]
        if last_resolution is None:
            transition = "Let's build your CV together."
        elif last_resolution.get("status") == "skipped":
            transition = "No problem, we can move on."
        else:
            transition = "Thanks, I've noted that."
        return {
            "transition": transition,
            "next_question_id": item["id"],
            "question": item["question"],
        }

    def _apply_selection(
        self, session: InterviewSession, selected: dict[str, Any]
    ) -> tuple[str | None, str, bool]:
        pending = session.pending_items()
        next_item = self._validated_next_item(selected.get("next_question_id"), pending)
        transition = str(selected.get("transition") or "").strip()
        if next_item is None:
            session.current_question_id = None
            session.current_question_text = None
            response = transition or "Thank you. Your CV questionnaire is complete."
            return None, response, True
        proposed_question = str(selected.get("question") or "").strip()
        proposed_id = selected.get("next_question_id")
        question = (
            proposed_question
            if str(proposed_id) == next_item["id"] and proposed_question
            else next_item["question"]
        )
        session.current_question_id = next_item["id"]
        session.current_question_text = question
        response = f"{transition} {question}".strip()
        return question, response, False

    @staticmethod
    def _question_number(question_id: str) -> int:
        return next(
            index for index, item in enumerate(QUESTIONNAIRE, start=1) if item["id"] == question_id
        )

    @staticmethod
    def _turn_record(
        session: InterviewSession,
        current: dict[str, Any],
        asked_question: str,
        transcript: str,
        outcome: str,
        normalized_value: str | None,
        assistant_response: str | None,
        error: str | None = None,
    ) -> dict[str, Any]:
        record = {
            "turn_number": len(session.turns) + 1,
            "question_id": current["id"],
            "attribute": current["title"],
            "question_text": asked_question,
            "raw_transcript": transcript,
            "outcome": outcome,
            "normalized_value": normalized_value,
            "assistant_response": assistant_response,
        }
        if error:
            record["error"] = error
        return record

    def _save(self, session: InterviewSession) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            path = self.data_dir / f"{session.session_id}.json"
            payload = {
                "version": 2,
                "session_id": session.session_id,
                "current_question_id": session.current_question_id,
                "current_question_text": session.current_question_text,
                "profile": session.profile,
                "turns": session.turns,
                "company_context": session.company_context,
            }
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            temporary.replace(path)
        except OSError as exc:
            raise InterviewError(f"The interview could not be saved locally: {exc}") from exc
