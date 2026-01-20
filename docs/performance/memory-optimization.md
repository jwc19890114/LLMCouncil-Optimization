# Memory Optimization Guide (SynthesisLab)

本项目在“本地单机 + Neo4j + 前端 + 大模型/Embedding/Rerank”组合下，内存占用偏高是正常现象；但可以通过**定位耗内存进程**与**收敛高峰内存**显著改善体验。

下面按“先定位 → 快速见效 → 中长期改造”的顺序给出建议（包含 Neo4j）。

---

## 1) 先定位：到底是谁在吃内存？

通常是三类进程：

- `java`：Neo4j 数据库（最常见的大头）
- `node`：前端开发服务器（Vite dev），仅在开发模式下需要
- `python`：后端（FastAPI + Job + LLM 调用）

Windows 上可用 PowerShell 快速看：

```powershell
Get-Process | Where-Object { $_.Name -match 'python|node|java|neo4j' } |
  Select-Object Name,Id,@{n='WorkingSetMB';e={[math]::Round($_.WorkingSet/1MB,1)}} |
  Sort-Object WorkingSetMB -Descending
```

如果 `java` 明显最大，优先按 Neo4j 调参；如果 `node` 明显最大，优先切换到“生产前端（无 dev server）”。

---

## 2) 快速见效（不改架构的优化）

### A. Neo4j：限制 Heap + Page Cache（最关键）

Neo4j 的内存模型主要两块：

- **Heap**：Java 堆（查询、事务、对象等）
- **Page Cache**：页缓存（通常更大，默认会吃很多内存以换速度）

如果你是本地个人使用、图谱规模不大，建议把 Neo4j 限制在更小的内存预算（示例值按 8–16GB 内存机器估计）：

- 8GB 内存：Heap 512MB–1GB，PageCache 512MB–1GB
- 16GB 内存：Heap 1GB–2GB，PageCache 1GB–2GB

**Neo4j 5.x 配置（neo4j.conf）**

```properties
server.memory.heap.initial_size=512m
server.memory.heap.max_size=1g
server.memory.pagecache.size=1g
```

### A.1 Docker（Neo4j 5.26）低内存建议（你当前环境）

你当前 Neo4j 是 Docker（Neo4j 5.26.x）。默认情况下 Neo4j 会用 JVM heuristic 给出一个偏大的 `Max heap` 上限（例如 3~4GB），并且 page cache 如果不显式配置也可能偏大；这会导致 Docker/WSL 的内存上限被“慢慢吃满”。

本地个人使用、图谱规模不大时，可以把 Neo4j 控制在一个更“克制”的预算（可按需上调）：

```properties
# Keep memory predictable (local usage)
server.memory.heap.initial_size=256m
server.memory.heap.max_size=1024m
server.memory.pagecache.size=256m
server.jvm.additional=-XX:+ExitOnOutOfMemoryError
dbms.memory.transaction.total.max=256m
db.memory.transaction.max=64m
```

验证是否生效（看日志里的 `Max memory`/`pagecache`）：

```bash
docker exec <neo4j-container> bash -lc "grep -Ei 'Max   memory|server.memory.pagecache.size' /logs/debug.log | tail -n 20"
```

> 当你后续图谱数据明显增大、查询变慢时，优先把 `server.memory.pagecache.size` 提到 `512m` 或 `1g`；如果写入/抽取时出现内存压力，再把 heap max 提到 `1536m~2048m`。

**Neo4j 4.x 配置（neo4j.conf）**

```properties
dbms.memory.heap.initial_size=512m
dbms.memory.heap.max_size=1g
dbms.memory.pagecache.size=1g
```

> 你如果用 Neo4j Desktop：在数据库的 Settings 里改上述配置即可，然后重启数据库。

### B. 前端：日常使用别跑 `npm run dev`

`npm run dev`（Vite）会常驻一个 `node` 进程，内存占用比“静态构建产物”高很多。

- 开发时：保留 `npm run dev`（需要热更新）
- 日常使用/远程访问：建议用 `npm run build` 的产物，并用后端或 Nginx/Caddy 直接托管静态文件（这样运行时不需要 Node）

### C. KB 检索：适当降低“语义池”与 rerank

设置里两个参数会直接影响内存/延迟：

- `kb_semantic_pool`：语义检索会先拉取一定数量的 chunk 做向量相似度计算；越大越耗时/耗内存
- `kb_enable_rerank`：rerank 会再次调用模型，成本与延迟都更高

建议：

- 先把 `kb_semantic_pool` 调到 300–800 试试（本项目默认值已降到 400）
- 如果主要追求稳定与成本可控：临时关闭 rerank

---

## 3) 代码层：降低 KG 抽取高峰内存（已做）

KG 抽取之前会把全文分块后一次性累积到内存（chunks + entities + relations），长文时峰值明显。

已将抽取流程改为“逐块产出、逐块写入 Neo4j”的方式，避免一次性把所有 chunk 结果堆在内存里：

- `backend/kg_extractor.py`：新增 `iter_split_text()` 与 `iter_extract_kg_chunks()`（流式、低峰值）
- `backend/main.py` + `backend/tools/kg_extract.py`：改为 `async for` 逐块抽取并写入

如果你仍感觉 Neo4j 内存很高，通常说明**数据库本身配置或数据量**才是主因（继续看下一节）。

---

## 4) Neo4j 数据侧的优化思路（降低 DB 与 PageCache 压力）

### A. 不把“海量原文”长期塞进 Neo4j

当前 KG 抽取会把每个 chunk 的文本写入 `KGChunk.text`，这会让 Neo4j 数据量快速增长（进而推高 page cache 需求）。

更省内存的架构是：

- Neo4j 只存：实体/关系/引用（chunk_id、doc_id、offset 等）
- 原文 chunk 存：KB（SQLite）或对象存储
- 需要展示/解释时：通过 chunk_id 回查 KB 获取原文

如果你后续想进一步降 Neo4j 占用，可以按这个方向改造（影响面较大，建议单独开任务做）。

### B. 图谱展示别一次性加载太大

前端图谱渲染（vis-network）对节点/边非常敏感：

- 先用“子图搜索”查看局部
- 对大图做聚类/分层加载/按度数 TopN 展示

---

## 5) 推荐的“低内存运行姿势”（本地个人 & 可远程访问）

1. Neo4j：限制 heap/pagecache（见第 2 节）
2. 前端：用构建产物（不用 dev server 常驻 node）
3. 后端：Job 长任务继续走异步（避免阻塞与高峰堆积）
4. KB：降低 `kb_semantic_pool`，必要时关 rerank

---

## 6) 你需要我继续做什么？

要更精确地“对症下药”，请你给我两条信息：

1) 内存主要被哪个进程吃掉？（`java` / `node` / `python`，大概多少 MB/GB）  
2) Neo4j 你是用 Desktop 还是 Docker？版本是 4.x 还是 5.x？

我可以据此给你一套更贴近你机器的默认配置，并把“生产模式（无 Node）”的启动方式补齐到脚本里。
