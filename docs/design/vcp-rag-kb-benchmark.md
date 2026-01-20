# VCP 风格 RAG 向量知识库层对标（LLMCouncil）

本文件将 `D:\E盘\Python\CodexTest\VCPToolBox` 的向量知识库层（KnowledgeBaseManager + RAGDiaryPlugin 依赖的向量索引/缓存体系）与本项目当前实现进行对标，目标是：

- 低内存峰值、低 CPU 抖动
- 长期稳定运行（可恢复、可重建、可降级）
- 项目级长期记忆（Project-centric）为主
- 上下文注入 token 可控（严格 topK + 截断 + 总预算）

> 说明：本文仅为设计与对标规格，不代表当前已实现。

---

## 1. VCP 向量知识库层：可借鉴要点（抽象）

从 VCPToolBox 代码中可观察到的关键设计点：

- **事实源与索引缓存分离**
  - SQLite 作为事实源（chunks/tags/meta 等）
  - 向量索引（`*.usearch`）作为可再生缓存：索引损坏/缺失可从 SQLite 恢复/重建
- **多索引 + 分片 + 懒加载**
  - 按“库/日记本”维护独立索引（仅在需要时加载）
  - 全局 Tag 索引单独维护（体积小、常驻）
- **写入侧成本控制**
  - 文本分块（chunking）+ token 预算（safeMaxTokens）+ 批处理（max items）+ 并发可配
  - 429/5xx 退避重试，减少抖动
- **增量更新与变更聚合**
  - watcher 收集变更 → 聚合窗口 → 批量 flush
  - 延迟保存索引文件，减少磁盘抖动
- **缓存体系（TTL/LRU）**
  - embedding cache：避免重复向量化
  - query result cache：短时间重复查询直接命中
  - 索引 LRU：按内存压力卸载冷索引
- **工具输出降噪与向量融合**
  - 工具结果/HTML/base64 清洗后再向量化，避免“巨大无用 token”
  - 上下文向量采用衰减窗口聚合，而不是把长对话全塞 prompt

---

## 2. 本项目现状（LLMCouncil）

### 2.1 现有能力

- KB（事实源）：`data/kb.sqlite`（FTS/语义/hybrid 检索 + 可选 rerank）
- Jobs（后台长任务）：`data/jobs.sqlite`（可取消、可回填）
- Trace：`data/traces/*.jsonl`
- KG（Neo4j）：图谱抽取与可视化（建议长期只存引用，不存全文）
- 持续导入：KB watch（监听目录导入）

### 2.2 当前痛点（与 VCP 对标）

- 语义检索/索引构建容易出现“批量拉取”导致峰值内存/CPU 抖动
- embedding 与检索路径缺少系统性“批处理/限流/退避”规范（需要参数化）
- 缺少明确的“索引缓存层”（可再生、可恢复），易把向量/检索状态与事实源绑死
- 项目级长期记忆需要一套“写入触发、去重、清理”的规范（你已选择：仅报告/证据完成写入）

---

## 3. 目标架构（对标落地规格）

### 3.1 分层：事实源层 vs 索引缓存层

**事实源层（必须可靠）**
- `data/kb.sqlite`
- 存储：doc 元数据、chunk 文本、chunk_hash、更新时间、（可选）embedding 等

**索引缓存层（可再生）**
- 建议新增目录：`data/index/`（未来实现）
- 存储：向量索引文件（按分片），可删除可重建

**原则**
- 索引永远是缓存：坏了/没了就重建；服务可降级到 FTS/hybrid

---

## 4. 分片命名（Project-centric）

你选择“项目级长期记忆为主”，因此分片建议：

### 4.1 一级分片：Project

- `shard = project/<project_id>`
- 例：`data/index/project/3a1f.../vectors.*`

### 4.2 二级可选分片（将来按需）

- `project/<project_id>/category/<category>`：适合大量分类、冷热明显
- `project/<project_id>/agent/<agent_id>`：适合专家独立知识域强隔离

### 4.3 全局轻量索引（可选）

用于轻量的全局召回或标签体系：
- `global/tags`
- `global/titles`

---

## 5. 索引生命周期（对标 VCP 的“懒加载 + 可卸载 + 可恢复”）

定义每个 shard 的状态：

- **UNBUILT**：索引文件不存在
- **BUILDING**：后台构建中（job）
- **READY**：可用（已落盘 + 可加载）
- **STALE**：可用但落后于事实源（需要增量修复）
- **CORRUPT**：加载失败/校验失败（需重建）
- **EVICTED**：从内存卸载（落盘存在）

生命周期建议：

1) Query 命中 shard：
   - 若 READY：加载（或复用已加载）
   - 若 UNBUILT：创建构建 job（不阻塞当前请求，先降级到 FTS/hybrid）
2) 内存压力/冷 shard：
   - LRU 卸载（EVICTED），保留落盘索引
3) 事实源更新导致 STALE：
   - 增量修复 job（优先小批）
4) CORRUPT：
   - 备份损坏索引文件 → 全量重建

---

## 6. 故障回退状态机（可恢复）

下面是“索引读取/检索”视角的状态机（建议未来实现）：

1) **检索请求进入**
2) **尝试加载 shard 索引**
   - 成功 → 走向量检索
   - 失败（文件缺失）→ 标记 UNBUILT，触发构建 job，当前请求降级
   - 失败（校验失败/异常）→ 标记 CORRUPT，备份+重建 job，当前请求降级
3) **降级路径**
   - `hybrid` → 仅 FTS 或仅语义（取决于可用性）
   - 仍不可用 → 最终只走 FTS（保证可用）

**目标**
- 任何时候“可用性优先”：检索不因索引坏掉而中断用户主流程

---

## 7. 写入/构建触发点（结合本项目）

### 7.1 你确认的长期记忆写入（项目级）

仅在以下完成时写入“项目记忆条目”（小文本、低 token）：

- Stage4 报告完成（report）
- evidence_pack 完成（证据整理）

写入内容应指针化：保留 `kb_doc_id/chunk_id/url/message_id`，不写全文。

### 7.2 与 Jobs 的结合（现有基础可承载）

建议未来将以下动作都建模为 Jobs（便于可取消、可重试、可回填、可清理）：

- `kb_index`：embedding/索引构建（按 shard、按 doc、按增量）
- `memory_write`（建议新增）：从 report/evidence 产物提取“项目记忆条目”，写入 KB
- `index_rebuild`（建议新增）：索引损坏/迁移时全量重建
- `index_compact`（建议新增）：索引合并/压缩（视引擎而定）

---

## 8. 成本控制：Embedding 批处理/限流（对标 VCP）

建议未来参数化以下指标（并在文档/设置中明确默认值与上限）：

- `EMBED_MAX_TOKENS`：embedding 模型单次 token 上限
- `EMBED_SAFE_RATIO`：安全比例（建议 0.8–0.9）
- `EMBED_MAX_BATCH_ITEMS`：单批最大条数（例如 32/64/100）
- `EMBED_CONCURRENCY`：并发数（默认小，如 2–4）
- `EMBED_RETRY_MAX`：最大重试次数
- `EMBED_RETRY_BACKOFF`：指数退避 + 抖动
- `EMBED_SKIP_OVERSIZE`：超长 chunk 策略（跳过/截断/拆分）

目标：防止一次性吞入大量 chunk 导致峰值内存/CPU 飙升；对外部 provider 限流保持韧性。

---

## 9. 检索注入：topK + 截断 + 总预算（防 token 膨胀）

推荐固定流程（未来实现时可配置）：

- 召回：向量 topN（例如 40）
- 去重/过滤：按 doc_id/chunk_hash 合并
- 重排（可选）：rerank 到 topK（例如 8）
- 注入：最终注入 topK（例如 3–8）
- 约束：
  - 每条 chunk 截断到最大长度
  - 总注入长度/总 token 上限（强制）

---

## 10. 缓存清单（TTL/LRU）

建议未来补齐三类缓存（与 VCP 对标）：

1) **EmbeddingCache（TTL/LRU）**
   - key：chunk_hash / normalized_text_hash
   - value：embedding 向量

2) **QueryResultCache（TTL/LRU）**
   - key：(project_id, query, filters, k, rerank)
   - value：topK 结果（含引用指针）

3) **IndexLRU（内存层）**
   - key：shard_id
   - value：已加载索引句柄/对象
   - 触发：内存压力或超过 max_loaded_shards

---

## 11. 配置项清单（建议纳入 settings/.env 的规范）

### 11.1 与本项目已有配置映射（现状）

- KB 检索相关（已有）：`kb_retrieval_mode`、`kb_semantic_pool`、`kb_initial_k`、`kb_enable_rerank`、`kb_rerank_model`
- KB watch（已有）：`KB_WATCH_*`（或 settings.json 里的同名字段）
- Jobs（已有）：`job_tool_limits`、`job_default_timeouts`、`job_result_ttls`

### 11.2 建议新增的索引层配置（未来实现）

- `KB_INDEX_SHARD_MODE=project|project_category|project_agent`
- `KB_INDEX_MAX_LOADED_SHARDS=...`（索引 LRU 上限）
- `KB_INDEX_REBUILD_ON_CORRUPT=true|false`
- `KB_INDEX_SAVE_DEBOUNCE_MS=...`

### 11.3 建议新增的 embedding 管控配置（未来实现）

- `KB_EMBED_MAX_BATCH_ITEMS`
- `KB_EMBED_SAFE_RATIO`
- `KB_EMBED_CONCURRENCY`
- `KB_EMBED_RETRY_MAX`
- `KB_EMBED_RETRY_BACKOFF_BASE_MS`

---

## 12. 与 KG（Neo4j）的关系（边界）

- KB（RAG）负责“文本事实源 + 可控注入”
- KG（Neo4j）负责“结构化长期关联 + 可视化”
- 长期建议：KG 节点/边只存引用（chunk_id/doc_id），需要证据时回查 KB 原文

---

## 13. 里程碑建议（按收益/风险排序）

1) **定义索引缓存层与恢复策略**（先规格后实现）
2) **项目分片 + 懒加载 + LRU 卸载**（明显降内存）
3) **embedding 批处理/限流/退避**（明显降峰值与失败率）
4) **Query/Embedding TTL 缓存**（降重复计算与延迟）
5) **索引自愈（CORRUPT→备份→重建）**（长期稳定）

