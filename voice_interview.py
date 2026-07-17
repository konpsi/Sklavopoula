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
DEFAULT_MODEL = "openrouter/free"


class InterviewError(RuntimeError):
    """A user-safe failure in the interview pipeline."""


@dataclass
class InterviewSession:
    session_id: str
    current_question_id: str = QUESTIONNAIRE[0]["id"]
    answers: list[dict[str, Any]] = field(default_factory=list)

    @property
    def answered_ids(self) -> set[str]:
        return {answer["question_id"] for answer in self.answers}

    def pending_items(self) -> list[dict[str, str]]:
        return [item for item in QUESTIONNAIRE if item["id"] not in self.answered_ids]


class OpenRouterClient:
    def __init__(self) -> None:
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        self.model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def initial_question(self, first_item: dict[str, str]) -> str:
        content = self._completion(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a warm, concise CV interviewer. Start the interview by asking "
                        "exactly one brief question that covers the supplied questionnaire item. "
                        "Return only a JSON object with a question field."
                    ),
                },
                {"role": "user", "content": json.dumps(first_item, ensure_ascii=False)},
            ],
            max_tokens=100,
        )
        try:
            result = self._parse_json_object(content)
        except json.JSONDecodeError as exc:
            raise InterviewError("OpenRouter returned an unexpected response.") from exc
        question = str(result.get("question") or "").strip()
        if not question:
            raise InterviewError("OpenRouter did not return the first interview question.")
        return question

    def next_question(
        self,
        current_item: dict[str, str],
        transcript: str,
        answers: list[dict[str, Any]],
        pending_items: list[dict[str, str]],
    ) -> dict[str, Any]:
        if not self.configured:
            raise InterviewError("OPENROUTER_API_KEY is not configured on the server.")

        allowed = [
            {"id": item["id"], "title": item["title"], "outline_question": item["question"]}
            for item in pending_items
        ]
        system_prompt = (
            "You are a warm, concise CV interviewer. The application, not you, stores the user's "
            "answer under the current questionnaire attribute. Acknowledge the answer in one short "
            "sentence, then choose the most useful next item only from the supplied pending items. "
            "Ask one natural question that covers that item's outline. Do not ask for information "
            "outside the questionnaire. Never claim that you changed or inferred a stored answer. "
            "Return only a JSON object with acknowledgement, next_question_id, and question. "
            "If pending_items is empty, next_question_id and question must be null and the "
            "acknowledgement should briefly say the questionnaire is complete."
        )
        user_payload = {
            "current_item": current_item,
            "user_answer": transcript,
            "saved_answers": answers,
            "pending_items": allowed,
        }
        content = self._completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            max_tokens=220,
        )
        try:
            return self._parse_json_object(content)
        except json.JSONDecodeError as exc:
            raise InterviewError("OpenRouter returned an unexpected response.") from exc

    def _completion(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        if not self.configured:
            raise InterviewError("OPENROUTER_API_KEY is not configured on the server.")
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "messages": messages,
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
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise InterviewError(f"OpenRouter returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise InterviewError(f"OpenRouter could not be reached: {exc}") from exc

        try:
            content = result["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            return str(content)
        except (KeyError, IndexError, TypeError) as exc:
            raise InterviewError("OpenRouter returned an unexpected response.") from exc

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

    def start(self, session_id: str) -> dict[str, Any]:
        if not self.configured:
            raise InterviewError("Set OPENROUTER_API_KEY before starting the voice interview.")
        session = InterviewSession(session_id=session_id)
        with self._sessions_lock:
            self.sessions[session_id] = session
        self._save(session)
        first = QUESTION_BY_ID[session.current_question_id]
        warning = None
        try:
            question = self.llm.initial_question(first)
        except InterviewError:
            question = first["question"]
            warning = "The AI service was unavailable, so the first outline question was used."
        result = {
            "question_number": 1,
            "attribute": first["title"],
            "question": question,
            "complete": False,
        }
        if warning:
            result["warning"] = warning
        return result

    def answer(self, session_id: str, audio_path: str) -> dict[str, Any]:
        session = self._session(session_id)
        transcript = self.transcriber.transcribe(audio_path)
        current = QUESTION_BY_ID[session.current_question_id]
        answer_record = {
            "question_number": next(
                index for index, item in enumerate(QUESTIONNAIRE, start=1) if item["id"] == current["id"]
            ),
            "question_id": current["id"],
            "attribute": current["title"],
            "value": transcript,
        }
        session.answers.append(answer_record)
        pending = session.pending_items()

        warning = None
        try:
            llm_turn = self.llm.next_question(current, transcript, session.answers, pending)
        except InterviewError as exc:
            warning = str(exc)
            llm_turn = self._fallback_turn(pending)

        next_item = self._validated_next_item(llm_turn.get("next_question_id"), pending)
        acknowledgement = str(llm_turn.get("acknowledgement") or "Thanks, I've noted that.").strip()
        if next_item is None:
            question = None
            spoken_response = acknowledgement
            complete = True
        else:
            session.current_question_id = next_item["id"]
            proposed_question = str(llm_turn.get("question") or "").strip()
            question = proposed_question or next_item["question"]
            spoken_response = f"{acknowledgement} {question}".strip()
            complete = False

        self._save(session)
        result = {
            "transcript": transcript,
            "saved_answer": answer_record,
            "response": spoken_response,
            "question": question,
            "complete": complete,
            "answered": len(session.answers),
            "total": len(QUESTIONNAIRE),
        }
        if warning:
            result["warning"] = "The AI service was unavailable, so the questionnaire continued in order."
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
        proposed_id: Any, pending: list[dict[str, str]]
    ) -> dict[str, str] | None:
        if not pending:
            return None
        allowed = {item["id"]: item for item in pending}
        return allowed.get(str(proposed_id), pending[0])

    @staticmethod
    def _fallback_turn(pending: list[dict[str, str]]) -> dict[str, Any]:
        if not pending:
            return {
                "acknowledgement": "Thank you. Your CV questionnaire is complete.",
                "next_question_id": None,
                "question": None,
            }
        item = pending[0]
        return {
            "acknowledgement": "Thanks, I've noted that.",
            "next_question_id": item["id"],
            "question": item["question"],
        }

    def _save(self, session: InterviewSession) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / f"{session.session_id}.json"
        payload = {
            "session_id": session.session_id,
            "current_question_id": session.current_question_id,
            "answers": session.answers,
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
