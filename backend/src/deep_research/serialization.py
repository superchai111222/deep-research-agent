"""Serialize domain snapshots shared by HTTP results and workflow events."""

from dataclasses import asdict

from .models import Task


def serialize_evidence(task: Task) -> list[dict[str, object]]:
    """Preserve source numbers across attempts and review assessments."""
    return [
        {"evidence_id": index, **asdict(item)}
        for index, item in enumerate(task.evidence, start=1)
    ]


def serialize_task(task: Task) -> dict[str, object]:
    """Return a detached JSON-compatible snapshot of a research task."""
    return {
        "id": task.id,
        "title": task.title,
        "goal": task.goal,
        "query": task.query,
        "required_aspects": list(task.required_aspects),
        "status": task.status.value,
        "attempts": task.attempts,
        "evidence_count": len(task.evidence),
        "evidence": serialize_evidence(task),
        "summary": task.summary,
        "review_decision": task.review_decision.value if task.review_decision else None,
        "review_reason": task.review_reason,
        "source_assessments": [
            {**asdict(item), "usable": item.usable}
            for item in task.source_assessments
        ],
        "review_coverage": [asdict(item) for item in task.review_coverage],
    }
