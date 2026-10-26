# 多租户体系设计说明

本文说明记忆平台租户体系的设计：模型分层、数据库表结构、鉴权与隔离方式，以及每个关键选型的理由与代价。内容与当前代码一致（`app/`、`security/`、`infrastructure/db/`），设计说明书式的历史方案见仓库外的《RAG改造\_多租户记忆平台\_设计说明书.md》。

## 1. 设计目标

| 目标 | 落地方式 |
| --- | --- |
| 租户隔离 | 服务端强制 `tenant_id + project_id` 过滤；跨租户一律 404 |
| 可计费 | 每次 API Key 调用归因到 `tenant / project / api_key`，落 `usage_ledger` |
| 可限流 | Redis Lua 令牌桶（按 Key）+ 月度请求配额（按租户） |
| 可运维 | 指标、日志、链路都带租户/请求上下文 |
| 可演进 | `tenants.plan`、`status`、`project.settings` 为计费与配置预留 |

**明确不做**（当前阶段）：SSO / OIDC、资源级 ACL、跨租户共享项目、PostgreSQL RLS。这些属于后续演进，见第 7 节。

## 2. 模型总览

```
Tenant（公司/组织，计费与隔离的边界）
 ├── Membership ── User（一个用户可属于多个 Tenant，角色按租户区分）
 ├── Project（应用/环境，例如 prod、staging）
 │    └── ApiKey（凭证，绑定 project，携带 scopes）
 └── Memory（记忆，归属 tenant + project，向量在 Qdrant）
```

控制面与数据面使用不同凭证：

| 面 | 凭证 | 能力 | 典型接口 |
| --- | --- | --- | --- |
| 控制面 | JWT（用户登录） | 管理项目、签发/吊销 Key、看用量 | `/v1/auth/*`、`/v1/projects`、`/v1/api-keys`、`/v1/usage` |
| 数据面 | API Key | 读写记忆、检索 | `/v1/memories`、`/v1/memories/search` |

**为什么 Key 绑定 project 而不是 tenant**：Key 是"某个应用"的凭证。绑定 project 后，服务端能直接从 Key 推导出 `tenant_id + project_id`，客户端无需（也无法）在请求里指定项目，天然避免越权指定别的项目。同一个公司可以有多个项目、多把 Key，互不影响。

## 3. 数据库表设计

所有表使用 PostgreSQL，主键统一 `UUID`（`gen_random_uuid()`，PG13+ 内置），时间列统一 `timestamptz`。

### 3.1 `tenants`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | uuid | PK，默认 `gen_random_uuid()` | 租户 ID |
| `name` | varchar(128) | not null | 展示名 |
| `slug` | varchar(64) | not null，unique | 人类可读标识 |
| `plan` | varchar(32) | not null，默认 `free` | 套餐，配额分级的预留位 |
| `status` | varchar(32) | not null，默认 `active` | 可停用租户 |
| `created_at` / `updated_at` | timestamptz | not null | |

设计点：

- `slug` 全局唯一，注册时由名称生成并追加 8 位随机后缀（`make_slug`），避免"公司重名"导致注册失败。
- `plan` 目前不参与逻辑，但先建字段，后续按套餐调整配额/限流不需要改表。
- `status` 用字符串而不是布尔，方便扩展 `suspended`、`trial` 等状态。

### 3.2 `users`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | uuid | PK | |
| `email` | varchar(255) | not null，unique | 登录名，注册时统一小写 |
| `password_hash` | text | not null | argon2 哈希 |
| `status` | varchar(32) | not null，默认 `active` | 禁用用户 |
| `created_at` | timestamptz | not null | |

**表里没有 `tenant_id`**：用户与租户是多对多关系（一个人可能属于多家公司），归属关系放在 `memberships`，角色也随之按租户区分。

### 3.3 `memberships`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `tenant_id` | uuid | PK 之一，FK → tenants，CASCADE | |
| `user_id` | uuid | PK 之一，FK → users，CASCADE | |
| `role` | varchar(16) | not null，CHECK `owner/admin/member` | 租户内角色 |
| `created_at` | timestamptz | not null | |

设计点：

- **复合主键 `(tenant_id, user_id)`** 天然保证"一个用户在同一个租户只有一条成员关系"，不需要额外的唯一索引。
- **角色放在关系上**：同一个用户在不同租户可以是不同角色。
- **已知优化点**：登录时按 `user_id` 查全部成员关系，复合主键前缀是 `tenant_id`，帮不上忙；成员量大时应补 `(user_id)` 索引。当前按"用户加入的租户数通常很少"接受顺序扫描。

### 3.4 `projects`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | uuid | PK | |
| `tenant_id` | uuid | not null，FK → tenants，CASCADE | |
| `name` | varchar(128) | not null | |
| `slug` | varchar(64) | not null | |
| `settings` | jsonb | not null，默认 `{}` | 项目级配置 |
| `created_at` | timestamptz | not null | |

唯一约束是 `(tenant_id, slug)` 而不是 `slug` 全局唯一：不同租户都可以有 `prod`，但同一租户内不能重复。`settings` 用 JSONB 存放非关键配置（检索参数、回调地址等），避免每加一个配置就 migration；需要过滤/索引的字段仍应升格为独立列。

### 3.5 `api_keys`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | uuid | PK | |
| `tenant_id` | uuid | not null，FK，CASCADE | 冗余租户，便于按租户列出/吊销 |
| `project_id` | uuid | not null，FK，CASCADE | Key 的作用域 |
| `name` | varchar(128) | not null | 用途备注 |
| `key_prefix` | varchar(64) | not null，unique | 形如 `sk_live_ab12cd34` |
| `key_hash` | text | not null | `HMAC-SHA256(pepper, secret)` |
| `scopes` | varchar[] | not null，默认 `{}` | 权限集合 |
| `status` | varchar(16) | not null，CHECK `active/revoked/expired` | |
| `last_used_at` | timestamptz | null | 最近使用时间 |
| `expires_at` | timestamptz | null | 过期时间 |
| `revoked_at` | timestamptz | null | 吊销时间 |
| `created_at` | timestamptz | not null | |

索引：`(tenant_id, status)` 用于"列出我租户下的有效 Key"。

设计点见 5.4、5.5（密钥格式与哈希选型）。`last_used_at` 不随每次请求同步写库，而是先在 Redis 累积、定时批量回写，避免把读请求变成写请求。

### 3.6 `memories`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | uuid | PK | 同时作为 Qdrant point id |
| `tenant_id` / `project_id` | uuid | not null，FK，CASCADE | 归属 |
| `external_id` | varchar(255) | null | 调用方自己的 ID |
| `content` | text | not null | 记忆正文 |
| `content_hash` | varchar(64) | not null | SHA-256，用于去重 |
| `metadata` | jsonb | not null，默认 `{}` | 调用方自由字段 |
| `status` | varchar(16) | not null，CHECK `pending/active/failed/deleted/expired` | 索引状态 |
| `source` | varchar(64) | null | 来源 |
| `embedding_model` | varchar(128) | null | 向量模型标识 |
| `qdrant_point_id` | uuid | null | 向量点 ID |
| `importance` | float | not null，默认 0.5 | 重要性权重 |
| `expires_at` | timestamptz | null | TTL |
| `created_at` / `updated_at` | timestamptz | not null | |
| `deleted_at` | timestamptz | null | 软删除标记 |

索引：

- `(tenant_id, project_id, created_at)`：列表分页。
- **部分唯一索引 `(project_id, content_hash) WHERE deleted_at IS NULL`**：同一项目内正文不重复，但删除后可以重新写入同样的内容。
- `(project_id, external_id) WHERE external_id IS NOT NULL`：按外部 ID 查找，且不给空值建索引。

设计点：

- 常查字段（状态、归属、时间）是独立列，业务自定义信息才进 JSONB。
- `status` 覆盖整个异步索引生命周期：写入即 `pending`，worker 消费后 `active`，TTL 到期 `expired`，用户删除 `deleted`。
- 去重在应用层（先查 `content_hash`）和数据库层（部分唯一索引）各做一次，后者兜住并发写入。

### 3.7 `outbox`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | bigserial | PK | 自增，按写入顺序投递 |
| `event_id` | uuid | not null，unique | 消费端幂等依据 |
| `topic` | varchar(128) | not null | Kafka topic |
| `partition_key` | varchar(255) | not null | 保证同一记忆的事件有序 |
| `event_type` | varchar(64) | not null | `memory.created/updated/deleted` |
| `payload` | jsonb | not null | 事件体 |
| `status` | varchar(16) | not null，CHECK `pending/published/failed` | |
| `attempts` | int | not null，默认 0 | 重试次数 |
| `available_at` | timestamptz | not null | 可见时间（退避） |
| `created_at` / `published_at` | timestamptz | | |
| `last_error` | text | null | 最近一次错误 |

索引：部分索引 `(status, available_at) WHERE status = 'pending'`，只索引待投递的行，避免已发布数据拖大索引。

设计点见 5.8（Outbox 选型）。

### 3.8 `usage_ledger`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | bigserial | PK | |
| `event_id` | uuid | not null，unique | 落账幂等 |
| `tenant_id` / `project_id` | uuid | not null，FK，CASCADE | 计费归属 |
| `api_key_id` | uuid | null，FK，SET NULL | Key 删除后保留历史 |
| `metric` | varchar(32) | not null | 目前为 `request`，可扩展 token 等 |
| `quantity` | bigint | not null，CHECK `>= 0` | |
| `model` | varchar(128) | null | 预留模型维度 |
| `period` | varchar(7) | not null | `YYYY-MM`，按月聚合 |
| `occurred_at` | timestamptz | not null | |
| `created_at` | timestamptz | not null | |

索引：`(tenant_id, period, metric)` 支撑用量汇总；`(api_key_id, occurred_at)` 支撑明细查询。

设计点：**Redis 是快路径，PostgreSQL 是计费真相源**。请求计数先累加 Redis（原子、低延迟），再以事件流批量落账；`event_id` 唯一保证重放不重复计费。

## 4. 关键流程

### 4.1 注册

`POST /v1/auth/register` 在一个事务里创建 `user + tenant + owner membership + 默认 project`：

1. 校验邮箱未注册；
2. 生成 `tenant.slug`（名称归一化 + 8 位随机后缀）；
3. 先 `flush` 父表（user、tenant），再插入子表（membership、project），最后 `commit`；
4. 返回 JWT 和默认 `project_id`。

> 这里有一个真实踩坑：SQLAlchemy 在没有 `relationship()` 声明时不保证跨表插入顺序，曾出现先插 `memberships` 再插 `tenants`，真实 PostgreSQL 直接外键失败。现在显式分两次 flush，并加了顺序回归测试。

### 4.2 登录与租户解析

- 用户在多个租户时，`login` 必须显式传 `tenant_id`；恰好一个时自动选中；一个都没有返回 403。
- JWT  Claims：`sub`（用户）、`email`、`tenant_id`、`role`、`iat`、`exp`、`jti`，HS256 签名，默认 15 分钟。
- `decode_access_token` 强制要求 `exp/sub/tenant_id/role` 存在，缺少即视为非法。

**为什么把 `tenant_id` 和 `role` 放进 Token**：避免每个控制面请求都回表查成员关系；代价是角色变更最多滞后一个 TTL（15 分钟），敏感操作可以改成就近校验或加撤销列表。

### 4.3 API Key 签发与校验

**格式**：`sk_<env>_<prefix8>_<secret32>`

- `env`：`live` / `test`；
- `prefix`：8 位随机串，明文存储、全局唯一；
- `secret`：32 位随机串，只返回一次，库里只存 `HMAC-SHA256(pepper, secret)`。

**签发**：生成 prefix + secret → 计算 hash → 入库 → 明文只在响应里返回一次。

**校验链路**（`require_api_key`）：

```
Bearer Token
  → parse_api_key（格式/长度校验）
  → Redis 缓存按 key_prefix 查（TTL 300s）
  → 未命中则按前缀查 DB，并回填缓存
  → HMAC + compare_digest 校验 secret
  → status / expires_at / revoked_at 检查
  → 令牌桶限流（按 api_key_id）
  → 月度配额（按 tenant_id）
  → 写 last_used（Redis 缓冲）
  → 写用量事件（Redis 队列）
  → 构造 AuthPrincipal(tenant_id, project_id, scopes)
```

吊销 Key 时主动删除缓存，避免 300 秒内旧缓存继续放行。

### 4.4 租户上下文与数据隔离

- 鉴权依赖把 `tenant_id / project_id / scopes` 注入 `AuthPrincipal`，路由只拿得到这个对象，**没有渠道传入别的租户**。
- 所有记忆查询都显式带 `WHERE tenant_id = ? AND project_id = ?`（见 `MemoryRepository.get_for_scope / list_for_scope`）。
- 跨租户访问返回 **404** 而不是 403：不泄露"这个 ID 是否存在"。
- 向量检索在 Qdrant 侧同样带 `tenant_id / project_id / status` 过滤，并提前建了 payload 索引。
- Redis 键都带归属信息，例如限流 `key:<api_key_id>`、配额 `quota:<tenant_id>:<YYYY-MM>:requests`、幂等 `idem:memory.create:<tenant_id>:<key>`。
- 指标可选按租户拆分，但用 `METRICS_TENANT_ALLOWLIST` 白名单控制基数。

### 4.5 写入与异步索引

1. 应用层按 `(project_id, content_hash)` 查重；并发下由部分唯一索引兜底，`IntegrityError` 时回查已有记录。
2. 同一个事务里写 `memories` 和 `outbox`，保证"数据在则事件在"。
3. Relay 用 `FOR UPDATE SKIP LOCKED` 领取待投递事件，投递 Kafka 后标记 `published`；多实例安全。
4. Worker 消费事件：校验事件里的 tenant/project 与数据库一致 → 先置 `active` → 写 Qdrant（payload 带 status）→ 提交。
5. 重复投递由 `event_id` + 状态判断消化，做到 **at-least-once 投递、effect-once 效果**。

### 4.6 用量与配额

- 每次 API Key 请求写一条用量事件到 Redis 列表，60 秒批量落 `usage_ledger`；落账失败会把整批放回队首，重放由 `event_id` 去重。
- 配额在 Redis 里用 Lua 原子"读-判-加"，键按租户+月份；Redis 不可用时 fail-open（放行），账本仍可通过恢复后的缓冲补齐。
- `GET /v1/usage/reconcile` 对比 Redis 计数与账本总量，发现漂移。

## 5. 选型与理由

### 5.1 为什么是 `tenant → project → api_key` 三级

| 方案 | 优点 | 问题 |
| --- | --- | --- |
| 单级 `tenant` + Key | 简单 | 无法区分同一公司的多个应用/环境，Key 权限粒度粗 |
| 三级（当前） | 隔离、计费、权限都能落到合适的层级 | 多一层模型与校验 |
| 四级（+ workspace 等） | 更细 | 当前业务不需要，增加认知成本 |

租户是**计费与数据隔离**边界，项目是**应用/环境**边界，Key 是**凭证与权限**边界。三者职责不重叠。

### 5.2 为什么 PostgreSQL，而不是 MySQL

- **JSONB**：`metadata` / `settings` / outbox `payload` 需要存半结构化数据并偶尔查询；MySQL 的 JSON 能力弱于 JSONB（索引与操作符）。
- **部分唯一索引**：`(project_id, content_hash) WHERE deleted_at IS NULL` 这种"软删后允许重建"的约束，PostgreSQL 原生支持。
- **数组类型**：`scopes varchar[]` 直接存储，读取一把取回。
- **`FOR UPDATE SKIP LOCKED`**：outbox 多实例领取，MySQL 8 也有但生态与语义不如 PostgreSQL 成熟。
- **事务与约束完整性**：账单、幂等、外键级联都依赖强一致。
- **`gen_random_uuid()` 内置**：不需要额外扩展。

代价：团队要熟悉 PostgreSQL 运维；托管成本通常略高于 MySQL。

### 5.3 为什么主键用 UUID

- ID 会出现在 API 响应、日志、事件里，UUID 不可枚举，避免泄露规模与顺序。
- 客户端/多服务可以本地生成，不依赖数据库序列。
- 代价：索引比自增主键大、随机写入有页分裂。当前量级可接受；outbox/usage 这类纯内部表仍用 bigserial，避免无谓开销。

### 5.4 为什么 API Key 用 HMAC+pepper，而密码用 argon2

- API Key 的 secret 是 **32 位随机串（约 190 bit 熵）**，暴力破解不可行，不需要"慢哈希"；需要的是**快速校验 + 按前缀 O(1) 查找**。
- HMAC-SHA256 是确定性哈希，可以按 prefix 定位唯一一行后用 `compare_digest` 常量时间比较。
- 加 pepper（服务端密钥）后，即使数据库泄露，攻击者没有 pepper 也无法离线撞库。
- 密码熵低，必须用 argon2 这类内存硬哈希抵抗字典攻击；两者场景不同。

### 5.5 为什么单独存 `key_prefix`

- 明文 Key 不能存，直接按 hash 查又需要全表扫描。
- 前缀明文 + 唯一索引，让校验变成"一次索引查找 + 一次 HMAC 比较"。
- 前缀只有 8 位随机（约 47 bit），碰撞概率低；唯一约束兜底，碰撞时重新生成。

### 5.6 为什么 `scopes` 用数组，而不是关联表

- scope 是**固定的少量枚举**（`memories:read`、`memories:write` 等），每次鉴权要整体判断。
- 数组读取一次取回，`admin` 可以隐含全部权限；关联表更适合"权限本身可动态增删、需要按权限反查用户"的场景。
- 代价：无法直接按单个 scope 建外键；需要时可以对数组建 GIN 索引。

### 5.7 为什么软删除 + 部分唯一索引

- 记忆删除后仍要保留审计/追溯能力，所以用 `deleted_at` 软删。
- 普通唯一索引会让"删除后重新写入同样内容"失败；部分唯一索引只约束 `deleted_at IS NULL` 的行，正好符合业务语义。
- 所有查询统一带 `deleted_at IS NULL`，避免漏过滤。

### 5.8 为什么用 Outbox，而不是"写库 + 发 Kafka"双写

| 方案 | 问题 |
| --- | --- |
| 双写（先写库再发 Kafka） | 发消息失败 → 库里有、索引没有；先发后写 → 消息指向不存在的记录 |
| 事务消息 | Kafka 事务与数据库事务无法真正原子 |
| Outbox（当前） | 业务写入与事件在同一个事务里；Relay 异步投递；at-least-once + 消费幂等 |

代价：多一张表、多一个 Relay 进程、需要处理重复投递与积压监控（已接入指标与告警）。

### 5.9 为什么限流/配额用 Redis，账本用 PostgreSQL

- 限流要**每个请求**执行，必须在毫秒级完成；Redis + Lua 单线程原子执行令牌桶，避免"读-改-写"竞态。
- 配额是跨实例共享的月度计数，数据库行锁会成为瓶颈。
- 但 Redis 可能丢数据、过期策略也可能误伤，所以**计费真相放 PostgreSQL**；Redis 只做快路径，二者通过事件流与对账接口收敛。

### 5.10 为什么跨租户返回 404

403 意味着"资源存在但你无权访问"，会泄露资源是否存在。对多租户系统，跨租户请求应当表现得像"这个资源根本不存在"。这也是 OWASP 推荐的防枚举做法。

### 5.11 为什么 JWT 而不是服务端 Session

- 控制面调用量小，但需要无状态水平扩展；JWT 不需要共享 Session 存储。
- 代价：无法即时撤销。当前用 15 分钟短 TTL 控制风险；后续可加 `jti` 黑名单或 refresh token。
- 数据面不使用 JWT，而用 API Key：API Key 可长期使用、可按项目签发/吊销，适合机器调用。

## 6. 隔离与降级行为

| 场景 | 行为 |
| --- | --- |
| Redis 不可用 | 限流、配额、幂等 fail-open（放行）；API Key 缓存回源数据库；`last_used` 与用量事件可能延迟 |
| API Key 被吊销 | 数据库状态立即生效，同时删除缓存；最坏 300 秒缓存窗口已被主动关闭 |
| JWT 角色变更 | 最多滞后一个 TTL（默认 900 秒） |
| Worker 积压 | outbox 指标暴露积压条数与最老等待时长，超过阈值触发告警 |
| 索引失败 | worker 重试 3 次后投递 DLQ；记忆保持 pending，不会误报为 active |
| 多 API 实例 | 无状态，直接扩容；限流/配额在 Redis 共享 |
| 多 Worker 实例 | 消费组分摊分区；outbox 用 SKIP LOCKED；用量落账用原子取批 |

## 7. 已知限制与演进方向

1. **没有 PostgreSQL RLS**：目前靠应用层强制过滤。加 RLS 可做纵深防御，但需要为每个请求设置 `SET LOCAL app.tenant_id`，并改造连接池/事务边界。
2. **`memberships(user_id)` 缺索引**：成员量大时登录会顺序扫描。
3. **JWT 无法即时撤销**：短 TTL 缓解，必要时加 `jti` 黑名单。
4. **API Key 无轮换接口**：目前只能吊销后重建；可加"双 Key 并行 + 到期吊销"的轮换流程。
5. **`tenants.plan` 未参与配额**：当前是全局默认配额，后续按套餐读取不同上限。
6. **删除租户的跨存储清理**：数据库有 FK CASCADE，但 Qdrant 向量、Kafka 事件、Redis 键需要异步清理任务。
7. **无审计日志**：Key 签发/吊销、成员变更等管理操作应落审计表。
8. **指标租户维度需白名单**：避免租户 ID 作为标签导致基数爆炸，当前通过 `METRICS_TENANT_ALLOWLIST` 控制。

## 8. 附录

### 8.1 配置项

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://rag:rag@localhost:5432/rag` | 数据库 |
| `REDIS_URL` | `redis://localhost:6379/0` | 缓存/限流/配额 |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | 事件总线 |
| `API_KEY_PEPPER` | `dev-pepper-change-me` | API Key HMAC pepper，生产必须更换 |
| `JWT_SECRET` | 开发默认值 | JWT 签名密钥，生产必须更换 |
| `JWT_ACCESS_TTL_SECONDS` | `900` | 访问令牌有效期 |
| `RATE_LIMIT_RATE` / `RATE_LIMIT_BURST` | `20` / `40` | 每 Key 每秒速率/突发 |
| `MONTHLY_REQUEST_QUOTA` | `100000` | 每租户每月请求上限 |
| `METRICS_TENANT_ALLOWLIST` | 空 | 允许出现在指标标签里的租户 |

### 8.2 表关系

```
users ──< memberships >── tenants ──< projects ──< api_keys
                             │            │            │
                             └──< memories ─────────────┘
                             └──< usage_ledger
tenants/projects/api_keys ──< outbox（payload 引用，无外键）
```

### 8.3 代码索引

| 关注点 | 文件 |
| --- | --- |
| 表模型 | `infrastructure/db/models.py`、`migrations/versions/` |
| 租户内查询 | `infrastructure/db/repositories.py` |
| 注册/登录 | `app/auth_routes.py`、`security/auth.py` |
| API Key 生成与哈希 | `security/api_keys.py` |
| 鉴权与限流/配额 | `app/deps.py`、`infrastructure/cache/` |
| 记忆写入与幂等 | `app/memory_routes.py`、`infrastructure/cache/idempotency.py` |
| Outbox/消费 | `infrastructure/db/outbox.py`、`infrastructure/queue/` |
| 用量账本 | `infrastructure/cache/usage_*.py`、`app/usage_routes.py` |
