# Deployment & Multi-user Design (Draft)

This note captures the decisions and recommendations discussed in chat, focusing on:

- Remote access (personal use first)
- Safe production exposure (do not run open-to-internet by default)
- A practical path from single-user local storage to multi-user service deployment

---

## 中文要点（落盘）

### 现状定位

- 当前更偏“本地单人工具”：会话/设置等以本地文件落盘为主，缺少面向公网/多租户的鉴权与权限隔离。
- 因此不建议直接把现有服务裸露到公网；优先走“安全远程访问”，再演进到“多人服务化部署”。

### 远程访问（先满足你自己用）

**方案 A（推荐）：零信任/虚拟局域网**

- 使用 `Tailscale` / `ZeroTier` 将你的电脑与远程设备加入同一虚拟局域网。
- 仅对虚拟网开放服务端口（例如 `8001/8002`），不需要公网暴露端口、不改代码。
- 优点：安全、维护成本低；缺点：本质还是“单机服务”，多人并发与数据隔离仍需后续改造。

**方案 B：VPS + 反代（HTTPS）+ 鉴权**

- 用 `Nginx/Caddy` 做反向代理与 `TLS`，只暴露一个域名到公网。
- 后端服务跑在内网端口；反代层至少加一层鉴权（Basic Auth 或应用层登录），并配置限流与上传限制。

### 多人化目标（建议先做 Multi-user v1）

建议先把“多人 v1”范围限定为：

1. 登录（JWT/Session）+ 基础权限（管理员/普通用户）
2. 数据隔离：会话/知识库/图谱/文件都绑定 `owner_id/tenant_id`
3. Job 任务：状态/日志持久化，支持取消/重试/幂等
4. 资源控制：按用户/会话限流与配额（避免 token 失控）

### 数据与存储（从本地落盘演进到可并发的服务端）

**元数据与业务数据**

- 建议迁移到 `PostgreSQL`（后续可用 `pgvector` 承载向量）。
- 核心表建议：`users`、`conversations`、`messages`、`jobs`、`job_events`、`kb_documents`、`kb_chunks`、`graphs`（如有）。

**文件与大对象**

- 上传文件建议存对象存储：`S3/MinIO`（本地可先 MinIO，线上也可继续 MinIO 或 S3）。
- 数据库只存：文件元信息、哈希、关联关系与权限字段。

### Job 长任务（你已在做的方向，继续加强）

多人环境下，Job 建议具备：

- 可取消：用户中断时能停止下游模型调用/检索/分块流程
- 可恢复/可追踪：事件流（SSE）只用于展示；真相在 `job_events` 表
- 幂等：同一输入/同一文档批处理避免重复跑
- 并发上限：按用户、按队列类型（例如：索引/抽取/检索）分别限制

队列实现可选：`Celery/RQ/Arq` 任一即可，搭配 `Redis`。

### 安全底线（上线必备）

- 全站 `HTTPS`（TLS）
- 应用层登录鉴权 + 关键资源 `owner/tenant` 校验
- 限流（按 IP/用户）与上传大小/类型白名单
- CORS/CSRF 策略清晰（前后端分离时尤其重要）
- 密钥仅在后端使用（前端不落任何 API Key）
- 审计日志（至少记录：登录、上传、删除、导出、关键任务触发）

### 成本与体验（多人场景的“稳”）

- 缓存：embedding、rerank、检索结果可按“文档哈希/查询 hash”缓存
- 预算：按用户设置 token/次数上限；长任务强制分段与中间落盘
- 降级：模型失败时返回可理解的提示，并保留“失败点”方便重试

### 推荐部署形态（最小可用多人架构）

- `Caddy/Nginx`：HTTPS + 反代 + 限流
- `backend`：API 服务（多进程）
- `worker`：跑 Job（队列消费）
- `PostgreSQL`：业务数据
- `Redis`：队列/缓存
- `MinIO`：文件存储

可以先用 `docker-compose` 串起来，后续再演进到 k8s。

### 里程碑建议

- Phase 0：本地单机（继续迭代功能）
- Phase 1：安全远程访问（Tailscale/ZeroTier 或 HTTPS 反代+鉴权）
- Phase 2：多人 v1（登录 + 隔离 + Job 入库 + 配额）
- Phase 3：多人协作增强（共享会话/共享知识库、协同编辑、实时性等）

