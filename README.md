# Deep Research 智能深度研究系统

输入一个研究主题，系统会自动拆解任务、联网检索资料、整理摘要、
审核证据，并生成带来源引用的 Markdown 报告。

基于 Python、HelloAgents、FastAPI、Vue 3 和 TypeScript 开发，
通过 SSE 向页面推送研究进度。

## 主要功能

- **任务规划**：将问题拆分为研究子任务，生成检索语句和验收项。
- **并行检索**：同时执行独立子任务，收集并按链接去重网络来源。
- **证据审核**：结合模型判断与程序校验，检查来源相关性、可信度和验收项覆盖情况。
- **补充搜索**：证据不足时调整查询继续检索，通过尝试次数和步骤上限控制执行范围。
- **进度展示**：查看任务阶段、来源内容、审核结果和补充检索历史。
- **报告生成**：根据通过审核的来源生成报告，附带引用编号与来源链接，支持下载 Markdown 文件。

## 安装与配置

准备 Git、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和
[Node.js 24](https://nodejs.org/)（含 npm）。

### 1. 下载项目

```shell
git clone https://github.com/superchai111222/deep-research-agent.git
cd deep-research-agent
```

如果已有项目文件，直接进入项目根目录即可。

### 2. 安装后端依赖

```shell
cd backend
uv python install 3.13
uv sync --locked --extra dev
```

uv 根据项目的依赖清单和锁文件自动创建 `backend/.venv/`，
无需另外创建或手动激活虚拟环境。

### 3. 配置模型和搜索服务

将 `backend/.env_example` 复制一份并命名为 `.env`，放在同一目录；
已有 `.env` 则直接编辑。填写模型和搜索配置：

```dotenv
LLM_PROVIDER=custom
LLM_MODEL_ID=your-model-name
LLM_API_KEY=your-api-key-here
LLM_BASE_URL=https://your-api-host.example/v1

SEARCH_API=duckduckgo
```

- `LLM_MODEL_ID`：模型服务商提供的模型名称。
- `LLM_API_KEY`：自己的模型服务密钥。
- `LLM_BASE_URL`：模型服务商提供的 OpenAI 兼容接口地址。
- `SEARCH_API`：搜索服务，默认 DuckDuckGo 无需密钥；使用 Tavily、SerpApi 等服务时，需要填写对应密钥。

Tavily、SerpApi 的 API 密钥可在各自官网注册申请，额度以官网说明为准。

其他配置见 `backend/.env_example`，包括本地模型地址、任务数、
尝试次数和并发限制。`.env.example` 也提供相同示例。
示例中的模型名称、地址和密钥是占位值，需要替换；真实 `.env` 不提交到 Git。

## 启动与使用

### 1. 启动后端

在 `backend/` 目录执行：

```shell
uv run --locked python -X utf8 -m uvicorn deep_research.main:app --app-dir src --reload --port 8000
```

后端启动后等待研究请求。
接口文档：[http://localhost:8000/docs](http://localhost:8000/docs)。

### 2. 启动前端

另开一个终端，从项目根目录执行：

```shell
cd frontend
npm ci
npm run dev
```

打开 [http://localhost:5174/](http://localhost:5174/)。
后续启动只需运行后端启动命令和 `npm run dev`，无需每次安装依赖。

### 3. 开始研究

1. 输入主题，例如“比较 PostgreSQL 和 MySQL 在高并发订单系统中的选型”。
2. 选择搜索引擎，或沿用后端配置。
3. 点击“开始研究”，查看任务列表和实时进度。
4. 选择任务，查看验收项、来源内容、摘要和审核历史。
5. 报告生成后，可在页面阅读或点击“下载 Markdown”。

运行时保持两个终端开启，分别按 `Ctrl+C` 可停止前后端服务。

## 使用说明

- 主题尽量明确，可以指定时间范围、比较对象和关注维度。
- 摘要和报告在对应阶段完成后整体展示，不是逐字输出。
- 达到执行上限后，部分任务可能标记为未完成；报告应结合证据缺口阅读。
- 来源审核不能保证事实绝对准确，重要结论应进一步核对原始资料。
- “停止接收”只断开页面的进度接收，后端已发出的模型或搜索请求可能继续执行。
- 页面刷新后不会恢复之前的研究进度，请及时下载报告。

如果后端地址改变，在 `frontend/.env.local` 中设置：

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

将地址改为实际后端地址后重启前端；生产构建前也需设置正确地址。
可参考 `frontend/.env.example`，前端配置中不要填写模型或搜索服务密钥。
