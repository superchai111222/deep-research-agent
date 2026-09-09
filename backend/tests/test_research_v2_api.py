"""Exercise the real HTTP boundary with deterministic, network-free adapters."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deep_research import api
from deep_research.config import ResearchPolicy
from deep_research.fake_adapters import (
    FakePlanner,
    FakeReporter,
    FakeReviewer,
    FakeSearchProvider,
    FakeSummarizer,
)
from deep_research.loop import ResearchLoop
from deep_research.main import create_app
from deep_research.models import Task


def fake_loop(**overrides):
    kwargs = dict(
        planner=FakePlanner(),
        search=FakeSearchProvider(),
        summarizer=FakeSummarizer(),
        reviewer=FakeReviewer(),
        reporter=FakeReporter(),
        policy=ResearchPolicy(),
    )
    kwargs.update(overrides)
    return ResearchLoop(**kwargs)


class ResearchApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.configs = []

        def build(config):
            self.configs.append(config)
            return fake_loop()

        self.factory = patch.object(api, "build_research_loop", side_effect=build)
        self.factory.start()
        self.addCleanup(self.factory.stop)
        self.addCleanup(self.client.close)

    def stream(self):
        response = self.client.post("/research/v2/stream", json={"topic": "测试研究"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        return [
            json.loads(frame.removeprefix("data: "))
            for frame in response.text.strip().split("\n\n")
        ]

    def test_sync_result_and_search_override(self):
        response = self.client.post(
            "/research/v2", json={"topic": "  测试主题  ", "search_api": "tavily"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.configs[0].search_backend, "tavily")
        result = response.json()
        self.assertIn("测试主题", result["report_markdown"])
        task = result["tasks"][0]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["attempts"], 2)
        self.assertEqual([item["evidence_id"] for item in task["evidence"]], [1, 2, 3])
        self.assertTrue(task["source_assessments"][1]["usable"])

    def test_stream_retry_and_source_snapshots(self):
        events = self.stream()
        types = [event["type"] for event in events]
        self.assertEqual(types[0], "research_started")
        self.assertEqual(types[-3:], ["report_started", "report_completed", "done"])
        self.assertEqual(types.count("task_retrying"), 1)
        searches = [e for e in events if e["type"] == "search_completed"]
        self.assertEqual([len(e["evidence"]) for e in searches], [1, 3])
        final = next(e["task"] for e in events if e["type"] == "task_completed")
        self.assertEqual(final["review_decision"], "accept")
        self.assertTrue(final["review_reason"])
        self.assertEqual(final["review_coverage"][0]["evidence_ids"], [2, 3])

    def test_input_validation_before_factory(self):
        for topic in ("", "  \t\n", "x" * 4001):
            for path in ("/research/v2", "/research/v2/stream"):
                self.assertEqual(self.client.post(path, json={"topic": topic}).status_code, 422)
        self.assertEqual(self.client.post(
            "/research/v2", json={"topic": "topic", "search_api": "unknown"}
        ).status_code, 422)
        self.assertEqual(self.configs, [])

    def test_invalid_configuration_is_http_error(self):
        with patch.object(api, "build_research_loop", side_effect=ValueError("bad config")):
            response = self.client.post("/research/v2/stream", json={"topic": "topic"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "bad config")

    def test_fatal_failure_is_terminal_error(self):
        loop = fake_loop()
        with patch.object(loop.reporter, "report", side_effect=RuntimeError("private diagnostic")):
            with patch.object(api, "build_research_loop", side_effect=lambda _: loop):
                events = self.stream()
        self.assertEqual(events[-1]["type"], "error")
        self.assertNotIn("done", [e["type"] for e in events])
        self.assertNotIn("private diagnostic", events[-1]["detail"])

    def test_search_failure_still_returns_partial_report(self):
        loop = fake_loop()
        with patch.object(loop.search, "search", side_effect=RuntimeError("search unavailable")):
            with patch.object(api, "build_research_loop", side_effect=lambda _: loop):
                events = self.stream()
        task = next(e["task"] for e in events if e["type"] == "task_incomplete")
        self.assertIn("search unavailable", task["review_reason"])
        self.assertEqual(task["review_decision"], "stop")
        self.assertEqual(events[-1]["type"], "done")

    def test_exhausted_attempts_do_not_advertise_another_retry(self):
        with patch.object(api, "build_research_loop", side_effect=lambda _: fake_loop(
            policy=ResearchPolicy(max_attempts=1)
        )):
            events = self.stream()
        self.assertNotIn("task_retrying", [e["type"] for e in events])
        task = next(e["task"] for e in events if e["type"] == "task_incomplete")
        self.assertIn("尝试次数上限", task["review_reason"])
        self.assertEqual(task["status"], "incomplete")

    def test_parallel_tasks_respect_shared_step_budget(self):
        loop = fake_loop(policy=ResearchPolicy(max_steps=1))
        with patch.object(loop.planner, "plan", return_value=[
            Task(id=index, title=str(index), goal="goal", query="query", required_aspects=["goal"])
            for index in (1, 2, 3)
        ]):
            events = list(loop.run_stream("topic"))
        final = [e["task"] for e in events if e["type"] == "task_incomplete"]
        self.assertEqual({task["id"] for task in final}, {1, 2, 3})
        self.assertEqual(sum(task["attempts"] for task in final), 1)
        self.assertTrue(all("步骤上限" in task["review_reason"] for task in final))
        self.assertTrue(all(task["required_aspects"] == ["goal"] for task in final))

    def test_empty_plan_reports_failure_then_closes(self):
        loop = fake_loop()
        with patch.object(loop.planner, "plan", return_value=[]):
            events = list(loop.run_stream("topic"))
        self.assertEqual([e["type"] for e in events],
                         ["research_started", "research_failed", "report_completed", "done"])

    def test_health_and_cors(self):
        self.assertEqual(self.client.get("/healthz").json(), {"status": "ok"})
        response = self.client.options("/research/v2/stream", headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "*")


if __name__ == "__main__":
    unittest.main()
