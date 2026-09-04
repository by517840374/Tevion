# Tevion Web 前端

`apps/web/` 是 Tevion 的前端视觉探索工作台，当前保持零依赖静态原型。

## 当前能力

- 自然语言需求与视觉标签输入
- Agent understanding checkpoint
- Explore / Refine 模式切换
- 候选图片展示与选择
- 演示登录和 Bearer token 调用
- 真实任务创建与生成接口联调骨架
- Visual Memory 展示占位

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

API client 已集中在 `app.js` 顶部，后续应改为可配置值，不要写入生产密钥。

## 迁移说明

原型来源于 `/Users/adtiger/Tevion-frontend`。外部目录仅作为迁移备份，维护版本以本目录为准。

## 后端边界

前端 Issue 只能修改 `apps/web/**`。如果需要新的后端接口，应创建或关联 `area:backend` Issue。只有明确标记为 `area:integration` 的 Issue 才能同时修改前后端。

## 当前已知缺口

- 反馈提交 API 尚未接入
- Visual Memory 仍是展示占位
- 真实 OIDC 登录尚未接入，目前使用 dev-token
- `verification.html` 仍需继续完善为无后端依赖的浏览器验收页
