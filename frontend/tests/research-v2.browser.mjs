// Optional browser smoke test. Run against the demo API and Vite described in README.md.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE
  ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : "playwright");
const browser = await chromium.launch({
  headless: true,
  ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {})
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
const base = process.env.FRONTEND_URL || "http://127.0.0.1:5174";
const frame = event => "data: " + JSON.stringify(event) + "\n\n";
const screenshot = async name => {
  if (!process.env.SCREENSHOT_DIR) return;
  await mkdir(process.env.SCREENSHOT_DIR, { recursive: true });
  await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, name), fullPage: true });
};

try {
  await page.goto(base + "/");
  await page.getByLabel("研究主题", { exact: true }).fill("中文研究：数据库选型");
  const request = page.waitForRequest(request => request.url().endsWith("/research/v2/stream"));
  await page.getByRole("button", { name: "开始研究 →", exact: true }).click();
  assert.equal((await request).postDataJSON().topic, "中文研究：数据库选型");
  await page.locator(".status-bar").getByText("研究完成", { exact: true }).waitFor();
  await page.getByRole("heading", { name: "最终报告", exact: true }).waitFor();
  assert.equal(await page.locator(".source-item").count(), 3);
  assert.equal(await page.locator(".assessment.passed").count(), 2);
  await page.getByText("检索与审核历史", { exact: true }).click();
  assert.match(await page.locator(".attempts").innerText(), /第 2 轮检索/);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载 Markdown" }).click();
  assert.equal((await download).suggestedFilename(), "研究报告.md");
  await screenshot("v2-desktop.png");
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await screenshot("v2-mobile.png");

  // A stage error must not leave stale results or a successful status.
  await page.route("**/research/v2/stream", route => route.fulfill({
    contentType: "text/event-stream",
    body: frame({ type: "research_started", topic: "错误场景" })
      + frame({ type: "error", detail: "测试服务失败" })
  }));
  await page.getByRole("button", { name: "开始研究 →", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "测试服务失败" }).waitFor();
  assert.equal(await page.getByRole("heading", { name: "最终报告", exact: true }).count(), 0);
  await page.unroute("**/research/v2/stream");

  // Hold a request to verify disconnect and immediate restart isolation.
  let heldRoute;
  let resolveHeld;
  const held = new Promise(resolve => { resolveHeld = resolve; });
  await page.route("**/research/v2/stream", route => { heldRoute = route; resolveHeld(); });
  await page.getByRole("button", { name: "开始研究 →", exact: true }).click();
  await held;
  await page.getByRole("button", { name: "停止接收", exact: true }).click();
  await page.getByText("已停止接收", { exact: true }).waitFor();
  await heldRoute.abort().catch(() => {});
  await page.unroute("**/research/v2/stream");
  await page.getByRole("button", { name: "开始研究 →", exact: true }).click();
  await page.locator(".status-bar").getByText("研究完成", { exact: true }).waitFor();
  assert.equal(await page.getByRole("alert").count(), 0);

  // Explicit task incompletion still has a report, but must be labelled partial.
  await page.route("**/research/v2/stream", route => route.fulfill({
    contentType: "text/event-stream",
    body: frame({ type: "research_started", topic: "部分完成" })
      + frame({ type: "tasks_planned", tasks: [{
        id: 1, title: "有限资料", goal: "资料核对", query: "query", required_aspects: [],
        status: "incomplete", attempts: 1, evidence_count: 0, evidence: [], summary: "",
        review_decision: "stop", review_reason: "达到上限", source_assessments: [], review_coverage: []
      }] })
      + frame({ type: "report_completed", report: "# 报告\n\n证据不足。" })
      + frame({ type: "done" })
  }));
  await page.getByRole("button", { name: "开始研究 →", exact: true }).click();
  await page.locator(".status-bar").getByText("报告已生成，部分任务未完成", { exact: true }).waitFor();
  await page.unroute("**/research/v2/stream");

  await page.goto(base + "/index.html");
  await page.getByRole("heading", { name: "今天，你想深入了解什么？", exact: true }).waitFor();
  await page.goto(base + "/v2.html");
  await page.getByRole("heading", { name: "今天，你想深入了解什么？", exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log("Browser checks passed: real SSE, retry, evidence, download, mobile, error, disconnect/restart, partial result, both page URLs.");
} finally {
  await browser.close();
}
