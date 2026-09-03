# Tevion

Tevion 是一个产品化的视觉 AI Agent。当前阶段聚焦于帮助用户创作**明确为成年男性的肖像**，呈现清新、年轻的活力感，具备有力的光影效果，并支持可控的视觉风格。

Tevion 的长期目标不是简单封装图像 API，而是成为能够从用户的选择、编辑、评价和使用行为中学习的个人视觉 Agent。

## 产品理念

```text
用户意图 → 视觉理解 → 候选生成 → 对比选择 → 反馈
        → 偏好记忆 → 下一次做出更好的决策
```

首个版本将 GPT-image2 作为可替换的图像生成 Provider。产品的核心边界包括：Web/App 体验、task/session/version 数据模型、反馈闭环，以及受策略控制的学习层。

## 仓库现状

- `apps/api/`：后端基础设施、领域契约，以及已实现的 API 模块（health、product、tasks、runtime、provider、learning）。
- `docs/`：产品文档、架构文档和决策记录。
- 数据层已落地：PostgreSQL（Docker 本地开发）、Alembic 迁移，以及 8 张核心表（users、projects、personas、sessions、generation_runs、image_versions、feedback_events、preference_events）。
- 前端代码在早期产品探索阶段暂不放入本仓库。目前本地原型位于：`/Users/adtiger/Tevion-frontend`。
- `README.en.md`：英文版说明文档。

## 第一阶段暂不包含的内容

- 不训练基础模型。
- 不实现不受限制的自主 Agent 循环。
- 不允许跨用户检索私有案例。
- 交互模型验证完成前，不发布正式前端代码。
- 不强依赖 ComfyUI；未来可以将其作为一个 Provider 接入。

## 本地运行 API

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn tevion_api.main:app --reload
```

当前 API 已提供健康检查、产品元数据、任务创建，以及任务运行时快照端点；生成 Provider 的实际执行与持久化仍按分层边界继续演进。

## 本地数据库（Docker 运行 PostgreSQL）

产品数据层使用 PostgreSQL。本地开发通过 docker-compose 运行真实的数据库实例：

```bash
docker compose up -d db          # 启动 PostgreSQL 16，并创建 `tevion` 与 `tevion_test`
cp .env.example .env             # 可选：复制并修改本地配置
cd apps/api
.venv/bin/alembic upgrade head   # 将迁移应用到 `tevion`
.venv/bin/python -m pytest       # 运行测试，包括真实 PostgreSQL 往返测试
```

`.env` 中的 `TEVION_DB_URL` 可以覆盖默认的本地数据库 URL。测试使用独立的 `tevion_test` 数据库；当 PostgreSQL 无法连接时，相关测试会自动跳过。

## 项目原则

1. 产品体验优先于 Provider 锁定。
2. 在开放式自主运行之前，先建立明确的状态转换规则。
3. 每个 prompt、tool call、图像版本、决策和反馈事件都必须可追溯。
4. 严格区分 session memory、user preference 和 global strategy learning。
5. 学习提案必须经过评估和版本化后才能发布。
6. 用户图像和私有偏好默认保持私有。

## 文档导航

建议先阅读以下文档：

1. `docs/PRODUCT_BRIEF.md`：产品目标、用户、核心体验、指标和风险。
2. `docs/PRODUCT_DEVELOPMENT_FLOW.md`：六类产品开发流程。
3. `docs/ARCHITECTURE.md`：系统边界、状态机、Provider 契约和记忆隔离。
4. `docs/DECISIONS.md`：已确定的产品与架构决策。

如需查看英文版，请阅读 `README.en.md`。

## 许可证

当前仓库未在 README 中声明许可证；如需开源发布，请先补充明确的 License 文件和说明。

## 相关链接

- GitHub：<https://github.com/by517840374/Tevion>
- 前端探索目录：`/Users/adtiger/Tevion-frontend`
