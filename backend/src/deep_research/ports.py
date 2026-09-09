"""Small interfaces that keep the workflow independent from concrete SDKs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .models import Evidence, ResearchState, ReviewResult, Task


class Planner(Protocol):
    """Create the initial task list for a topic."""

    def plan(self, topic: str) -> list[Task]:
        ...


class SearchProvider(Protocol):
    """Retrieve evidence for one search query."""

    def search(self, query: str) -> list[Evidence]:
        ...


class Summarizer(Protocol):
    """Turn a task and its evidence into a concise summary."""

    def summarize(self, task: Task) -> str:
        ...


class Reviewer(Protocol):
    """Assess whether the current evidence is sufficient for a task."""

    def review(self, task: Task) -> ReviewResult:
        ...


class Reporter(Protocol):
    """Create a final report from the completed research state."""

    def report(self, state: ResearchState) -> str:
        ...


EventSink = Callable[[dict[str, object]], None]
