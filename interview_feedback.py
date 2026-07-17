"""Feedback data structures and placeholder analysis for interview results."""

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


def build_placeholder_feedback(session_data: dict[str, Any]) -> InterviewFeedback:
    """Create deterministic placeholder feedback until the real analyzer is plugged in."""

    profile = session_data.get("profile") or {}
    turns = session_data.get("turns") or []
    captured = [
        item
        for item in profile.values()
        if item.get("status") == "captured" and item.get("value")
    ]
    skipped = [item for item in profile.values() if item.get("status") == "skipped"]
    clarifications = [turn for turn in turns if turn.get("outcome") == "clarify"]

    feedback = InterviewFeedback()

    if skipped:
        item = skipped[0]
        feedback.missed_opportunities.append(
            RiskFinding(
                id="missed-skipped-detail",
                category="missed_opportunity",
                title="Some CV sections were skipped",
                summary="Skipped answers can leave the generated CV thinner than it needs to be.",
                evidence=f"{item.get('attribute', 'A section')} was skipped.",
                severity="medium",
                related_question_id=item.get("question_id"),
                suggested_fix="Revisit skipped sections and add one concrete example where possible.",
            )
        )

    if clarifications:
        turn = clarifications[0]
        feedback.red_flags.append(
            RiskFinding(
                id="red-clarity",
                category="red_flag",
                title="Some answers needed clarification",
                summary="A hiring interviewer may need clearer, more direct answers.",
                evidence=turn.get("raw_transcript") or "A clarification turn was recorded.",
                severity="low",
                related_question_id=turn.get("question_id"),
                suggested_fix="Practice answering with a short situation, action, and result.",
            )
        )

    if not captured:
        feedback.red_flags.append(
            RiskFinding(
                id="red-no-captured-answers",
                category="red_flag",
                title="No strong answer data captured yet",
                summary="The app does not yet have enough interview material to evaluate the CV.",
                evidence="No captured profile answers were found for this session.",
                severity="high",
                suggested_fix="Complete the voice questions with specific examples and outcomes.",
            )
        )
    else:
        strongest = captured[0]
        feedback.strengths.append(
            StrengthFinding(
                id="strength-specific-answer",
                title=f"{strongest.get('attribute', 'One answer')} is usable",
                summary="This answer gives the CV generator concrete material to work with.",
                evidence=str(strongest.get("value", ""))[:240],
                related_question_id=strongest.get("question_id"),
            )
        )

    feedback.contradictions.append(
        RiskFinding(
            id="contradictions-pending-analyzer",
            category="contradiction",
            title="Contradiction checks pending",
            summary="No contradiction analyzer has been plugged in yet.",
            evidence="Future analysis will compare the CV, profile answers, and interview transcript.",
            severity="low",
            suggested_fix="Connect the analyzer to populate this section with real findings.",
        )
    )

    feedback.suggested_improvements.append(
        SuggestedImprovement(
            id="improve-add-metrics",
            title="Add measurable outcomes",
            action="Where possible, include numbers, scope, tools, time saved, revenue, users, or quality improvements.",
            priority="high",
        )
    )
    feedback.suggested_improvements.append(
        SuggestedImprovement(
            id="improve-company-fit",
            title="Tie answers to the target company",
            action="When a company website is provided, connect your experience to its products, values, or role needs.",
            priority="medium",
        )
    )

    return feedback
