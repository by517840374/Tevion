# Tevion Web 前端

`apps/web/` 是 Tevion 的前端视觉探索工作台，当前保持零依赖静态原型。

## 当前能力
- 自然语言需求与视觉标签输入
- Agent understanding checkpoint
- Explore / Refine 模式切换
- 候选图片展示、选择、拒绝
- 真实任务创建与生成接口联调骨架
- Visual Memory 从偏好查询端点读取

## 运行
可以直接用浏览器打开 `index.html`，也可以在仓库根目录运行一个静态服务器：

```bash
python3 -m http.server 8080 --directory apps/web
```

然后访问 <http://127.0.0.1:8080/>。

当前 API 地址默认是：

```text
http://127.0.0.1:8010/api/v1
```

API client 已集中在 `app.js` 顶部，地址可配置；不要写入生产密钥。

## 迁移说明
原型来源于 `/Users/adtiger/Tevion-frontend`。外部目录仅作为迁移备份，维护版本以本目录为准。

## 后端边界
前端 Issue 只能修改 `apps/web/**`。如果需要新的后端接口，应创建或关联 `area:backend` Issue。只有明确标记为 `area:integration` 的 Issue 才能同时修改前后端。

## 当前已知缺口
- 真实 Provider 生成和 PostgreSQL 运行环境仍需按部署配置启用；静态前端本身不提供离线生成
- 真实 OIDC 登录契约已接入，生产环境仍需配置 OIDC provider；本地演示可使用 dev-token
- `verification.html` 用于无后端依赖的静态交互验收；真实 API 闭环仍需可用的后端和认证配置
