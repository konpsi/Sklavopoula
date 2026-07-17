"""Feedback data structures and validation for interview results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


RiskCategory = Literal["red_flag", "contradiction", "missed_opportunity"]


@dataclass
class RiskFinding:
    """A negative or cautionary interview finding shown in the red results box."""

    id: str
    category: RiskCategory
    title: str
    summary: str
    evidence: str
    severity: Literal["low", "medium", "high"] = "medium"
    related_question_id: str | None = None
    suggested_fix: str | None = None


@dataclass
class StrengthFinding:
    """A strong answer or positive pattern shown in the green results box."""

    id: str
    title: str
    summary: str
    evidence: str
    related_question_id: str | None = None


@dataclass
class SuggestedImprovement:
    """A concrete next action shown under the finding boxes."""

    id: str
    title: str
    action: str
    priority: Literal["low", "medium", "high"] = "medium"
    related_finding_ids: list[str] = field(default_factory=list)


@dataclass
class InterviewFeedback:
    red_flags: list[RiskFinding] = field(default_factory=list)
    contradictions: list[RiskFinding] = field(default_factory=list)
    missed_opportunities: list[RiskFinding] = field(default_factory=list)
    strengths: list[StrengthFinding] = field(default_factory=list)
    suggested_improvements: list[SuggestedImprovement] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def feedback_from_llm(payload: dict[str, Any]) -> InterviewFeedback:
    """Convert a structured LLM response into the UI's typed feedback model."""

    def clean(value: Any, fallback: str = "") -> str:
        return " ".join(str(value or fallback).split())[:1200]

    def severity(value: Any) -> Literal["low", "medium", "high"]:
        return value if value in {"low", "medium", "high"} else "medium"

    def risks(key: str, category: RiskCategory) -> list[RiskFinding]:
        findings = []
        raw_items = payload.get(key) if isinstance(payload.get(key), list) else []
        for index, item in enumerate(raw_items, start=1):
            if not isinstance(item, dict):
                continue
            title = clean(item.get("title"))
            summary = clean(item.get("summary"))
            evidence = clean(item.get("evidence"))
            if not title or not summary or not evidence:
                continue
            suggested_fix = clean(item.get("suggested_fix")) or None
            findings.append(
                RiskFinding(
                    id=f"{category}-{index}",
                    category=category,
                    title=title,
                    summary=summary,
                    evidence=evidence,
                    severity=severity(item.get("severity")),
                    suggested_fix=suggested_fix,
                )
            )
        return findings

    strengths = []
    raw_strengths = payload.get("strengths") if isinstance(payload.get("strengths"), list) else []
    for index, item in enumerate(raw_strengths, start=1):
        if not isinstance(item, dict):
            continue
        title = clean(item.get("title"))
        summary = clean(item.get("summary"))
        evidence = clean(item.get("evidence"))
        if title and summary and evidence:
            strengths.append(
                StrengthFinding(
                    id=f"strength-{index}",
                    title=title,
                    summary=summary,
                    evidence=evidence,
                )
            )

    improvements = []
    raw_improvements = (
        payload.get("suggested_improvements")
        if isinstance(payload.get("suggested_improvements"), list)
        else []
    )
    for index, item in enumerate(raw_improvements, start=1):
        if not isinstance(item, dict):
            continue
        title = clean(item.get("title"))
        action = clean(item.get("action"))
        if title and action:
            improvements.append(
                SuggestedImprovement(
                    id=f"improvement-{index}",
                    title=title,
                    action=action,
                    priority=severity(item.get("priority")),
                )
            )

    return InterviewFeedback(
        red_flags=risks("red_flags", "red_flag"),
        contradictions=risks("contradictions", "contradiction"),
        missed_opportunities=risks("missed_opportunities", "missed_opportunity"),
        strengths=strengths,
        suggested_improvements=improvements,
    )
