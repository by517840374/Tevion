# 事件目录

> 本文档只记录当前 `apps/api/src/tevion_api` 已实现的事件与状态事实，不扩展未来事件设计。

## 1. 事件边界

当前有两类事件来源：

1. `TaskRuntime` 内存中的有界状态迁移事件 `TaskEvent`；
2. PostgreSQL 中持久化的 `FeedbackEvent` 与 `PreferenceEvent`。

`TaskEvent` 用于运行时记录与 replay；`FeedbackEvent` 和 `PreferenceEvent` 是数据库领域记录。当前 API 的 task/generation 持久化状态由 `Session.status` 与 `GenerationRun.status` 保存，尚未自动写入 `TaskRuntime.events`。

## 2. TaskRuntime 状态迁移事件

`TaskRuntime.transition()` 每次成功迁移都创建一个 `TaskEvent`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `event_id` | `str` | 运行时内生成，格式为 `<task_id>:event:<序号>` |
| `task_id` | `str` | 所属 task |
| `event_type` | `str` | 由调用方提供的迁移事件名称 |
| `from_state` | `TaskState` | 迁移前状态；runtime 初始状态为 `CREATED` |
| `to_state` | `TaskState` | 迁移后的状态 |
| `correlation_id` | `str` | 默认等于 `task_id`，用于 replay 归属校验 |
| `payload` | `dict[str, Any]` | 附加数据，默认 `{}` |
| `occurred_at` | `datetime` | UTC 时间 |

允许的迁移如下：

```text
CREATED → UNDERSTANDING
UNDERSTANDING → AWAITING_CONFIRMATION 或 PLANNING
AWAITING_CONFIRMATION → PLANNING 或 NEEDS_USER_REVIEW
PLANNING → EXPLORING 或 REFINING
EXPLORING/REFINING → GENERATING
GENERATING → EVALUATING 或 NEEDS_USER_REVIEW
EVALUATING → AWAITING_SELECTION、RETRYING 或 NEEDS_USER_REVIEW
RETRYING → GENERATING 或 NEEDS_USER_REVIEW
AWAITING_SELECTION → COMPLETED 或 REFINING
NEEDS_USER_REVIEW → PLANNING、RETRYING 或 COMPLETED
COMPLETED → （终态）
```

非法迁移抛出 `InvalidTransition`。进入 `RETRYING` 时递增 `retry_count`；达到 `max_retries` 后不允许继续重试。`replay()` 会从 `CREATED` 重放事件，并校验 `task_id` 与 `correlation_id`。

## 3. 持久化 task/generation 状态

状态源与 runtime projection 契约如下：

- `Session.status` 是跨请求持久化的 task-level canonical source。
- `GenerationRun.status` 是一次 generation attempt 的 attempt-level canonical source；runtime 读取该 task 的最新 run。
- `TaskRuntime` 仅是有界 transition validator/replay helper，`TaskRuntime.events` 只存在于当前进程，不是数据库状态源。
- runtime GET 只读已提交的 Session/GenerationRun projection：不创建 runtime、run 或 event，不调用 Provider，不触发 retry。
- 最新 run 为 `generating` 或 `unknown` 时，API `state` 投影为 `recovery_required`；为 `failed` 时投影为 `needs_user_review`。这两个值是 projection-only API 状态，不写入 Session/GenerationRun。
- 进程重启后只能读取最后一次已提交的数据库状态；不声称恢复外部 Provider 的 in-flight 工作。恢复或 retry 必须通过显式、有界命令完成。

创建 `POST /api/v1/tasks` 时，服务端创建一个 `Session` 和一个 `GenerationRun`，二者初始 `status` 都是 `created`。`GenerationRun` 还保存 `strategy_version`、请求参数和可选的 `parent_run_id`。服务层对持久化状态写入使用 bounded transition guard；非法转换被拒绝且不会改变对象状态。

调用 `POST /api/v1/tasks/{task_id}/generate` 后，`services.execute_generation()` 的当前迁移是：

```text
GenerationRun.status: created → generating
成功: generating → completed
失败: generating → failed
Session.status: created → awaiting_selection（成功时）
```

失败时会写入 `GenerationRun.error_code` 与 `error_message`，并重新抛出异常供 API 映射。成功时会写入 `model_name`、`latency_ms`、`estimated_cost`、`completed_at`，并为每个 `asset_url` 创建 `ImageVersion`。`TaskStatus`/`TaskSummary`/`TaskDetail`/`GenerateResponse` 对外暴露 task 状态；完整 `TaskRuntime` 状态机目前是独立的内存 runtime，不要把两套状态自动等同。

`refine` task 必须提供属于当前用户/项目的 `parent_version_id`；创建时保存 `parent_image_id` 和对应的 `parent_run_id`，生成出的 `ImageVersion` 继承该父图像关联。

## 4. `feedback_events`

ORM：`FeedbackEvent`；表：`feedback_events`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `str` | `feedback_` 前缀的 ID |
| `user_id` | `str` | 本地 `users.id` |
| `session_id` | `str` | 所属 task/session |
| `image_version_id` | `str` | 被选择或拒绝的 `ImageVersion` |
| `event_type` | `str` | 当前 API 写入 `selected` 或 `rejected` |
| `payload_json` | `dict` | 反馈详情 |
| `created_at` | `datetime` | UTC 创建时间 |

写入端点：

```http
POST /api/v1/tasks/{task_id}/feedback
```

请求模型 `FeedbackRequest` 要求 `version_id`，并要求提供 `accepted`/`selected` 或 `rejected` 之一；拒绝时必须提供 `rejection_reason`。服务端会校验 task、image version 与当前用户 ownership。当前写入的 payload 字段为：

- `selected: bool`
- `rejected: bool`
- `rejection_reason: str | null`
- `direction: str | null`，来自 `continue_direction`

## 5. `preference_events`

ORM：`PreferenceEvent`；表：`preference_events`。它是偏好证据记录，不是直接修改后的偏好快照。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `str` | `pref_event_` 前缀的 ID |
| `user_id` | `str` | 本地用户 ID |
| `scope` | `str` | `session`、`project` 或 `user`；投影器也能识别 `global`，但当前 API 查询 scope 只接受前三者 |
| `scope_id` | `str | null` | scope 对应资源 ID；`user` 可为空 |
| `key` | `str` | 偏好键 |
| `value` | `str` | 偏好值 |
| `source` | `str` | `explicit_feedback`、`tagged_feedback`、`selection`、`usage` 或 `inference` 等来源字符串 |
| `confidence` | `float` | 持久化置信度 |
| `deleted` | `bool` | tombstone；默认 `false` |
| `created_at` | `datetime` | UTC 创建时间 |

查询端点：

```http
GET /api/v1/preferences?scope=project&task_id=<task_id>
```

`project_preferences_for_task()` 会将当前 task 的反馈转换为 evidence，再合并匹配 scope 的 `PreferenceEvent`，交给 `PreferenceProjector`。来源权重为：`explicit_feedback=1.0`、`tagged_feedback=0.8`、`selection=0.7`、`usage=0.5`、`inference=0.2`。未 `consented` 的 `global` evidence 不参与投影；`deleted` evidence 移除对应 bucket。返回项包含 `key`、`value`、`source`、`confidence`（投影 weight）、`scope`、`scope_id` 与 `evidence_count`。

## 6. Ownership 与隐私边界

- 业务归属使用本地 `users.id`，不使用 email 作为 ownership key。
- task、image version、feedback 与 preference 查询必须经过当前用户 ownership 校验。
- 不在事件、日志或文档中记录 raw `Authorization` header、API key 或私有图像内容。
- `session`、`project`、`user` memory scope 分开处理；未 consent 的 global evidence 不进入投影。
- `downloaded`、`edited` 等 `FeedbackEvent.event_type` 值在领域模型中可表示，但当前 API 尚未写入这些事件。

## 7. 代码来源

- `apps/api/src/tevion_api/runtime.py`
- `apps/api/src/tevion_api/models.py`
- `apps/api/src/tevion_api/learning.py`
- `apps/api/src/tevion_api/services.py`
- `apps/api/src/tevion_api/schemas.py`
- `apps/api/src/tevion_api/main.py`
