# LLM Council

![llmcouncil](header.jpg)

The idea of this repo is that instead of asking a question to your favorite LLM provider (e.g. OpenAI GPT 5.1, Google Gemini 3.0 Pro, Anthropic Claude Sonnet 4.5, xAI Grok 4, eg.c), you can group them into your "LLM Council". This repo is a simple, local web app that essentially looks like ChatGPT except it uses OpenRouter to send your query to multiple LLMs, it then asks them to review and rank each other's work, and finally a Chairman LLM produces the final response.

In a bit more detail, here is what happens when you submit a query:

1. **Stage 1: First opinions**. The user query is given to all LLMs individually, and the responses are collected. The individual responses are shown in a "tab view", so that the user can inspect them all one by one.
2. **Stage 2: Review**. Each individual LLM is given the responses of the other LLMs. Under the hood, the LLM identities are anonymized so that the LLM can't play favorites when judging their outputs. The LLM is asked to rank them in accuracy and insight.
3. **Stage 3: Final response**. The designated Chairman of the LLM Council takes all of the model's responses and compiles them into a single final answer that is presented to the user.

## Vibe Code Alert

This project was 99% vibe coded as a fun Saturday hack because I wanted to explore and evaluate a number of LLMs side by side in the process of [reading books together with LLMs](https://x.com/karpathy/status/1990577951671509438). It's nice and useful to see multiple responses side by side, and also the cross-opinions of all LLMs on each other's outputs. I'm not going to support it in any way, it's provided here as is for other people's inspiration and I don't intend to improve it. Code is ephemeral now and libraries are over, ask your LLM to change it in whatever way you like.

## Setup

### 1. Install Dependencies

The project uses [uv](https://docs.astral.sh/uv/) for project management.

**Backend:**
```bash
uv sync
```

**Frontend:**
```bash
cd frontend
npm install
cd ..
```

### 2. 配置 API Key

在项目根目录创建 `.env` 文件：

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

你可以在 [openrouter.ai](https://openrouter.ai/) 获取 API Key，并确保账户有足够额度（或开启自动充值）。

提示：可以先把 `.env.example` 复制成 `.env` 再修改。

### 2b. 使用其他 Provider（DashScope / ApiYi / Ollama）

本项目支持多种 Provider，并通过统一的模型标识格式来配置：

`<provider>:<model>`

支持的 provider：
- `openrouter`（默认）
- `dashscope`（直连 DashScope 的 OpenAI 兼容接口，用于 Qwen 等）
- `apiyi`（直连 ApiYi 的 OpenAI 兼容接口：https://docs.apiyi.com/getting-started）
- `ollama`（本地 Ollama）

在 `.env` 中配置对应的环境变量（见 `.env.example`），然后按需设置 `COUNCIL_MODELS`、`CHAIRMAN_MODEL`、`TITLE_MODEL`。

示例：
```bash
COUNCIL_MODELS=openrouter:openai/gpt-5.1,apiyi:gpt-4o-mini,dashscope:qwen-plus,ollama:llama3.1
CHAIRMAN_MODEL=dashscope:qwen-plus
```

### 3. 配置模型（可选）

Edit `backend/config.py` to customize the council:

```python
COUNCIL_MODELS = [
    "openrouter:openai/gpt-5.1",
    "openrouter:google/gemini-3-pro-preview",
    "openrouter:anthropic/claude-sonnet-4.5",
    "openrouter:x-ai/grok-4",
]

CHAIRMAN_MODEL = "openrouter:google/gemini-3-pro-preview"
```

## Running the Application

**方式 1：使用启动脚本**
```bash
./start.sh
```

**方式 1b（Windows / PowerShell）：**
```powershell
.\start.ps1
```

**方式 2：手动启动**

Terminal 1 (Backend):
```bash
uv run python -m backend.main
```

Terminal 2 (Frontend):
```bash
cd frontend
npm run dev
```

然后在浏览器打开启动脚本输出的 Frontend 地址（默认是 http://localhost:5173；若端口被占用会自动递增）。

也可以访问启动脚本输出的 Backend 地址下的 `/api/status` 查看后端 provider/key 配置状态（不会返回密钥本身）。

常用环境变量：
- `BACKEND_PORT`：指定后端端口（默认 8001；端口冲突时脚本会选择可用端口）
- `FRONTEND_PORT`：指定前端端口（默认 5173；端口冲突时脚本会选择可用端口）
- `VITE_API_BASE`：指定前端连接的后端地址（例如 `http://localhost:8002`）

## Tech Stack

- **Backend:** FastAPI (Python 3.10+), async httpx, OpenRouter API
- **Frontend:** React + Vite, react-markdown for rendering
- **Storage:** JSON files in `data/conversations/`
- **Package Management:** uv for Python, npm for JavaScript

## Notes

- 前端使用 Vite；如果看到 Node.js 版本警告，请升级到 Vite 支持的 Node 版本。

## 管理功能（已增强）

### 会话管理

- 删除会话：前端侧边栏每条会话右侧 `Delete`（后端：`DELETE /api/conversations/{id}`）
- 导出会话：前端侧边栏/聊天页 `导出`（后端：`GET /api/conversations/{id}/export`，包含会话内容 + Trace + 当前 Agent 配置）

### Agent 管理（人设/权重/年资）

- 前端：侧边栏 `管理 Agents` 可新增/编辑/删除 Agent，设置 `model_spec`、人设(system prompt)、重要性权重、年资、启用/停用
- 后端接口：
  - `GET /api/agents`
  - `POST /api/agents`
  - `PUT /api/agents/{agent_id}`
  - `DELETE /api/agents/{agent_id}`
- 落盘位置：`data/agents.json`

### 可追溯 Trace（讨论过程）

- 后端会把每次 LLM 调用（请求 messages + 响应 + 耗时 + 错误）按 JSONL 落盘：`data/traces/<conversation_id>.jsonl`
- 前端：聊天页可 `显示过程`，并可点击某条记录展开查看 request/response 详情
- 查询接口：`GET /api/conversations/{id}/trace`

### 输出语言 / 外部信息设置

- 默认：输出中文；并在 Stage1 注入当前日期时间与网页检索摘要（可在设置中关闭）
- 设置接口：
  - `GET /api/settings`
  - `POST /api/settings`（示例：`{"output_language":"zh","enable_web_search":true,"enable_date_context":true}`）

### 每个会话选择参与专家

- 前端聊天页点击 `选择专家`，为当前会话选择参与讨论的专家子集
- 后端接口：`PUT /api/conversations/{id}/agents`（传入 `["agent_id_1","agent_id_2"]`；传空数组表示恢复默认=全部启用专家）

## 知识库 / 知识图谱（实验性）

### 稳定知识库（本地 SQLite）

- 存储：`data/kb.sqlite`（SQLite + FTS5，稳定、无需额外服务）
- 前端入口：侧边栏 `知识库`
- 默认检索策略：Hybrid（FTS + Embeddings 语义召回 + LLM 重排）。其中 embeddings/重排为“尽力而为”，不可用时会自动退化为 FTS。
- 接口：
  - `GET /api/kb/documents`
  - `GET /api/kb/documents/{doc_id}`（返回全文，用于图谱抽取）
  - `POST /api/kb/documents`（`{title, source, text, agent_ids}`）
  - `DELETE /api/kb/documents/{doc_id}`
  - `GET /api/kb/search?q=...&agent_id=...`
  - `POST /api/kb/index`（预先为知识库分块生成 embeddings，加速语义检索）

#### 知识库分类

- 文档支持 `categories`（分类多选、无层级），用于按主题组织知识库。
- 专家侧可配置 `kb_categories` 作为“允许列表”：该专家检索时只会在这些分类下的文档中查找（若同时填了 `kb_doc_ids`，则优先按 `kb_doc_ids` 精确限定）。
- 前端：知识库上传页支持下拉多选分类；已上传文档也可在列表中点击 `分类` 进行修改。

#### Hybrid 参数与开关

- 环境变量（推荐写入 `.env`）：
  - `KB_EMBEDDING_MODEL=<provider>:<model>`（用于向量召回，例如 `dashscope:text-embedding-v3`）
  - `KB_RERANK_MODEL=<provider>:<model>`（可选，默认用 `CHAIRMAN_MODEL` 做重排）
- 设置接口也可动态调整（`POST /api/settings`）：
  - `kb_retrieval_mode`: `fts|semantic|hybrid`
  - `kb_embedding_model`: string
  - `kb_enable_rerank`: bool
  - `kb_rerank_model`: string
  - `kb_semantic_pool`: int（语义检索扫描的 chunk 上限）
  - `kb_initial_k`: int（初筛候选数量）

### GraphRAG 风格知识图谱（Neo4j）

- 依赖：本地 Neo4j（建议用 Docker 或 Neo4j Desktop）
- 环境变量见 `.env.example`：`NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD/NEO4J_DATABASE`
- 前端入口：侧边栏/聊天页 `图谱`
- 接口：
  - `GET /api/kg/graphs`
  - `POST /api/kg/graphs`（`{"name":"...","agent_id":"..."}`；若传了 `agent_id` 且该专家尚未配置 `graph_id`，会自动绑定）
  - `POST /api/kg/extract`（将文本按分段增量抽取实体/关系并写入 Neo4j；包含实体类型规范化、去重合并策略，参考 MiroFish-Optimize）
  - `GET /api/kg/graphs/{graph_id}`（返回 nodes/edges 便于前端可视化）
  - `POST /api/kg/graphs/{graph_id}/interpret/stream`（生成“节点解读/社区摘要”，SSE 返回进度并写回 Neo4j）
  - `POST /api/kg/graphs/{graph_id}/interpret`（非流式版本）
  - `GET /api/kg/graphs/{graph_id}/subgraph?q=...`（按实体名称关键字检索子图）

### 给专家绑定知识库与图谱

- `Agent 管理`里可为每个专家设置：
  - `kb_doc_ids`：该专家可用的知识库文档列表（只检索这些文档）
  - `kb_categories`：该专家可用的知识库分类“允许列表”（当未填写 `kb_doc_ids` 时生效）
  - `graph_id`：该专家对应的 Neo4j 图谱 ID（会自动取子图作为上下文）

### 推荐工作流（KB → KG → 专家注入）

1. 侧边栏进入 `知识库`，新增文档；可选“绑定专家”，用于后续自动注入。
2. 侧边栏进入 `图谱`，创建图谱（可选“绑定专家”，会自动写入该专家的 `graph_id`）。
3. 在 `图谱` 中选择图谱，使用“从知识库文档抽取”把文档内容抽取为实体/关系并写入 Neo4j。
   - 也可以选择“按分类批量抽取”，把某个分类下的全部知识库文档一次性写入图谱（带进度条与累计实体/关系统计）。
4. 回到聊天，选择参与专家后发起提问：每个专家会在 Stage1 自动注入其绑定的 KB 命中片段与 KG 子图摘要（同时写入 Trace，便于导出分析）。
