import assert from "node:assert/strict";
import { test } from "node:test";
import { runResearchStream } from "../src/research-v2/api.ts";
import { applyResearchEvent, createResearchState } from "../src/research-v2/state.ts";

function response(text, chunkSize = 3) {
  const bytes = new TextEncoder().encode(text);
  let position = 0;
  return new Response(new ReadableStream({
    pull(controller) {
      if (position >= bytes.length) return controller.close();
      controller.enqueue(bytes.slice(position, position += chunkSize));
    }
  }), { headers: { "Content-Type": "text/event-stream" } });
}

test("SSE handles UTF-8 byte splits, CRLF, comments and trailing frame", async t => {
  const wire = ': heartbeat\r\n\r\ndata: {"type":"report_completed",\r\ndata: "report":"中文报告"}\r\n\r\ndata: {"type":"done"}';
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.match(url, /\/research\/v2\/stream$/);
    assert.equal(JSON.parse(options.body).topic, "中文");
    return response(wire, 1);
  });
  const events = [];
  await runResearchStream({ topic: "中文" }, event => events.push(event));
  assert.deepEqual(events, [{ type: "report_completed", report: "中文报告" }, { type: "done" }]);
});

test("premature EOF and missing report are failures", async t => {
  for (const wire of ['data: {"type":"research_started","topic":"x"}\n\n', 'data: {"type":"done"}\n\n']) {
    const mock = t.mock.method(globalThis, "fetch", async () => response(wire));
    await assert.rejects(runResearchStream({ topic: "x" }, () => {}), /断开|报告/);
    mock.mock.restore();
  }
});

test("server errors and callback errors propagate, reader gets released", async t => {
  let body;
  const mock = t.mock.method(globalThis, "fetch", async () => {
    const result = response('data: {"type":"error","detail":"服务失败"}\n\n');
    body = result.body;
    return result;
  });
  await assert.rejects(runResearchStream({ topic: "x" }, () => {}), /服务失败/);
  assert.equal(body.locked, false);
  mock.mock.restore();
  t.mock.method(globalThis, "fetch", async () => response('data: {"type":"report_started"}\n\n'));
  await assert.rejects(runResearchStream({ topic: "x" }, () => { throw new Error("callback failure"); }), /callback failure/);
});

test("HTTP validation and malformed data are visible errors", async t => {
  const mock = t.mock.method(globalThis, "fetch", async () => new Response(
    JSON.stringify({ detail: [{ msg: "请输入主题" }] }), { status: 422 }
  ));
  await assert.rejects(runResearchStream({ topic: "" }, () => {}), /请输入主题/);
  mock.mock.restore();
  t.mock.method(globalThis, "fetch", async () => response("data: broken-json\n\n"));
  await assert.rejects(runResearchStream({ topic: "x" }, () => {}), /格式无效/);
});

test("abort signal reaches fetch", async t => {
  const controller = new AbortController();
  controller.abort();
  t.mock.method(globalThis, "fetch", async (_, options) => {
    assert.equal(options.signal, controller.signal);
    options.signal.throwIfAborted();
  });
  await assert.rejects(runResearchStream({ topic: "x" }, () => {}, { signal: controller.signal }),
    { name: "AbortError" });
});

const task = id => ({
  id, title: "任务" + id, goal: "目标", query: "查询", required_aspects: ["定义"],
  status: "pending", attempts: 0, evidence_count: 0, evidence: [], summary: "",
  review_decision: null, review_reason: "", source_assessments: [], review_coverage: []
});

test("interleaved tasks keep summaries and retry history separate", () => {
  const state = createResearchState();
  applyResearchEvent(state, { type: "tasks_planned", tasks: [task(1), task(2)] });
  applyResearchEvent(state, { type: "attempt_started", task_id: 2, attempt: 1, query: "q2" });
  applyResearchEvent(state, { type: "summary_completed", task_id: 2, summary: "第二个摘要" });
  applyResearchEvent(state, { type: "task_retrying", task_id: 1, previous_query: "q1", next_query: "补充来源" });
  applyResearchEvent(state, { type: "attempt_started", task_id: 1, attempt: 2, query: "补充来源" });
  assert.equal(state.tasks[1].summary, "第二个摘要");
  assert.equal(state.tasks[0].summary, "");
  assert.equal(state.tasks[0].attempts, 2);
  assert.equal(state.tasks[0].status, "in_progress");
  assert.equal(state.tasks[0].history.length, 2);
});

test("partial completion and research failure are not rendered as success", () => {
  const state = createResearchState();
  applyResearchEvent(state, { type: "tasks_planned", tasks: [task(1)] });
  applyResearchEvent(state, { type: "task_incomplete", task: { ...task(1), status: "incomplete", review_reason: "达到上限" } });
  applyResearchEvent(state, { type: "report_completed", report: "有限的结论" });
  applyResearchEvent(state, { type: "done" });
  assert.equal(state.status, "partial");
  assert.equal(state.tasks[0].review_reason, "达到上限");
  const failed = createResearchState();
  applyResearchEvent(failed, { type: "research_failed", reason: "规划为空" });
  applyResearchEvent(failed, { type: "report_completed", report: "没有任务" });
  applyResearchEvent(failed, { type: "done" });
  assert.equal(failed.status, "failed");
});

test("new evidence invalidates previous review until re-assessed", () => {
  const state = createResearchState();
  applyResearchEvent(state, { type: "tasks_planned", tasks: [task(1)] });
  applyResearchEvent(state, { type: "review_completed", task_id: 1, decision: "retry", reason: "不足",
    source_assessments: [{ evidence_id: 1, usable: true }], coverage: [{ aspect: "定义", covered: true }] });
  applyResearchEvent(state, { type: "search_completed", task_id: 1, evidence_count: 2,
    evidence: [{ evidence_id: 1 }, { evidence_id: 2 }] });
  assert.deepEqual(state.tasks[0].source_assessments, []);
  assert.deepEqual(state.tasks[0].review_coverage, []);
  assert.equal(state.tasks[0].review_decision, null);
});
