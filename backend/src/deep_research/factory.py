"""Assemble a fresh workflow for each HTTP request."""

from .config import ResearchConfig
from .loop import ResearchLoop


def build_research_loop(config: ResearchConfig) -> ResearchLoop:
    """Construct the production adapters without sharing mutable run state."""
    from .helloagents_adapters import (
        ConfiguredSearchProvider,
        HelloAgentsTextLLM,
        LLMPlanner,
        LLMReporter,
        LLMReviewer,
        LLMSummarizer,
    )

    llm = HelloAgentsTextLLM(config)
    return ResearchLoop(
        planner=LLMPlanner(llm, config.policy),
        search=ConfiguredSearchProvider(config),
        summarizer=LLMSummarizer(llm),
        reviewer=LLMReviewer(llm),
        reporter=LLMReporter(llm),
        policy=config.policy,
    )
