"""Runtime configuration and limits for the deep_research workflow."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping

from dotenv import load_dotenv


@dataclass(frozen=True)
class ResearchPolicy:
    """Limits that keep one research run bounded and predictable."""

    max_tasks: int = 3
    max_attempts: int = 2
    max_steps: int = 10
    max_results: int = 3
    max_tokens_per_source: int = 2000

    # Independent tasks can be run concurrently because their search and LLM
    # requests are I/O-bound. Keep the limit small to avoid provider throttling.
    parallel_tasks: bool = True
    max_concurrency: int = 3

    search_max_retries: int = 2
    search_retry_delay: float = 1.0

    def __post_init__(self) -> None:
        for name in (
            "max_tasks",
            "max_attempts",
            "max_steps",
            "max_results",
            "max_tokens_per_source",
            "max_concurrency",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be at least 1")
        if self.search_max_retries < 0:
            raise ValueError("search_max_retries must be at least 0")
        if self.search_retry_delay < 0:
            raise ValueError("search_retry_delay must be at least 0")

    @classmethod
    def from_env(
        cls,
        values: Mapping[str, Any] | None = None,
    ) -> "ResearchPolicy":
        """Load research limits from ``RESEARCH_*`` environment variables."""

        source = values or {}
        return cls(
            max_tasks=_env_int("RESEARCH_MAX_TASKS", 3, source),
            max_attempts=_env_int("RESEARCH_MAX_ATTEMPTS", 2, source),
            max_steps=_env_int("RESEARCH_MAX_STEPS", 10, source),
            max_results=_env_int("RESEARCH_MAX_RESULTS", 3, source),
            max_tokens_per_source=_env_int(
                "RESEARCH_MAX_TOKENS_PER_SOURCE", 2000, source
            ),
            parallel_tasks=_env_bool("RESEARCH_PARALLEL_TASKS", True, source),
            max_concurrency=_env_int("RESEARCH_MAX_CONCURRENCY", 3, source),
            search_max_retries=_env_int(
                "RESEARCH_SEARCH_MAX_RETRIES", 2, source
            ),
            search_retry_delay=_env_float(
                "RESEARCH_SEARCH_RETRY_DELAY", 1.0, source
            ),
        )


@dataclass(frozen=True)
class ResearchConfig:
    """Runtime configuration for the independent research workflow."""

    # LLM connection settings migrated from the legacy backend configuration.
    llm_provider: str = "custom"
    llm_model_id: str | None = None
    local_llm: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_timeout: int = 60
    llm_temperature: float = 0.0
    ollama_base_url: str = "http://localhost:11434"
    lmstudio_base_url: str = "http://localhost:1234/v1"

    # Search connection settings.
    search_backend: str = "duckduckgo"
    tavily_api_key: str | None = None
    serpapi_api_key: str | None = None
    perplexity_api_key: str | None = None
    # Search snippets are sufficient for the first pass and avoid fetching
    # several complete pages per result. Set FETCH_FULL_PAGE=true when needed.
    fetch_full_page: bool = False

    policy: ResearchPolicy = field(default_factory=ResearchPolicy)

    def __post_init__(self) -> None:
        if self.llm_timeout < 1:
            raise ValueError("llm_timeout must be at least 1")
        if not self.llm_provider.strip():
            raise ValueError("llm_provider must not be empty")
        if not self.search_backend.strip():
            raise ValueError("search_backend must not be empty")

    @classmethod
    def from_env(
        cls,
        overrides: Mapping[str, Any] | None = None,
    ) -> "ResearchConfig":
        """Load the new workflow configuration from ``backend/.env``."""

        load_dotenv()
        values = dict(overrides or {})
        policy_values = values.get("policy")

        return cls(
            llm_provider=_env_text("LLM_PROVIDER", "custom", values),
            llm_model_id=_env_optional_text("LLM_MODEL_ID", values),
            local_llm=_env_optional_text("LOCAL_LLM", values),
            llm_api_key=_env_optional_text("LLM_API_KEY", values),
            llm_base_url=_env_optional_text("LLM_BASE_URL", values),
            llm_timeout=_env_int("LLM_TIMEOUT", 60, values),
            llm_temperature=_env_float("LLM_TEMPERATURE", 0.0, values),
            ollama_base_url=_env_text(
                "OLLAMA_BASE_URL", "http://localhost:11434", values
            ),
            lmstudio_base_url=_env_text(
                "LMSTUDIO_BASE_URL", "http://localhost:1234/v1", values
            ),
            search_backend=_env_text("SEARCH_API", "duckduckgo", values).lower(),
            tavily_api_key=_env_optional_text("TAVILY_API_KEY", values),
            serpapi_api_key=_env_optional_text("SERPAPI_API_KEY", values),
            perplexity_api_key=_env_optional_text("PERPLEXITY_API_KEY", values),
            fetch_full_page=_env_bool("FETCH_FULL_PAGE", False, values),
            policy=(
                policy_values
                if isinstance(policy_values, ResearchPolicy)
                else ResearchPolicy.from_env(values)
            ),
        )

    def resolved_model(self) -> str | None:
        """Resolve the configured model, including local-model fallback."""

        return self.llm_model_id or self.local_llm

    def resolved_base_url(self) -> str | None:
        """Resolve provider-specific local URLs without reading the environment."""

        if self.llm_base_url:
            return self.llm_base_url
        if self.llm_provider.lower() == "ollama":
            base = self.ollama_base_url.rstrip("/")
            return base if base.endswith("/v1") else f"{base}/v1"
        if self.llm_provider.lower() == "lmstudio":
            return self.lmstudio_base_url
        return None


def _raw_value(name: str, default: Any, values: Mapping[str, Any]) -> Any:
    if name in values:
        return values[name]
    return os.getenv(name, default)


def _env_text(name: str, default: str, values: Mapping[str, Any]) -> str:
    value = _raw_value(name, default, values)
    return str(value).strip()


def _env_optional_text(name: str, values: Mapping[str, Any]) -> str | None:
    value = _raw_value(name, None, values)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _env_int(name: str, default: int, values: Mapping[str, Any]) -> int:
    value = _raw_value(name, default, values)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _env_float(name: str, default: float, values: Mapping[str, Any]) -> float:
    value = _raw_value(name, default, values)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc


def _env_bool(name: str, default: bool, values: Mapping[str, Any]) -> bool:
    value = _raw_value(name, default, values)
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")
