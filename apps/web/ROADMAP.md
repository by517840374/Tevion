# Tevion 前端产品化路线（Frontend Roadmap）

> 状态：持续维护 · 位置：仓库内 `apps/web/`（ADR-008）· 语言：中文
> 关联后端：`apps/api`（FastAPI，真实 PostgreSQL + 认证 + GPT-image2 已通）
> 项目状态更新：2026-09-05 · 方案依据 GitHub Issue #70/#72/#73/#75/#76 与 PR #71/#74 的实际状态

## 1. 现状

`apps/web` 是从迁移备份恢复的零依赖静态原型（index.html / styles.css / app.js），已验证核心交互：
Explore/Refine 模式、视觉标签、理解确认节点、候选选择、Visual Memory 展示。
当前主流程已接入真实 API：任务创建、候选生成、反馈提交和 Visual Memory 偏好读取已在 `origin/main` 实现；Issue #24、#28、#29、#30 对应实现已合并。Issue #70 的 failed generation 显式 retry 已通过 PR #71 合并；Issue #72 的 generation migration drift 已通过 PR #74 合并，并已验证 `alembic upgrade head`、`alembic check` 与 API 测试通过。当前前端优先任务为 Issue #73 的 Impeccable critique → audit → polish；后端 #75（unknown reconciliation 边界）处于 shaping，#76（recovery phase 字段契约）待串行推进，避免与已完成的 generation 代码区域产生并行冲突。

## 2. 产品化目标

把"概念演示"变成"真实闭环"：登录 → 自然语言 + 标签 → 真实生成候选 → 选择/反馈 → 偏好可见。

```text
登录（token）
  → 新建会话（POST /api/v1/tasks）
  → 生成候选（真实 GPT-image2，任务状态轮询）
  → 候选比较与选择（反馈事件）
  → Visual Memory 真实投影（GET preferences）
```

## 3. 里程碑

### M1 真实数据接入（已完成）
- 保持无依赖模块化 JS，待 UX 定型后再评估 Vite + React；
- `api client` 层：token 存储（dev：注入；prod：OIDC code flow）、fetch 封装、错误统一处理；
- 完善真实调用：创建任务 → 查询/等待状态 → 展示候选图。

### M2 认证体验（契约已完成，配置与体验持续完善）
- 登录页 / 跳转 OIDC（Authorization Code + PKCE）；
- 401 拦截与自动续期；用户信息展示。

### M3 反馈闭环（已完成基础闭环）
- 候选"选择/拒绝/理由"提交到反馈 API；
- Visual Memory 从偏好查询端点读取真实投影（来源 + 置信度可见）；
- 修改理解 → 影响下一轮生成，作为后续体验增强项持续完善。

### M4 产品化打磨（当前优先）
- Issue #73：对 Explore/Generate/Select/Feedback/Refine 工作台执行有限的 Impeccable `critique` → `audit` → `polish`；仅修改 `apps/web/**`，不改变 API 契约；
- 使用浏览器或静态验证桌面与窄屏布局、加载/错误/重试状态和可访问性；
- 官方 Impeccable CLI 若因 Apple Silicon binary 不可用，记录实际失败并采用可验证的替代审查，不声称 CLI 已运行；
- 项目/会话/历史版本管理；
- 多主题扩展预留（Persona 概念入口）。

### M5 后端可靠性与可恢复性（按依赖串行）
- Issue #70：failed generation 显式 retry，已通过 PR #71 合并；
- Issue #72：generation migration drift 修复，已通过 PR #74 合并；
- Issue #75：定义 unknown generation 的 reconciliation 边界与查询契约，先 shaping；
- Issue #76：建立 generation recovery phase 与 reconciliation 字段契约，在 #75 边界明确后推进；
- #75/#76 不与同一 generation 代码区域并行修改。

## 4. 后端配合缺口（需要 apps/api 侧新增/确认）

| 能力 | 后端现状 | 缺口 |
|---|---|---|
| 创建任务 | `POST /api/v1/tasks` ✅ | 无 |
| 任务详情 | `GET /api/v1/tasks/{id}` ✅ | 无 |
| 执行生成并落图 | `POST /api/v1/tasks/{id}/generate` ✅ | 真实 Provider 和运行环境按部署配置启用 |
| 候选图列表 | `GET /api/v1/tasks/{id}/images` ✅ | 无 |
| 反馈提交 | `POST /api/v1/tasks/{id}/feedback` ✅ | 无 |
| 偏好/记忆 | `GET /api/v1/preferences?scope=...` ✅ | 继续完善展示与策略体验 |

## 5. 原则

- 前端维护版本在 `apps/web/`；原 `/Users/adtiger/Tevion-frontend` 仅作为迁移备份；
- 每个里程碑先定 API 契约再写界面；
- 交互继续坚持"看图选择 > 写 prompt"，不引入 prompt 工程负担。
