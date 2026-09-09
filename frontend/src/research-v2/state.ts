import type { ResearchEvent, ResearchTask } from "./types";

export interface TaskView extends ResearchTask {
  stage: string;
  history: string[];
}

export interface ResearchState {
  status: "idle" | "running" | "completed" | "partial" | "failed" | "disconnected";
  stage: string;
  tasks: TaskView[];
  report: string;
  error: string;
  logs: string[];
}

export function createResearchState(): ResearchState {
  return { status: "idle", stage: "等待开始", tasks: [], report: "", error: "", logs: [] };
}

export function applyResearchEvent(state: ResearchState, event: ResearchEvent): void {
  const log = (message: string) => { state.logs.push(message); };
  const task = "task_id" in event ? state.tasks.find((item) => item.id === event.task_id) : undefined;
  switch (event.type) {
    case "research_started":
      state.status = "running";
      state.stage = "正在规划研究任务";
      log("开始研究：" + event.topic);
      break;
    case "tasks_planned":
      state.tasks = event.tasks.map((item) => ({ ...item, stage: "待执行", history: [] }));
      state.stage = "正在检索与审核";
      log(`已规划 ${event.tasks.length} 个任务`);
      break;
    case "task_started":
    case "task_completed":
    case "task_incomplete": {
      const previous = state.tasks.find((item) => item.id === event.task.id);
      const stage = event.type === "task_started" ? "准备检索"
        : event.type === "task_completed" ? "已完成" : "未完成";
      if (previous) Object.assign(previous, event.task, { stage });
      else state.tasks.push({ ...event.task, stage, history: [] });
      log(`${event.task.title}：${stage}` + (event.type === "task_incomplete" ? `（${event.task.review_reason}）` : ""));
      break;
    }
    case "attempt_started":
      if (task) {
        task.status = "in_progress";
        task.stage = "正在搜索";
        task.attempts = event.attempt;
        task.query = event.query;
        task.history.push(`第 ${event.attempt} 轮检索：${event.query}`);
        log(`${task.title}：第 ${event.attempt} 轮检索`);
      }
      break;
    case "search_completed":
      if (task) {
        task.evidence = event.evidence;
        task.evidence_count = event.evidence_count;
        // Previous assessments belong to the previous evidence/summary snapshot.
        task.source_assessments = [];
        task.review_coverage = [];
        task.review_decision = null;
        task.review_reason = "";
        task.stage = "正在生成摘要";
      }
      break;
    case "summary_completed":
      if (task) { task.summary = event.summary; task.stage = "正在审核证据"; }
      break;
    case "review_completed":
      if (task) {
        task.review_decision = event.decision;
        task.review_reason = event.reason;
        task.source_assessments = event.source_assessments;
        task.review_coverage = event.coverage;
        task.history.push("审核：" + event.reason);
        log(`${task.title}：${event.reason}`);
      }
      break;
    case "task_retrying":
      if (task) {
        task.status = "retrying";
        task.stage = "准备补充检索";
        task.query = event.next_query;
        task.history.push(`补充检索：${event.previous_query} → ${event.next_query}`);
      }
      break;
    case "search_failed":
      if (task) {
        task.stage = "搜索失败";
        task.history.push("搜索失败：" + event.error);
        log(`${task.title}：搜索失败，${event.error}`);
      }
      break;
    case "research_failed":
      state.status = "failed";
      state.error = event.reason;
      state.stage = "研究失败";
      log(event.reason);
      break;
    case "report_started":
      state.stage = "正在生成最终报告";
      log(state.stage);
      break;
    case "report_completed":
      state.report = event.report;
      break;
    case "error":
      state.status = "failed";
      state.error = event.detail;
      state.stage = "研究失败";
      break;
    case "done":
      if (state.status !== "failed") {
        state.status = state.tasks.some((item) => item.status !== "completed") ? "partial" : "completed";
        state.stage = state.status === "partial" ? "报告已生成，部分任务未完成" : "研究完成";
      }
      log(state.stage);
      break;
  }
}
