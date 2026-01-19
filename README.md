# SynthesisLab

![llmcouncil](header.jpg)

## 最近更新

- 活力模式（Stage 2B）改为“热身碰撞（每人 1 条）→ Chairman 选择可变数量意见领袖 → 领袖先发言并点名提问 → 其他人必须接话并给出新内容 → 自由流 + 收敛 checkpoint”的互动机制
- 意见领袖数量不固定（当前上限 3），支持主线（mainline）与分工（assignments），并明确禁止纯附和式回复
- 前端 Stage 2B 以“群聊气泡”方式展示（头像、系统提示），并展示活力模式元信息（script/turns/messages）
- 后端 `stage2b_complete` SSE 事件会携带 `metadata.lively`，用于前端回填展示

> 本仓库基于原始项目 `karpathy/llm-council`，并针对“数据分析/知识库/图谱/可长期迭代”的目标做了增强与优化。

## 项目简介（原始简介中文翻译）

这个仓库的想法是：与其只向你最喜欢的 LLM 提一个问题（例如 OpenAI、Google Gemini、Anthropic Claude、xAI Grok 等），不如把它们组成一个“LLM 委员会”。本项目是一个本地 Web 应用，界面类似 ChatGPT，但它会通过 OpenRouter（以及其它兼容 Provider）把你的问题同时发给多个模型，让它们互相评审并排序，最后由“主席（Chairman）”模型综合生成最终答案。

更具体一点，当你提交问题时会发生：

1. **阶段 1：初稿**：把用户问题分别发给所有模型并收集回答。前端用“Tab 视图”展示每个专家的独立回答，便于逐个查看。
2. **阶段 2：互评**：把其它专家的回答发给每个模型，并对身份做匿名化（避免偏袒），让模型从准确性与洞察等维度进行评审并给出排序。
3. **阶段 3：定稿**：由指定的主席模型综合所有回答与互评结果，输出最终结论。

## Vibe Code Alert（原作者声明中文翻译）

该项目最初是作者在一个周六“图一乐”的 99% vibe coding 作品，用于在“和 LLM 一起读书”的过程中并排对比多个模型的效果。并排查看多个回答、以及模型之间对彼此输出的交叉评价很有趣也很实用。作者不打算维护该项目，它按现状提供，仅供启发；想改什么就让你的 LLM 去改。

## 本仓库的增强（LLMCouncil-Optimization）

面向“可长期用于数据分析”的目标，本仓库在原始项目基础上做了增强（下面是最重要的变化点；更完整的模块说明见 `ARCHITECTURE.md`）：

- **Agent 管理增强**：前端可新增/编辑/删除 Agent，支持人设（system prompt）、权重/年资、启用/停用；支持自动生成人设。
- **会话级配置**：每个会话可选择参与专家子集；可在会话内按 **Agent 名称** 下拉选择 Chairman（仅影响阶段 3 综合）。
- **文本数据上传与解读**：聊天页支持上传文本文件 → 写入知识库 → 绑定到当前会话；阶段 1 注入时优先使用会话附件做检索与上下文。
- **知识库（SQLite）**：`data/kb.sqlite`，支持 FTS/语义/Hybrid 检索与可选 rerank；支持分类与按专家范围过滤。
- **知识图谱（Neo4j）**：图谱创建/抽取/可视化/节点解读与社区摘要；图谱界面支持拖拽调宽与节点详情侧栏。
- **可追溯 Trace**：LLM 调用与过程落盘 `data/traces/*.jsonl`，前端可直接查看与导出。
- **稳定性加固**：前端 ErrorBoundary 防白屏；后端关键 JSON 存储采用原子写入，降低文件损坏风险；启动脚本支持端口自动递增。

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

#### 持续导入（监听目录，新增）

- 目标：文件放进指定目录后自动落盘到知识库（可选自动建 embedding），做到“无感入库、可长期积累”。
- 默认监听目录：`data/kb_watch`（可在设置里修改）。
- 设置入口：前端 `流程设置` → `知识库：持续导入`
- 相关接口：
  - `GET /api/kb/watch/status`
  - `POST /api/kb/watch/scan`（立即扫描一次）
- 环境变量（写入 `.env`）：
  - `KB_WATCH_ENABLE=true|false`
  - `KB_WATCH_ROOTS=path1;path2`（分号/逗号分隔）
  - `KB_WATCH_EXTS=txt,md,json,log`
  - `KB_WATCH_INTERVAL_SECONDS=10`
  - `KB_WATCH_MAX_FILE_MB=20`

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
