# Provider 契约

> 本文档以当前 `apps/api/src/tevion_api/provider.py` 与调用方实现为准，记录已实现边界，不新增 Provider 设计。

## 1. 内部接口

业务代码依赖 structural `Protocol`，不依赖供应商 SDK：

```python
class ImageGenerationProvider(Protocol):
    def generate(self, request: GenerationRequest) -> GenerationResult: ...
```

Provider 负责组装外部请求、处理同步或异步响应、轮询任务并将结果规范化。`services.execute_generation()` 只消费 `GenerationResult`，然后持久化 `ImageVersion` 与 generation 状态。

## 2. `GenerationRequest`

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `prompt` | `str` | 必填 | 生成提示文本 |
| `output_count` | `int` | `1` | 输出数量；Maizitech 仅在大于 1 时发送 `n` |
| `aspect_ratio` | `str` | `1:1` | 内部尺寸/比例值；Maizitech 映射为 `size` |
| `strategy_version` | `str` | `default` | 策略版本标识 |
| `quality` | `str` | `low` | Provider quality 参数 |

当前 `services.execute_generation()` 从 task 参数创建 request；`strategy_version` 保留在 task/run 领域数据中，当前 execute path 未将其单独传入 `GenerationRequest`。

## 3. `GenerationResult`

| 字段 | 类型 | 说明 |
|---|---|---|
| `provider_request_id` | `str` | 外部请求 ID 或异步 task ID；同步响应可为空字符串 |
| `model_name` | `str` | 实际模型名称 |
| `asset_urls` | `list[str]` | 生成资源 URL 列表 |
| `latency_ms` | `int` | Provider 调用耗时 |
| `cost` | `float | None` | Provider 返回的成本（若有） |
| `metadata` | `dict[str, Any] | None` | 规范化后的附加信息 |

`MaizitechImageProvider` 的异步结果 metadata 当前包含 `provider`、`params` 与从 `params` 读取的 `size`；业务层用 `size` 解析图像宽高，并将 model/provider 写入 `ImageVersion.metadata_json`。

## 4. `GPTImageProvider` 规范化边界

`GPTImageProvider` 是 GPT Image 2-compatible API 的规范化实现：

- payload 字段为 `model`、`prompt`、`n`、`aspect_ratio`；
- 响应要求非空字符串 `id`、非空列表 `data`，并从其中提取非空 `url`；
- `usage.cost` 如存在必须是 number；
- 结果转换为 `GenerationResult`，可带 `strategy_version` metadata。

## 5. Maizitech async polling

实现类：`MaizitechImageProvider`。默认 `base_url` 为：

```text
https://www.maizitech.ai/v1
```

### 提交

向下列地址发送带 Bearer token 的 JSON POST：

```http
POST /images/generations
```

当前提交 body：

- `model`: `model_name`，默认 `gpt-image-2`
- `prompt`: `GenerationRequest.prompt`
- `size`: `GenerationRequest.aspect_ratio`
- `quality`: `GenerationRequest.quality`
- `n`: 仅当 `output_count > 1` 时发送

正常异步响应从 `data[0].task_id` 取得 task ID。若 `data` 直接含有带 URL 的 item，则按 synchronous-style 响应直接返回，不轮询。

### 轮询与结果

异步任务向以下地址 GET 轮询：

```http
GET /tasks/{task_id}
```

默认每 2 秒轮询，默认总超时 180 秒。`status=completed` 后读取 `result_urls`；若状态为 `failed`、`error` 或 `cancelled`，立即视为失败；超时或 completed 但没有结果 URL 也视为失败。成功结果的 `provider_request_id` 为 task ID。

HTTP 非成功响应由 `httpx` 的 `raise_for_status()` 处理，传播 `httpx.HTTPStatusError`。

## 6. 错误分类与业务状态

配置或响应错误类型：

- `ProviderConfigError`：缺少必要 endpoint 或 API key；
- `ProviderResponseError`：task ID、结果数据或 completed 结果不符合预期；
- `classify_provider_error()` 的标准分类：`timeout`、`rate_limit`、`server_error`、`model_unavailable`、`malformed_response`、`provider_error`。

在 `services.execute_generation()` 中：

```text
run.status: created → generating → completed（成功）
run.status: generating → failed（ProviderResponseError 或其他异常）
```

失败会写入 `GenerationRun.error_code` 与 `error_message` 并重新抛出；`ProviderResponseError` 映射为 `provider_error`，其他异常映射为 `internal`。成功会写入 model、latency、estimated cost 与 completed time，并将 `Session.status` 设为 `awaiting_selection`。错误文本最多保存 2000 字符（通用异常路径），Provider task 错误会先做 API key redaction。

## 7. Secret 边界

- API key 通过运行环境传入：API 当前从 `MAIZI_API_KEY` 读取；`MAIZI_BASE_URL` 与 `MAIZI_MODEL` 可覆盖默认值。
- `MaizitechImageProvider` 在内部构造 `Authorization: Bearer <key>`；API key 不进入请求 JSON。
- Provider 的 `_api_key`（`GPTImageProvider`）或 `api_key`（`MaizitechImageProvider`）不应写入日志、测试输出、commit 或文档。
- Maizitech provider 的失败文本会替换 API key 为 `[REDACTED]` 后再抛出；不记录 raw authorization header。
- 真实图片 URL 属于资产数据，不应复制到日志、Issue 或文档；测试使用 mock transport，不调用真实供应商。

## 8. 替换 Provider 的最小要求

1. 实现 `ImageGenerationProvider.generate()`。
2. 将外部请求/响应转换为 `GenerationRequest` / `GenerationResult`。
3. 将异步 polling、HTTP 错误、失败状态与 secret redaction 保留在 Provider 边界内。
4. 不让业务层依赖供应商 SDK 类型。
5. 使用 focused tests 覆盖 payload、成功规范化、async polling、失败响应与 secret redaction。

本文档不规定未实现的重试策略、webhook、资产下载、Provider 路由或成本策略。

## 9. 测试来源

当前 Provider 行为由以下测试使用 `httpx.MockTransport` 覆盖，不产生真实供应商费用：

- `apps/api/tests/test_maizitech_provider.py`
- `apps/api/tests/test_provider.py`
- `apps/api/tests/test_provider_errors.py`
- `apps/api/tests/test_generation_failure.py`
- `apps/api/tests/test_generation_loop.py`

## 10. 代码来源

- `apps/api/src/tevion_api/provider.py`
- `apps/api/src/tevion_api/services.py`
- `apps/api/src/tevion_api/main.py`
- `apps/api/tests/test_maizitech_provider.py`
- `apps/api/tests/test_provider.py`
