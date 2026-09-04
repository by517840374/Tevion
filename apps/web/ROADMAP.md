# Tevion 前端产品化路线（Frontend Roadmap）

> 状态：草案 · 位置：仓库内 `apps/web/`（ADR-008）· 语言：中文
> 关联后端：`apps/api`（FastAPI，真实 PG + 认证 + GPT-image2 已通）

## 1. 现状

`apps/web` 是从迁移备份恢复的零依赖静态原型（index.html / styles.css / app.js），已验证核心交互：
Explore/Refine 模式、视觉标签、理解确认节点、候选选择、Visual Memory 展示。
当前主流程已接入真实 API：任务创建、候选生成、反馈提交和 Visual Memory 偏好读取已在 `origin/main` 实现；Issue #24、#28、#29、#30 对应实现已合并。后续路线聚焦认证配置、失败恢复、历史版本管理和产品化打磨。

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

### M4 产品化打磨
- 项目/会话/历史版本管理；
- 视觉规范统一（暗色编辑器风格）；
- 多主题扩展预留（Persona 概念入口）。

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
