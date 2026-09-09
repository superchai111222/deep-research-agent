"""Bounded research loop independent from FastAPI and external SDKs."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Lock, local

from .config import ResearchPolicy
from .models import (
    Evidence,
    ResearchResult,
    ResearchState,
    ReviewDecision,
    Task,
    TaskStatus,
)
from .ports import EventSink, Planner, Reporter, Reviewer, SearchProvider, Summarizer
from .serialization import serialize_evidence, serialize_task


class ResearchLoop:
    """Coordinate plan, search, summarize, review, retry, and report stages."""

    def __init__(
        self,
        planner: Planner,
        search: SearchProvider,
        summarizer: Summarizer,
        reviewer: Reviewer,
        reporter: Reporter,
        *,
        policy: ResearchPolicy | None = None,
        # Keep the old keyword overrides temporarily for small external scripts.
        max_attempts: int | None = None,
        max_steps: int | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        """Store adapters and per-run limits."""
        if policy is not None and (
            max_attempts is not None or max_steps is not None
        ):
            raise ValueError("pass policy or max_attempts/max_steps, not both")
        if policy is None:
            policy = ResearchPolicy(
                max_attempts=max_attempts if max_attempts is not None else 2,
                max_steps=max_steps if max_steps is not None else 10,
            )

        self.planner = planner
        self.search = search
        self.summarizer = summarizer
        self.reviewer = reviewer
        self.reporter = reporter
        self.policy = policy
        self.max_attempts = policy.max_attempts
        self.max_steps = policy.max_steps
        self.event_sink = event_sink
        self.last_result: ResearchResult | None = None
        self._step_lock = Lock()
        self._sink_local = local()

    def run(self, topic: str) -> ResearchResult:
        """Run the workflow synchronously and return its final state."""
        for _ in self.run_stream(topic):
            pass

        if self.last_result is None:  # pragma: no cover - defensive guard
            raise RuntimeError("research loop finished without a result")
        return self.last_result

    def run_stream(self, topic: str) -> Iterator[dict[str, object]]:
        """Yield workflow events while executing one bounded research run."""
        topic = topic.strip()
        if not topic:
            raise ValueError("topic must not be empty")

        state = ResearchState(topic=topic)
        yield from self._emit({"type": "research_started", "topic": topic})

        state.tasks = self.planner.plan(topic)
        if not state.tasks:
            yield from self._emit(
                {"type": "research_failed", "reason": "planner returned no tasks"}
            )
            report = "# 研究报告\n\n未生成可执行任务。"
            self.last_result = ResearchResult(report=report, state=state)
            yield from self._emit({"type": "report_completed", "report": report})
            yield from self._emit({"type": "done"})
            return

        yield from self._emit(
            {
                "type": "tasks_planned",
                "tasks": [self._task_payload(task) for task in state.tasks],
            }
        )

        if self.policy.parallel_tasks and len(state.tasks) > 1:
            yield from self._run_tasks_parallel(state)
        else:
            for task in state.tasks:
                yield from self._run_task(state, task)

        yield from self._emit({"type": "report_started"})
        report = self.reporter.report(state)
        self.last_result = ResearchResult(report=report, state=state)
        yield from self._emit(
            {"type": "report_completed", "report": report}
        )
        yield from self._emit({"type": "done"})

    def _run_tasks_parallel(
        self, state: ResearchState
    ) -> Iterator[dict[str, object]]:
        """Run independent tasks concurrently and stream events as they occur.

        Workers only put events on a queue. The caller thread forwards them to
        the sink and consumer, which keeps callbacks single-threaded and
        avoids buffering a slow task's entire event history.
        """
        worker_count = min(self.policy.max_concurrency, len(state.tasks))
        events: Queue[tuple[str, object]] = Queue()

        def worker(task: Task) -> None:
            # A sink may update UI or other non-thread-safe state. Suppress it
            # in workers; the consumer thread invokes it when forwarding each
            # event from the queue.
            self._sink_local.suppress = True
            try:
                for event in self._run_task(state, task):
                    events.put(("event", event))
            except BaseException as exc:  # propagate after all workers finish
                events.put(("error", exc))
            finally:
                self._sink_local.suppress = False
                events.put(("done", task.id))

        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="research-task",
        ) as executor:
            futures = [executor.submit(worker, task) for task in state.tasks]
            completed = 0
            errors: list[BaseException] = []
            while completed < len(state.tasks):
                kind, payload = events.get()
                if kind == "event":
                    event = payload
                    assert isinstance(event, dict)
                    if self.event_sink:
                        self.event_sink(event)
                    yield event
                elif kind == "error":
                    assert isinstance(payload, BaseException)
                    errors.append(payload)
                else:
                    completed += 1

            # Surface unexpected worker failures after every worker has
            # released the executor, while retaining normal task-level error
            # events for provider failures handled inside _run_task.
            for future in futures:
                future.result()
            if errors:
                raise errors[0]

    def _run_task(
        self, state: ResearchState, task: Task
    ) -> Iterator[dict[str, object]]:
        task.status = TaskStatus.IN_PROGRESS
        yield from self._emit(
            {"type": "task_started", "task": self._task_payload(task)}
        )

        while (
            task.attempts < self.policy.max_attempts
            and state.step < self.policy.max_steps
            and task.status != TaskStatus.COMPLETED
        ):
            if not self._claim_step(state):
                task.status = TaskStatus.INCOMPLETE
                task.review_decision = ReviewDecision.STOP
                task.review_reason = "已达到本次研究的步骤上限"
                break
            task.attempts += 1
            yield from self._emit(
                {
                    "type": "attempt_started",
                    "task_id": task.id,
                    "attempt": task.attempts,
                    "query": task.query,
                }
            )

            try:
                new_evidence = self.search.search(task.query)
            except Exception as exc:
                task.status = TaskStatus.INCOMPLETE
                task.review_decision = ReviewDecision.STOP
                task.review_reason = f"搜索失败：{exc}"
                yield from self._emit(
                    {
                        "type": "search_failed",
                        "task_id": task.id,
                        "error": str(exc),
                    }
                )
                break

            self._merge_evidence(task, new_evidence)
            yield from self._emit(
                {
                    "type": "search_completed",
                    "task_id": task.id,
                    "evidence_count": len(task.evidence),
                    "evidence": serialize_evidence(task),
                }
            )

            task.summary = self.summarizer.summarize(task)
            yield from self._emit(
                {
                    "type": "summary_completed",
                    "task_id": task.id,
                    "summary": task.summary,
                }
            )

            review = self.reviewer.review(task)
            task.review_decision = review.decision
            task.review_reason = review.reason
            task.source_assessments = review.source_assessments
            task.review_coverage = review.coverage
            yield from self._emit(
                {
                    "type": "review_completed",
                    "task_id": task.id,
                    "decision": review.decision.value,
                    "reason": review.reason,
                    "source_assessments": [
                        {
                            "evidence_id": item.evidence_id,
                            "relevant": item.relevant,
                            "credible": item.credible,
                            "usable": item.usable,
                            "reason": item.reason,
                        }
                        for item in review.source_assessments
                    ],
                    "coverage": [
                        {
                            "aspect": item.aspect,
                            "covered": item.covered,
                            "evidence_ids": item.evidence_ids,
                            "reason": item.reason,
                        }
                        for item in review.coverage
                    ],
                }
            )

            if review.decision == ReviewDecision.ACCEPT:
                task.status = TaskStatus.COMPLETED
                yield from self._emit(
                    {"type": "task_completed", "task": self._task_payload(task)}
                )
                break

            if review.decision == ReviewDecision.RETRY and review.next_query:
                if (
                    task.attempts >= self.policy.max_attempts
                    or state.step >= self.policy.max_steps
                ):
                    break
                task.status = TaskStatus.RETRYING
                previous_query = task.query
                task.query = review.next_query
                yield from self._emit(
                    {
                        "type": "task_retrying",
                        "task_id": task.id,
                        "previous_query": previous_query,
                        "next_query": task.query,
                    }
                )
                continue

            task.status = TaskStatus.INCOMPLETE
            break

        if task.status != TaskStatus.COMPLETED:
            task.status = TaskStatus.INCOMPLETE
            if task.review_decision != ReviewDecision.STOP:
                if state.step >= self.policy.max_steps:
                    limit_reason = "已达到本次研究的步骤上限"
                elif task.attempts >= self.policy.max_attempts:
                    limit_reason = "已达到任务的尝试次数上限"
                else:
                    limit_reason = "任务未满足验收条件"
                task.review_reason = "；".join(
                    part for part in (task.review_reason, limit_reason) if part
                )
                task.review_decision = ReviewDecision.STOP
            yield from self._emit(
                {"type": "task_incomplete", "task": self._task_payload(task)}
            )

    def _claim_step(self, state: ResearchState) -> bool:
        """Atomically reserve one global workflow step for a worker."""
        with self._step_lock:
            if state.step >= self.policy.max_steps:
                return False
            state.step += 1
            return True

    def _emit(self, event: dict[str, object]) -> Iterator[dict[str, object]]:
        if self.event_sink and not getattr(self._sink_local, "suppress", False):
            self.event_sink(event)
        yield event

    @staticmethod
    def _merge_evidence(task: Task, evidence: list[Evidence]) -> None:
        """Keep one record per URL when retries return overlapping sources."""
        known_urls = {item.url for item in task.evidence}
        for item in evidence:
            if item.url not in known_urls:
                task.evidence.append(item)
                known_urls.add(item.url)

    @staticmethod
    def _task_payload(task: Task) -> dict[str, object]:
        return serialize_task(task)
