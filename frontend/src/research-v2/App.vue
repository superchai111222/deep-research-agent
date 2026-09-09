<template>
  <main class="app-shell">
    <div class="aurora" aria-hidden="true"></div>
    <div class="layout">
      <header class="app-header">
        <div class="brand"><span class="logo" aria-hidden="true">◎</span><div><strong>深度研究助手 <span class="version">V2</span></strong><p>从问题出发，让每个结论都有据可查。</p></div></div>
      </header>

      <section class="panel input-panel">
        <div class="section-heading"><span class="eyebrow">开始探索</span><h1>今天，你想深入了解什么？</h1><p class="muted">自动拆解任务、检索资料、审核证据，并汇总为研究报告。</p></div>
        <form @submit.prevent="submit">
          <label class="field"><span>研究主题</span><textarea v-model="form.topic" :disabled="loading" maxlength="4000" rows="3" required placeholder="例如：比较 PostgreSQL 和 MySQL 在高并发订单系统中的选型"></textarea></label>
          <div class="form-actions">
            <label class="field search-field"><span>搜索引擎</span><select v-model="form.searchApi" :disabled="loading"><option value="">沿用后端配置</option><option v-for="option in searchOptions" :key="option" :value="option">{{ option }}</option></select></label>
            <div class="buttons">
              <button v-if="loading" type="button" class="secondary-btn" @click="disconnect">停止接收</button>
              <button class="submit" type="submit" :disabled="loading"><span v-if="loading" class="spinner" aria-hidden="true"></span>{{ loading ? '研究进行中…' : '开始研究 →' }}</button>
            </div>
          </div>
        </form>
        <p v-if="state.error" class="error-chip" role="alert">{{ state.error }}</p>
        <p v-if="state.status === 'disconnected'" class="notice" role="status">已停止接收进度。后端已发出的搜索或模型请求可能仍在执行，当前内容尚未确认完整。</p>
      </section>

      <section v-if="state.status !== 'idle'" class="panel result-panel" aria-label="研究结果">
        <header class="status-bar">
          <div role="status" aria-live="polite"><span class="status-dot" :class="state.status"></span><strong>{{ state.stage }}</strong><p class="muted">{{ finishedTasks }} / {{ state.tasks.length }} 个任务已结束 · {{ completedTasks }} 个通过审核</p></div>
          <span v-if="state.tasks.length" class="task-label">{{ evidenceCount }} 条累计来源</span>
        </header>
        <progress v-if="state.tasks.length" :value="finishedTasks" :max="state.tasks.length" aria-label="已结束的任务"></progress>
        <details class="timeline"><summary>流程记录 · {{ state.logs.length }} 条</summary><ol><li v-for="(entry, index) in state.logs" :key="index">{{ entry }}</li></ol></details>

        <div v-if="state.tasks.length" class="tasks-section">
          <aside class="tasks-list" aria-label="任务清单">
            <h2>任务清单</h2>
            <button v-for="task in state.tasks" :key="task.id" type="button" class="task-button" :class="{ active: currentTask?.id === task.id }" :aria-pressed="currentTask?.id === task.id" @click="activeTaskId = task.id">
              <span class="task-number">任务 {{ String(task.id).padStart(2, '0') }}</span><strong>{{ task.title }}</strong>
              <span class="task-status" :class="task.status">{{ task.stage }}</span>
              <small>检索 {{ task.attempts }} 轮 · 来源 {{ task.evidence_count }} 条</small>
            </button>
          </aside>

          <article v-if="currentTask" class="task-detail">
            <header><span class="eyebrow">任务详情</span><h2>{{ currentTask.title }}</h2><p class="muted">{{ currentTask.goal }}</p><p class="query"><strong>当前查询</strong> {{ currentTask.query }}</p></header>
            <section class="detail-block">
              <h3>验收项与覆盖情况</h3>
              <ul v-if="coverageItems.length" class="coverage-list"><li v-for="item in coverageItems" :key="item.aspect"><span class="check" :class="{ passed: item.covered }">{{ item.covered ? '✓' : '○' }}</span><div><strong>{{ item.aspect }}</strong><p>{{ item.reason || '等待证据审核' }}<span v-if="item.evidence_ids.length"> · 来源 {{ item.evidence_ids.map(id => 'S' + id).join('、') }}</span></p></div></li></ul>
              <p v-else class="muted">等待任务验收项。</p>
              <p v-if="currentTask.review_reason" class="review-note"><strong>{{ decisionLabel }}</strong> · {{ currentTask.review_reason }}</p>
            </section>

            <section class="detail-block">
              <h3>证据来源 <span class="count">{{ currentTask.evidence.length }}</span></h3>
              <p v-if="!currentTask.evidence.length" class="muted">搜索完成后，来源与内容会显示在这里。</p>
              <div v-for="source in currentTask.evidence" :key="source.evidence_id" class="source-item">
                <div class="source-heading"><a v-if="safeUrl(source.url)" :href="safeUrl(source.url)" target="_blank" rel="noopener noreferrer">[S{{ source.evidence_id }}] {{ source.title }}</a><span v-else>[S{{ source.evidence_id }}] {{ source.title }}</span><span class="assessment" :class="{ passed: assessment(source.evidence_id)?.usable }">{{ !assessment(source.evidence_id) ? '待审核' : assessment(source.evidence_id)?.usable ? '审核通过' : '未通过审核' }}</span></div>
                <p v-if="assessment(source.evidence_id)" class="muted">相关性：{{ assessment(source.evidence_id)?.relevant ? '通过' : '未通过' }} · 可信度：{{ assessment(source.evidence_id)?.credible ? '通过' : '未通过' }} · {{ assessment(source.evidence_id)?.reason }}</p>
                <details><summary>查看来源内容</summary><pre class="block-pre">{{ source.content }}</pre></details>
              </div>
            </section>

            <section class="detail-block"><h3>任务摘要</h3><pre v-if="currentTask.summary" class="block-pre">{{ currentTask.summary }}</pre><p v-else class="muted">等待摘要生成。每轮摘要完成后更新。</p></section>
            <details v-if="currentTask.history.length" class="attempts"><summary>检索与审核历史</summary><ol><li v-for="(entry, index) in currentTask.history" :key="index">{{ entry }}</li></ol></details>
          </article>
        </div>

        <section v-if="state.report" class="report-block">
          <div class="report-heading"><div><span class="eyebrow">研究成果</span><h2>最终报告</h2></div><button type="button" class="secondary-btn" @click="downloadReport">下载 Markdown</button></div>
          <pre class="block-pre">{{ state.report }}</pre>
        </section>
      </section>
      <footer>规划 · 检索 · 摘要 · 审核 · 报告</footer>
    </div>
  </main>
</template>

<script lang="ts" setup>
import { computed, onBeforeUnmount, reactive, ref } from "vue";
import { runResearchStream } from "./api";
import { applyResearchEvent, createResearchState } from "./state";

const form = reactive({ topic: "", searchApi: "" });
const state = reactive(createResearchState());
const loading = ref(false);
const activeTaskId = ref<number | null>(null);
let currentController: AbortController | null = null;
const searchOptions = ["advanced", "duckduckgo", "serpapi", "tavily", "perplexity", "searxng"];
const currentTask = computed(() => state.tasks.find(task => task.id === activeTaskId.value) ?? state.tasks[0]);
const completedTasks = computed(() => state.tasks.filter(task => task.status === "completed").length);
const finishedTasks = computed(() => state.tasks.filter(task => task.status === "completed" || task.status === "incomplete").length);
const evidenceCount = computed(() => state.tasks.reduce((total, task) => total + task.evidence_count, 0));
const coverageItems = computed(() => {
  const task = currentTask.value;
  if (!task) return [];
  return task.required_aspects.length
    ? task.required_aspects.map(aspect => task.review_coverage.find(item => item.aspect === aspect) ?? { aspect, covered: false, evidence_ids: [], reason: "" })
    : task.review_coverage;
});
const decisionLabel = computed(() => {
  const decision = currentTask.value?.review_decision;
  return decision === "accept" ? "审核通过" : decision === "retry" ? "需要补充证据" : "已停止本任务";
});

function assessment(id: number) {
  return currentTask.value?.source_assessments.find(item => item.evidence_id === id);
}

function safeUrl(value: string): string | undefined {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : undefined;
  } catch { return undefined; }
}

async function submit() {
  if (loading.value) return;
  if (!form.topic.trim()) { state.error = "请输入研究主题"; return; }
  Object.assign(state, createResearchState());
  activeTaskId.value = null;
  state.status = "running";
  state.stage = "正在连接研究服务";
  loading.value = true;
  const controller = new AbortController();
  currentController = controller;
  try {
    await runResearchStream(
      { topic: form.topic.trim(), search_api: form.searchApi || undefined },
      event => { if (currentController === controller && !controller.signal.aborted) applyResearchEvent(state, event); },
      { signal: controller.signal }
    );
  } catch (error) {
    if (currentController !== controller || controller.signal.aborted) return;
    state.status = "failed";
    state.stage = "研究未正常完成";
    state.error = error instanceof Error ? error.message : "研究请求失败";
  } finally {
    if (currentController === controller) {
      currentController = null;
      loading.value = false;
    }
  }
}

function disconnect() {
  currentController?.abort();
  currentController = null;
  loading.value = false;
  state.status = "disconnected";
  state.stage = "已停止接收";
}

function downloadReport() {
  const url = URL.createObjectURL(new Blob([state.report], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "研究报告.md";
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

onBeforeUnmount(() => { currentController?.abort(); currentController = null; });
</script>

<style scoped>
.app-shell { position: relative; min-height: 100vh; padding: 32px 24px; background: radial-gradient(circle at 20% 10%, #f8fafc, #dbeafe 90%); color: #1f2937; }
.aurora { position: absolute; inset: 0; pointer-events: none; background: radial-gradient(ellipse at 85% 30%, #e8e1ff88, transparent 55%); }
.layout { position: relative; max-width: 1200px; margin: 0 auto; }
.app-header, .brand, .form-actions, .buttons, .status-bar, .source-heading, .report-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.app-header { margin: 4px 0 32px; }
.brand { justify-content: flex-start; }
.brand strong { font-size: 19px; }
.brand p { margin: 4px 0 0; font-size: 13px; color: #64748b; }
.logo { display: grid; place-items: center; width: 46px; height: 46px; border-radius: 14px; color: white; background: linear-gradient(135deg, #3b82f6, #6366f1); font-size: 32px; }
.version, .task-label, .count { border-radius: 20px; background: #eaf1ff; padding: 4px 10px; font-size: 12px; color: #315cc4; }
.version { vertical-align: middle; margin-left: 6px; }
.panel { border: 1px solid #ffffff; background: #ffffffeb; border-radius: 24px; box-shadow: 0 16px 50px #334d8110; margin-bottom: 24px; }
.input-panel { padding: 32px; }
.eyebrow { color: #5272b5; font-size: 12px; letter-spacing: .12em; }
h1 { font-size: clamp(24px, 4vw, 32px); line-height: 1.4; margin: 10px 0; }
h2 { font-size: 20px; margin: 8px 0 12px; }
h3 { font-size: 15px; margin: 0 0 16px; }
.muted { color: #64748b; font-size: 14px; }
.field { display: flex; flex-direction: column; gap: 8px; font-size: 13px; color: #475569; }
form { margin-top: 24px; }
textarea, select { width: 100%; font: inherit; font-size: 15px; border: 1px solid #d8e1ef; border-radius: 12px; background: #f8fafc; color: #1f2937; padding: 14px; }
textarea { resize: vertical; min-height: 110px; }
textarea:focus, select:focus { outline: 2px solid #8db6ff; outline-offset: 2px; }
.form-actions { margin-top: 18px; align-items: flex-end; flex-wrap: wrap; }
.search-field { width: 240px; }
button, a { -webkit-tap-highlight-color: transparent; }
button { font: inherit; cursor: pointer; }
button:disabled { opacity: .65; cursor: wait; }
button:focus-visible, a:focus-visible, summary:focus-visible { outline: 2px solid #2563eb; outline-offset: 3px; }
.submit, .secondary-btn { display: inline-flex; align-items: center; justify-content: center; gap: 10px; border-radius: 12px; padding: 12px 20px; font-size: 14px; text-decoration: none; }
.submit { border: none; color: white; background: linear-gradient(135deg, #2563eb, #6366f1); box-shadow: 0 6px 16px #2563eb28; min-width: 152px; }
.secondary-btn { border: 1px solid #dce4f1; background: #ffffffc9; color: #475569; }
.secondary-btn:hover { background: #eef4ff; }
.result-panel { padding: 28px; }
.status-bar p { margin: 6px 0 0 18px; }
.status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #94a3b8; margin-right: 10px; }
.status-dot.running { background: #3b82f6; }
.status-dot.completed { background: #10b981; }
.status-dot.partial { background: #d97706; }
.status-dot.failed { background: #dc2626; }
progress { width: 100%; height: 5px; accent-color: #5279ec; margin: 20px 0 8px; }
.timeline { margin: 16px 0 24px; padding: 14px 18px; border-radius: 12px; background: #f6f8fc; font-size: 13px; color: #64748b; }
summary { cursor: pointer; }
ol { padding-left: 22px; line-height: 1.9; overflow-wrap: anywhere; }
.timeline ol { max-height: 230px; overflow-y: auto; }
.tasks-section { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 28px; border-top: 1px solid #e9eef5; padding-top: 24px; }
.tasks-list h2 { font-size: 14px; color: #64748b; margin-bottom: 16px; }
.task-button { width: 100%; padding: 16px; display: flex; flex-direction: column; align-items: flex-start; text-align: left; gap: 9px; border: 1px solid #e3e9f1; border-radius: 14px; background: white; color: #334155; margin-bottom: 12px; overflow-wrap: anywhere; }
.task-button.active { border-color: #92b2f6; background: #f1f6ff; box-shadow: 0 3px 10px #3b82f610; }
.task-number, .task-button small { color: #64748b; font-size: 12px; }
.task-status, .assessment { display: inline-block; border-radius: 6px; background: #eef2f7; color: #526176; padding: 3px 8px; font-size: 12px; }
.task-status.in_progress { background: #e0edff; color: #245ac0; }
.task-status.retrying, .task-status.incomplete { background: #fff3dc; color: #996218; }
.task-status.completed, .assessment.passed { background: #e1f5eb; color: #227452; }
.task-detail { min-width: 0; }
.query { overflow-wrap: anywhere; background: #f8fafc; border-radius: 8px; padding: 12px; font-size: 13px; color: #64748b; }
.query strong { color: #334155; margin-right: 8px; }
.detail-block { margin-top: 26px; }
.coverage-list { list-style: none; padding: 0; font-size: 14px; }
.coverage-list li { display: flex; align-items: flex-start; gap: 12px; margin: 14px 0; }
.coverage-list p { font-size: 13px; margin: 4px 0; color: #64748b; }
.check { color: #94a3b8; }
.check.passed { color: #059669; }
.review-note, .notice { border-left: 3px solid #e5b24f; background: #fff9ec; padding: 12px 16px; font-size: 13px; color: #80621f; border-radius: 4px; }
.source-item { border: 1px solid #e4eaf2; border-radius: 12px; padding: 14px 16px; margin-bottom: 10px; }
.source-heading { align-items: flex-start; flex-wrap: wrap; gap: 8px; }
.source-heading a { color: #3365bf; text-decoration: none; font-size: 14px; overflow-wrap: anywhere; flex: 1; }
.source-heading a:hover { text-decoration: underline; }
.assessment { flex-shrink: 0; }
.source-item details { font-size: 12px; color: #64748b; }
.block-pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.9; font-size: 14px; color: #334155; }
.source-item .block-pre { max-height: 300px; overflow-y: auto; }
.attempts { font-size: 13px; color: #64748b; margin-top: 24px; }
.report-block { border-top: 1px solid #e5ebf3; margin-top: 28px; padding-top: 28px; }
.report-heading { align-items: flex-start; flex-wrap: wrap; }
.report-block > pre { padding: 20px; border-radius: 12px; background: #f8fafc; }
.error-chip { padding: 12px 16px; border-radius: 10px; color: #b42318; background: #fff0ed; overflow-wrap: anywhere; }
footer { text-align: center; color: #71829e; padding: 10px 0 24px; font-size: 12px; letter-spacing: .12em; }
.spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid #ffffff66; border-top-color: white; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 760px) {
  .app-shell { padding: 20px 12px; }
  .app-header { align-items: flex-start; gap: 8px; }
  .brand p { max-width: 180px; }
  .app-header .secondary-btn { padding: 8px 12px; white-space: nowrap; }
  .input-panel, .result-panel { padding: 20px; border-radius: 18px; }
  .tasks-section { grid-template-columns: minmax(0, 1fr); gap: 16px; }
  .tasks-list { display: flex; overflow-x: auto; gap: 10px; align-items: stretch; padding: 3px; }
  .tasks-list h2 { display: none; }
  .task-button { flex: 0 0 200px; margin-bottom: 0; }
  .status-bar { align-items: flex-start; flex-wrap: wrap; }
  .search-field, .buttons { width: 100%; }
  .buttons > button { flex: 1; }
}
@media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
</style>
