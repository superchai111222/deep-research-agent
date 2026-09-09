"""Deterministic adapters for testing the workflow without network or an LLM."""

from __future__ import annotations

from .models import (
    CoverageItem,
    Evidence,
    ResearchState,
    ReviewDecision,
    ReviewResult,
    SourceAssessment,
    Task,
)


class FakePlanner:
    """Plan one task so the first vertical slice stays intentionally small."""

    def plan(self, topic: str) -> list[Task]:
        return [
            Task(
                id=1,
                title="背景梳理",
                goal="找到主题的定义、背景和官方依据",
                query=f"{topic} official definition",
            )
        ]


class FakeSearchProvider:
    """Return weak evidence first and stronger evidence for a refined query."""

    def search(self, query: str) -> list[Evidence]:
        if "additional source" in query:
            return [
                Evidence(
                    title="Official documentation",
                    url="https://example.test/official",
                    content="The official documentation defines the subject and its intended use.",
                ),
                Evidence(
                    title="Project source repository",
                    url="https://example.test/repository",
                    content="The source repository demonstrates the implementation described by the documentation.",
                ),
            ]

        return [
            Evidence(
                title="Initial search result",
                url="https://example.test/initial",
                content="An initial source gives a short background description.",
            )
        ]


class FakeSummarizer:
    """Produce a deterministic summary from the evidence currently attached to a task."""

    def summarize(self, task: Task) -> str:
        evidence_titles = ", ".join(item.title for item in task.evidence)
        return (
            f"{task.title}：围绕“{task.goal}”整理了 "
            f"{len(task.evidence)} 条来源（{evidence_titles}）。"
        )


class FakeReviewer:
    """Return deterministic source-quality and coverage assessments."""

    def review(self, task: Task) -> ReviewResult:
        if len(task.evidence) >= 2 and task.summary:
            return ReviewResult(
                decision=ReviewDecision.ACCEPT,
                reason="任务目标已被通过质量验证的来源覆盖。",
                source_assessments=[
                    SourceAssessment(
                        evidence_id=index,
                        relevant=True,
                        credible=index > 1,
                        reason=(
                            "测试官方来源可用于支持任务目标。"
                            if index > 1
                            else "初始来源过于简略，不作为最终证据。"
                        ),
                    )
                    for index, _ in enumerate(task.evidence, start=1)
                ],
                coverage=[
                    CoverageItem(
                        aspect="定义和背景",
                        covered=True,
                        evidence_ids=list(range(2, len(task.evidence) + 1)),
                        reason="测试官方来源提供了定义和背景信息。",
                    )
                ],
            )

        return ReviewResult(
            decision=ReviewDecision.RETRY,
            reason="当前只有少量证据，需要补充来源。",
            next_query=f"{task.query} additional source",
            source_assessments=[
                SourceAssessment(
                    evidence_id=1,
                    relevant=True,
                    credible=False,
                    reason="初始来源过于简略，不作为最终证据。",
                )
            ],
            coverage=[
                CoverageItem(
                    aspect="定义和背景",
                    covered=False,
                    reason="当前来源不足以覆盖任务目标。",
                )
            ],
        )


class FakeReporter:
    """Render the state as a small Markdown report."""

    def report(self, state: ResearchState) -> str:
        lines = [f"# 研究报告：{state.topic}", ""]
        for task in state.tasks:
            usable_evidence_ids = {
                item.evidence_id
                for item in task.source_assessments
                if item.usable
            }
            lines.extend(
                [
                    f"## {task.title}",
                    f"- 状态：{task.status.value}",
                    f"- 尝试次数：{task.attempts}",
                    f"- 摘要：{task.summary or '暂无可用信息'}",
                    "- 来源：",
                ]
            )
            lines.extend(
                f"  - [{item.title}]({item.url})"
                for index, item in enumerate(task.evidence, start=1)
                if index in usable_evidence_ids
            )
            if task.review_reason:
                lines.append(f"- 审核说明：{task.review_reason}")
            lines.append("")
        return "\n".join(lines).strip()
