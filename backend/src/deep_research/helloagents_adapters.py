"""HelloAgents-backed stage implementations for the research MVP."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from typing import Any
from urllib.parse import urlparse

from hello_agents import HelloAgentsLLM
from hello_agents.tools import SearchTool

from .config import ResearchConfig, ResearchPolicy
from .models import (
    CoverageItem,
    Evidence,
    ResearchState,
    ReviewDecision,
    ReviewResult,
    SourceAssessment,
    Task,
)

logger = logging.getLogger(__name__)

PLANNER_SYSTEM = """你是一个研究任务规划器。你的工作是把用户主题拆成完成研究所必需的最少任务，
并为每个任务预先定义必须被证据覆盖的验收方面。

任务拆分规则（必须遵守）：
1. 先判断一个搜索任务是否已经能够覆盖用户问题；如果可以，只输出一个任务。
2. 只有当主题包含两个或更多彼此独立、必须分别检索的问题时，才拆成多个任务。
3. 尽量少拆分，通常输出 1-3 个任务；绝不能为了凑数量拆分。
4. 每个任务必须有独立目标和可直接执行的搜索查询。
5. 任务按研究必要性排序。
6. 当前日期仅用于帮助理解相对时间。

required_aspects 规则：
1. required_aspects 是该任务最终被判定完成时必须全部有证据支持的验收项。
2. 必须直接从用户主题和任务目标中提取，不能随意增加用户没有要求的方面。
3. 每个任务通常包含 1-5 个 required_aspects。
4. 每个 aspect 必须原子化，一个 aspect 只表达一个需要验证的问题。
5. 不得使用“其他”“综合情况”“相关信息”等模糊表述。
6. Reviewer 后续只能审核这里定义的 required_aspects，因此这里必须完整，不得遗漏任务目标中的关键要求。

输出契约：
- 只能输出一个 JSON 对象。
- 顶层只能包含 tasks。
- tasks 必须是非空数组。
- 任务数量不得超过 N。
- 每个任务只能包含：
  title: string
  goal: string
  query: string
  required_aspects: string[]
- required_aspects 必须非空。

示例：
{
  "tasks": [
    {
      "title": "数据库选型比较",
      "goal": "比较 PostgreSQL 和 MySQL 是否适合高并发订单系统",
      "query": "PostgreSQL MySQL high concurrency transaction comparison",
      "required_aspects": [
        "高并发写入和事务处理能力",
        "事务一致性能力",
        "复制与故障恢复能力"
      ]
    }
  ]
}
"""

SUMMARIZER_SYSTEM = """你是一个研究摘要器。
根据任务和来源写一段简洁、基于来源的摘要。
使用输入中的来源编号标注依据，不要生成来源清单或 URL。
不要补充来源中没有的信息，不要输出 JSON，不要输出工具调用标记。
"""

REVIEWER_SYSTEM = """你是一个证据审核器。

Planner 已经为任务预先确定 required_aspects。
required_aspects 是固定验收标准。

你不得：
- 新增 required_aspect
- 删除 required_aspect
- 合并 required_aspect
- 拆分 required_aspect
- 改写 required_aspect 的文字

你只能逐项判断已有 required_aspects 是否得到合格证据支持。

执行规则：

1. 逐一审核所有来源。每条来源必须输出一次 source_assessments。
   - relevant：内容是否直接支持任务目标或 required_aspects
   - credible：来源主体和事实依据是否可识别、可核验
   - 只有 relevant=true 且 credible=true 的来源才是合格来源

2. 必须对输入中的每一个 required_aspect 恰好输出一次 coverage。
   - coverage.aspect 必须与输入 required_aspects 中的字符串完全一致
   - 不得新增输入中不存在的 aspect
   - 不得遗漏任何 required_aspect
   - 不得重复同一个 required_aspect
   - covered=true 时，evidence_ids 必须至少包含一个合格来源编号
   - evidence_ids 只能引用输入中真实存在的来源编号

3. 只有以下条件全部满足时才能 accept：
   - 每条来源都完成质量审核
   - 每一个 required_aspect 都有对应 coverage
   - 每一个 required_aspect 都 covered=true
   - 每一个 covered aspect 都至少引用一个合格来源

4. 任一 required_aspect 缺少合格证据时必须 retry。
   next_query 必须针对尚未覆盖的 required_aspect 或缺少的可靠来源。

5. 不能仅根据来源数量 accept。

只能输出以下 JSON，不要输出 Markdown 或解释：

{
  "decision": "accept|retry|stop",
  "reason": "总体判断原因",
  "source_assessments": [
    {
      "evidence_id": 1,
      "relevant": true,
      "credible": true,
      "reason": "该来源为什么相关且可信，或为什么不可用"
    }
  ],
  "coverage": [
    {
      "aspect": "必须原样复制某一个 required_aspect",
      "covered": true,
      "evidence_ids": [1, 2],
      "reason": "这些来源如何支持该方面"
    }
  ],
  "next_query": "补充缺失方面的搜索查询，没有则为空"
}
"""

REPORTER_SYSTEM = """你是一个研究报告撰写者。
只根据输入中“通过质量验证的来源”生成简洁的 Markdown 报告。
每个结论都必须能在这些来源中找到依据，并使用类似 [T1-S2] 的来源编号标注；没有合格来源时必须明确说明证据不足。
输入不包含 URL。不要生成来源清单或猜测链接，程序会直接追加搜索结果中的真实 URL。
只输出报告正文，不要输出 JSON、解释或工具调用标记。
"""


def get_current_date() -> str:
    """Return the runtime date used as planning context."""

    return date.today().isoformat()


def _parse_source_assessments(
    payload: dict[str, Any],
    evidence_count: int,
) -> list[SourceAssessment]:
    raw_assessments = payload.get("source_assessments", [])
    if not isinstance(raw_assessments, list):
        return []

    assessments_by_id: dict[int, SourceAssessment] = {}
    for item in raw_assessments:
        if not isinstance(item, dict):
            continue

        evidence_id = item.get("evidence_id")
        if (
            not isinstance(evidence_id, int)
            or isinstance(evidence_id, bool)
            or not 1 <= evidence_id <= evidence_count
        ):
            continue

        assessments_by_id[evidence_id] = SourceAssessment(
            evidence_id=evidence_id,
            relevant=item.get("relevant") is True,
            credible=item.get("credible") is True,
            reason=_text(item.get("reason")),
        )

    return [assessments_by_id[index] for index in sorted(assessments_by_id)]


def _parse_coverage(
    payload: dict[str, Any],
    evidence_count: int,
) -> list[CoverageItem]:
    raw_coverage = payload.get("coverage", [])
    if not isinstance(raw_coverage, list):
        return []

    coverage: list[CoverageItem] = []

    for item in raw_coverage:
        if not isinstance(item, dict):
            continue

        aspect = _text(item.get("aspect"))
        if not aspect:
            continue

        covered = item.get("covered") is True
        raw_ids = item.get("evidence_ids", [])

        evidence_ids: list[int] = []
        if isinstance(raw_ids, list):
            for value in raw_ids:
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and 1 <= value <= evidence_count
                ):
                    evidence_ids.append(value)

        coverage.append(
            CoverageItem(
                aspect=aspect,
                covered=covered,
                evidence_ids=sorted(set(evidence_ids)),
                reason=_text(item.get("reason")),
            )
        )

    return coverage


def _keep_usable_coverage_sources(
    coverage: list[CoverageItem],
    usable_evidence_ids: set[int],
) -> list[CoverageItem]:
    validated: list[CoverageItem] = []
    for item in coverage:
        evidence_ids = [
            evidence_id
            for evidence_id in item.evidence_ids
            if evidence_id in usable_evidence_ids
        ]
        covered = item.covered and bool(evidence_ids)
        reason = item.reason
        if item.covered and not evidence_ids:
            reason = (
                f"{reason}；未引用通过质量验证的来源"
                if reason
                else "未引用通过质量验证的来源"
            )

        validated.append(
            CoverageItem(
                aspect=item.aspect,
                covered=covered,
                evidence_ids=evidence_ids,
                reason=reason,
            )
        )

    return validated

def _validate_required_coverage(
    coverage: list[CoverageItem],
    required_aspects: list[str],
) -> tuple[list[CoverageItem], bool]:
    """Force Reviewer coverage to match Planner-defined aspects exactly."""

    required_set = set(required_aspects)

    coverage_by_aspect: dict[str, CoverageItem] = {}
    duplicate_aspects: set[str] = set()
    unexpected_aspects: set[str] = set()

    for item in coverage:
        # Reviewer 不允许生成 Planner 未定义的 aspect。
        if item.aspect not in required_set:
            unexpected_aspects.add(item.aspect)
            continue

        if item.aspect in coverage_by_aspect:
            duplicate_aspects.add(item.aspect)
            continue

        coverage_by_aspect[item.aspect] = item

    validated: list[CoverageItem] = []

    for aspect in required_aspects:
        item = coverage_by_aspect.get(aspect)

        if item is None:
            validated.append(
                CoverageItem(
                    aspect=aspect,
                    covered=False,
                    evidence_ids=[],
                    reason="Reviewer 未返回该必需验收项",
                )
            )
            continue

        if aspect in duplicate_aspects:
            validated.append(
                CoverageItem(
                    aspect=aspect,
                    covered=False,
                    evidence_ids=[],
                    reason="Reviewer 重复返回了该必需验收项",
                )
            )
            continue

        validated.append(item)

    complete = (
        bool(required_aspects)
        and not unexpected_aspects
        and not duplicate_aspects
        and len(validated) == len(required_aspects)
        and all(
            item.covered and bool(item.evidence_ids)
            for item in validated
        )
    )

    return validated, complete

class HelloAgentsTextLLM:
    """Thin adapter that keeps HelloAgents outside the workflow code."""

    def __init__(self, config: ResearchConfig) -> None:
        kwargs: dict[str, Any] = {
            "model": config.resolved_model(),
            "provider": config.llm_provider,
            "temperature": config.llm_temperature,
            "timeout": config.llm_timeout,
        }

        if config.llm_api_key:
            kwargs["api_key"] = config.llm_api_key
        base_url = config.resolved_base_url()
        if base_url:
            kwargs["base_url"] = base_url

        self._llm = HelloAgentsLLM(**kwargs)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Perform one non-streaming model request."""

        response = self._llm.invoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
        return response.strip()


class ConfiguredSearchProvider:
    """Search adapter configured by the deep_research runtime settings."""

    def __init__(self, config: ResearchConfig) -> None:
        self.config = config
        self.policy = config.policy
        self.max_results = config.policy.max_results
        self.backend = config.search_backend
        self._tool = SearchTool(
            backend=self.backend,
            tavily_key=config.tavily_api_key,
            serpapi_key=config.serpapi_api_key,
            perplexity_key=config.perplexity_api_key,
        )

    def search(self, query: str) -> list[Evidence]:
        """Run search with bounded retries for temporary failures."""

        max_retries = self.policy.search_max_retries
        last_error: Exception | None = None

        for retry_index in range(max_retries + 1):
            try:
                return self._search_once(query)
            except Exception as exc:
                last_error = exc
                is_last_attempt = retry_index >= max_retries

                if is_last_attempt or not _is_retryable_search_error(exc):
                    raise

                delay = self.policy.search_retry_delay * (2**retry_index)
                logger.warning(
                    "Search failed; retrying query=%r retry=%d/%d "
                    "delay=%.1fs error=%s",
                    query,
                    retry_index + 1,
                    max_retries,
                    delay,
                    exc,
                )

                if delay > 0:
                    time.sleep(delay)

        raise RuntimeError("search failed without an exception") from last_error

    def _search_once(self, query: str) -> list[Evidence]:
        """Run one search request and normalize its results."""

        raw_response = self._tool.run(
            {
                "input": query,
                "backend": self.backend,
                "mode": "structured",
                "fetch_full_page": self.config.fetch_full_page,
                "max_results": self.max_results,
                "max_tokens_per_source": self.policy.max_tokens_per_source,
            }
        )

        if isinstance(raw_response, str):
            raise RuntimeError(raw_response)

        results: list[Evidence] = []
        for item in raw_response.get("results", [])[: self.max_results]:
            if not isinstance(item, dict):
                continue

            url = _text(item.get("url"))
            if not _is_http_url(url):
                continue

            content = _text(item.get("content")) or _text(item.get("raw_content"))
            if not content:
                continue
            results.append(
                Evidence(
                    title=_text(item.get("title")) or url,
                    url=url,
                    content=content,
                )
            )

        notices = raw_response.get("notices") or []
        if not results and notices:
            raise RuntimeError("；".join(str(notice) for notice in notices))

        return results


class LLMPlanner:
    """Planner that lets the model choose a small, bounded task list."""

    def __init__(
        self,
        llm: HelloAgentsTextLLM,
        policy: ResearchPolicy | None = None,
        *,
        max_tasks: int | None = None,
    ) -> None:
        if policy is not None and max_tasks is not None:
            raise ValueError("pass policy or max_tasks, not both")
        if policy is None:
            policy = ResearchPolicy(
                max_tasks=max_tasks if max_tasks is not None else 3
            )
        self.llm = llm
        self.policy = policy
        self.max_tasks = policy.max_tasks

    def plan(self, topic: str) -> list[Task]:
        raw = self.llm.complete(
            PLANNER_SYSTEM,
            f"当前日期：{get_current_date()}\n"
            f"研究主题：{topic}\n"
            f"任务数量上限 N：{self.max_tasks}\n"
            "请先尝试用一个任务覆盖主题；只有确实存在独立问题时才增加任务，"
            "并严格按照系统提示中的 JSON 契约输出。",
        )

        payload = _parse_json(raw)
        candidates = payload.get("tasks", []) if isinstance(payload, dict) else []

        tasks: list[Task] = []
        seen_queries: set[str] = set()

        for item in candidates[: self.max_tasks]:
            if not isinstance(item, dict):
                continue

            task_id = len(tasks) + 1

            title = _text(item.get("title")) or f"研究任务 {task_id}"
            goal = _text(item.get("goal")) or "收集主题的关键事实和依据"
            query = _text(item.get("query")) or topic

            required_aspects = _parse_required_aspects(
                item.get("required_aspects")
            )

            # Planner 给不出有效 required_aspects 时，不建议偷偷接受空数组。
            # 使用 goal 作为保守 fallback，至少保证 Reviewer 有固定验收项。
            if not required_aspects:
                required_aspects = [goal]

            query_key = " ".join(query.casefold().split())
            if query_key in seen_queries:
                continue

            seen_queries.add(query_key)

            tasks.append(
                Task(
                    id=task_id,
                    title=title,
                    goal=goal,
                    query=query,
                    required_aspects=required_aspects,
                )
            )

        if tasks:
            return tasks

        return [
            Task(
                id=1,
                title="主题核心信息",
                goal="收集能够直接回答用户主题的核心事实和可靠依据",
                query=topic,
                required_aspects=[
                    "能够直接回答研究主题的核心事实和可靠依据"
                ],
            )
        ]

    


class LLMSummarizer:
    """Summarizer that makes one model request per task attempt."""

    def __init__(self, llm: HelloAgentsTextLLM) -> None:
        self.llm = llm

    def summarize(self, task: Task) -> str:
        evidence = "\n".join(
            f"[{index}] {item.title}\n{item.content}"
            for index, item in enumerate(task.evidence, start=1)
        )
        return self.llm.complete(
            SUMMARIZER_SYSTEM,
            f"任务标题：{task.title}\n任务目标：{task.goal}\n"
            f"搜索查询：{task.query}\n来源：\n{evidence or '暂无来源'}",
        )


class LLMReviewer:
    """Reviewer that returns a validated, bounded decision."""

    def __init__(self, llm: HelloAgentsTextLLM) -> None:
        self.llm = llm

    def review(self, task: Task) -> ReviewResult:
        evidence = "\n".join(
            f"[{index}] {item.title} | {item.url}\n{item.content}"
            for index, item in enumerate(task.evidence, start=1)
        )

        required_aspects_text = "\n".join(
            f"- {aspect}" for aspect in task.required_aspects
        )

        raw = self.llm.complete(
            REVIEWER_SYSTEM,
            f"任务目标：{task.goal}\n"
            f"固定 required_aspects：\n"
            f"{required_aspects_text or '- 暂无验收项'}\n"
            f"任务摘要：{task.summary}\n"
            f"当前来源数量：{len(task.evidence)}\n"
            f"来源：\n{evidence or '暂无来源'}",
        )

        payload = _parse_json(raw)
        decision_text = _text(payload.get("decision")) if isinstance(payload, dict) else ""
        try:
            decision = ReviewDecision(decision_text.lower())
        except ValueError:
            # An invalid or malformed model response must never be treated as
            # approval merely because several sources happen to be present.
            decision = ReviewDecision.RETRY

        reason = (
            _text(payload.get("reason"))
            if isinstance(payload, dict)
            else "模型未返回结构化审核结果"
        ) or "未提供审核说明"
        next_query = _text(payload.get("next_query")) if isinstance(payload, dict) else ""
        source_assessments = (
            _parse_source_assessments(payload, len(task.evidence))
            if isinstance(payload, dict)
            else []
        )
        usable_evidence_ids = {
            item.evidence_id for item in source_assessments if item.usable
        }
        coverage = (
            _parse_coverage(payload, len(task.evidence))
            if isinstance(payload, dict)
            else []
        )
        coverage = _keep_usable_coverage_sources(coverage, usable_evidence_ids)

        coverage, required_coverage_complete = _validate_required_coverage(
            coverage,
            task.required_aspects,
        )
        # The model proposes the decision, but application code enforces the
        # evidence contract. Every source must be assessed, and covered aspects
        # may refer only to sources that passed both quality checks.
        expected_evidence_ids = set(range(1, len(task.evidence) + 1))
        assessed_evidence_ids = {
            item.evidence_id for item in source_assessments
        }
        source_assessment_complete = (
            bool(expected_evidence_ids)
            and assessed_evidence_ids == expected_evidence_ids
        )

        coverage_complete = required_coverage_complete

        if decision == ReviewDecision.ACCEPT and (
            not source_assessment_complete or not coverage_complete
        ):
            decision = ReviewDecision.RETRY
            failed_checks: list[str] = []
            if not source_assessment_complete:
                failed_checks.append("来源质量检查不完整")
            if not coverage_complete:
                failed_checks.append("必需验收项覆盖检查未通过")
            reason = f"{reason}；{'；'.join(failed_checks)}"

            missing_aspects = [
                item.aspect
                for item in coverage
                if not item.covered or not item.evidence_ids
            ]
            if missing_aspects:
                next_query = f"{task.query} {' '.join(missing_aspects)}"

        if decision == ReviewDecision.RETRY and not next_query:
            next_query = f"{task.query} additional official source"

        return ReviewResult(
            decision=decision,
            reason=reason,
            next_query=next_query or None,
            source_assessments=source_assessments,
            coverage=coverage,
        )


class LLMReporter:
    """Reporter that consolidates the state into Markdown."""

    def __init__(self, llm: HelloAgentsTextLLM) -> None:
        self.llm = llm

    def report(self, state: ResearchState) -> str:
        task_blocks: list[str] = []
        for task in state.tasks:
            usable_evidence_ids = {
                item.evidence_id
                for item in task.source_assessments
                if item.usable
            }
            evidence = "\n".join(
                f"[T{task.id}-S{index}] {item.title}\n{item.content}"
                for index, item in enumerate(task.evidence, start=1)
                if index in usable_evidence_ids
            )
            task_blocks.append(
                f"任务：{task.title}\n"
                f"目标：{task.goal}\n"
                f"状态：{task.status.value}\n"
                f"通过质量验证的来源：\n{evidence or '暂无合格来源'}"
            )

        report = self.llm.complete(
            REPORTER_SYSTEM,
            f"研究主题：{state.topic}\n\n" + "\n\n".join(task_blocks),
        )
        return self._append_verified_sources(report, state)

    @staticmethod
    def _append_verified_sources(report: str, state: ResearchState) -> str:
        source_lines = ["## 可核验来源"]
        seen_urls: set[str] = set()

        for task in state.tasks:
            usable_evidence_ids = {
                item.evidence_id
                for item in task.source_assessments
                if item.usable
            }
            for index, evidence in enumerate(task.evidence, start=1):
                if index not in usable_evidence_ids or evidence.url in seen_urls:
                    continue
                seen_urls.add(evidence.url)
                source_lines.append(
                    f"- [T{task.id}-S{index}] [{evidence.title}]({evidence.url})"
                )

        if not seen_urls:
            source_lines.append("- 暂无通过质量验证的来源")

        return f"{report.strip()}\n\n" + "\n".join(source_lines)


def _parse_required_aspects(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    aspects: list[str] = []
    seen: set[str] = set()

    for item in value:
        aspect = _text(item)
        if not aspect:
            continue

        key = " ".join(aspect.casefold().split())
        if key in seen:
            continue

        seen.add(key)
        aspects.append(aspect)

    return aspects[:5]

def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_retryable_search_error(exc: Exception) -> bool:
    """Return whether a search error is likely temporary."""

    error_name = type(exc).__name__.lower()
    message = str(exc).lower()

    # Credential, parameter, permission, and exhausted-credit errors will not
    # be fixed by sending the same request again.
    permanent_markers = (
        "invalid api key",
        "api key",
        "unauthorized",
        "forbidden",
        "bad request",
        "insufficient credit",
        "insufficient credits",
        "quota",
        "balance",
        "payment required",
        "usage limit exceeded",
    )
    if any(marker in message for marker in permanent_markers):
        return False

    # Tavily uses UsageLimitExceededError for both throttling and exhausted
    # usage. Only retry when the message explicitly describes throttling.
    if "usagelimitexceedederror" in error_name:
        return "rate limit" in message or "too many requests" in message

    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code in {429, 500, 502, 503, 504}:
        return True
    if status_code in {400, 401, 403, 404}:
        return False

    temporary_names = (
        "timeout",
        "timeouterror",
        "connecterror",
        "connectionerror",
        "readtimeout",
        "connecttimeout",
    )
    if any(name in error_name for name in temporary_names):
        return True

    temporary_markers = (
        "timed out",
        "timeout",
        "connection reset",
        "connection aborted",
        "temporarily unavailable",
        "service unavailable",
        "429",
        "502",
        "503",
        "504",
        "rate limit",
        "too many requests",
    )
    return any(marker in message for marker in temporary_markers)


def _parse_json(text: str) -> dict[str, Any] | list[Any]:
    """Parse plain or fenced JSON returned by a model."""

    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    candidates = [fenced.group(1).strip()] if fenced else []
    candidates.append(cleaned)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed

    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start == -1 or end <= start:
            continue
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed

    return {}
