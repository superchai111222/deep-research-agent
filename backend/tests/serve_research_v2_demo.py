"""Serve the real v2 HTTP routes with fake adapters for local UI verification.

Run from backend: python -X utf8 tests/serve_research_v2_demo.py --port 8000
This test entrypoint never calls an external search provider or LLM.
"""

import argparse
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deep_research import api
from deep_research.config import ResearchConfig
from deep_research.fake_adapters import (
    FakePlanner,
    FakeReporter,
    FakeReviewer,
    FakeSearchProvider,
    FakeSummarizer,
)
from deep_research.loop import ResearchLoop
from deep_research.main import create_app


def build_demo_loop(config: ResearchConfig) -> ResearchLoop:
    return ResearchLoop(
        planner=FakePlanner(), search=FakeSearchProvider(),
        summarizer=FakeSummarizer(), reviewer=FakeReviewer(),
        reporter=FakeReporter(), policy=config.policy,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    api.build_research_loop = build_demo_loop
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)
