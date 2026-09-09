# Deep Research

独立的 FastAPI + Vue 3 深度研究应用。后端负责规划、检索、摘要、证据审核、
补充检索与报告生成；前端通过 POST SSE 显示过程和结果。

## 目录

```text
deep-research/
├── backend/
│   ├── src/deep_research/
│   │   ├── main.py              FastAPI 应用入口
│   │   ├── api.py               HTTP / SSE 路由及请求校验
│   │   ├── factory.py           为每次请求组装研究流程
│   │   ├── serialization.py     任务和证据的传输格式
│   │   ├── loop.py              研究核心循环
│   │   ├── models.py            任务、来源和审核结果
│   │   ├── ports.py             流程接口
│   │   ├── helloagents_adapters.py
│   │   ├── fake_adapters.py     测试适配器
│   │   └── config.py            配置与执行限制
│   ├── tests/
│   ├── .env                    本机模型及搜索配置
│   ├── .env.example
│   ├── pyproject.toml
│   └── uv.lock
├── frontend/
│   ├── src/research-v2/         Vue 页面、事件类型、状态和请求处理
│   ├── tests/
│   ├── index.html              默认新版首页
│   ├── v2.html                 同一页面的兼容入口
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

原目标目录的 `src/`、Python 项目配置和 `.env` 已移入 `backend/`。
Python 包统一命名为 `deep_research`。已移除 `cli.py` 和
`pyproject.toml` 中的 CLI 命令注册；通过 FastAPI 启动研究。
源项目没有改动，也没有复制旧版 Agent 或旧版 Vue 页面。

## 启动

后端终端：

后端通过 `backend/.python-version` 固定使用 Python 3.13，避免旧依赖
在 Python 3.14 上缺少预编译包的问题。uv 会按此文件选择解释器。

```powershell
cd E:\code\deep-research\backend
uv sync --extra dev
uv run python -X utf8 -m uvicorn deep_research.main:app --app-dir src --reload --port 8000
```

原有 `.env` 已原样迁到 `backend/.env`。模型配置使用
`LLM_PROVIDER`、`LLM_MODEL_ID`、`LLM_API_KEY`、`LLM_BASE_URL`；
搜索配置使用 `SEARCH_API` 和相应服务密钥。
`RESEARCH_*` 控制任务数、尝试次数和并发限制。
Windows 使用 `-X utf8`，避免第三方工具输出状态符号时编码失败。

前端终端：

```powershell
cd E:\code\deep-research\frontend
npm install
npm run dev
```

打开 [研究页面](http://localhost:5174/)。
[API 文档](http://localhost:8000/docs) 可查看接口及请求格式。
前端也支持 [v2.html](http://localhost:5174/v2.html)。

前端默认连接 `http://localhost:8000`。若端口改变，在
`frontend/.env.local` 中设置 `VITE_API_BASE_URL=http://localhost:新端口`，
然后重启 Vite；生产环境也需要在构建前设置此变量。

## 接口与行为

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /healthz | 健康检查 |
| POST | /research/v2 | 完整报告及结构化任务 |
| POST | /research/v2/stream | 阶段事件与最终报告的 SSE 流 |

迁移保留原 v2 路径，前后端协议一致。两个 POST 接口都接收：

```json
{"topic":"比较 PostgreSQL 和 MySQL 的事务能力","search_api":"tavily"}
```

`search_api` 可省略，沿用后端配置。浏览器仅提交研究主题和搜索选项，
模型密钥保留在后端。每次请求创建独立的研究状态。

页面显示任务进度、验收项、来源相关性与可信度、检索审核历史和报告下载。
摘要和报告在阶段完成时整体更新。部分任务未完成会明确标记；
“停止接收”只断开前端接收，后端已发出的模型或搜索请求可能继续。

## 验证

后端测试使用模拟适配器，不调用真实模型和搜索服务：

```powershell
cd E:\code\deep-research\backend
uv run --extra dev python -X utf8 -m unittest discover -s tests -v
```

前端测试要求 Node.js 24：

```powershell
cd E:\code\deep-research\frontend
npm test
npm run build
```

无需外部服务的本地页面联调，可用以下命令代替正式后端：

```powershell
cd E:\code\deep-research\backend
uv run python -X utf8 tests/serve_research_v2_demo.py --port 8000
```

模拟接口使用真实 FastAPI 路由和测试适配器，返回 `example.test` 来源。
这只用于验证页面，不代表真实研究结果。正式后端不会自动使用模拟数据。

可选浏览器测试：启动模拟后端和 Vite 后，在 frontend 执行
`node tests/research-v2.browser.mjs`。需要可用的 Playwright；
`PLAYWRIGHT_MODULE` 可指定其 `index.mjs` 的绝对路径，
`BROWSER_EXECUTABLE` 可指定 Chromium 路径，
`FRONTEND_URL` 默认 `http://127.0.0.1:5174`。
