"""Domain models for the incremental research workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    """Lifecycle states exposed by the workflow."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RETRYING = "retrying"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"


class ReviewDecision(str, Enum):
    """The bounded set of decisions a reviewer can make."""

    ACCEPT = "accept"
    RETRY = "retry"
    STOP = "stop"


@dataclass
class Evidence:
    """A source fragment that can support a task summary."""

    title: str
    url: str
    content: str


@dataclass
class SourceAssessment:
    """Quality assessment for one evidence item."""

    evidence_id: int
    relevant: bool
    credible: bool
    reason: str = ""

    @property
    def usable(self) -> bool:
        """Return whether this source may support a coverage claim."""
        return self.relevant and self.credible


@dataclass
class CoverageItem:
    """Coverage assessment for one aspect of a task goal."""

    aspect: str
    covered: bool
    evidence_ids: list[int] = field(default_factory=list)
    reason: str = ""


@dataclass
class Task:
    """One bounded unit of research."""

    id: int
    title: str
    goal: str
    query: str
    required_aspects: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    evidence: list[Evidence] = field(default_factory=list)
    summary: str = ""
    review_decision: ReviewDecision | None = None
    review_reason: str = ""
    review_coverage: list[CoverageItem] = field(default_factory=list)
    source_assessments: list[SourceAssessment] = field(default_factory=list)


@dataclass
class ReviewResult:
    """Result returned by a reviewer after inspecting one task."""

    decision: ReviewDecision
    reason: str
    next_query: str | None = None
    coverage: list[CoverageItem] = field(default_factory=list)
    source_assessments: list[SourceAssessment] = field(default_factory=list)


@dataclass
class ResearchState:
    """Mutable state shared by all stages of one research run."""

    topic: str
    tasks: list[Task] = field(default_factory=list)
    step: int = 0


@dataclass
class ResearchResult:
    """Final result returned by the workflow."""

    report: str
    state: ResearchState
