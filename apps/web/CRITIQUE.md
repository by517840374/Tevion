# Issue #73 前端 critique / audit 记录

> 评审基线：`origin/main`（`db50d816d15fca7588badf57007781a0ae5e9d46`）。范围严格限定 `apps/web/**`。

## Impeccable CLI

本机未发现 `impeccable` 可执行文件（`command -v impeccable` 无输出），因此未声称运行官方 CLI；以下为基于产品文档、源码和可执行静态/浏览器验证的替代评审。

## Critique：信息层级与主次操作

- 工作台的生成入口、状态和候选图视觉重点方向正确，但表单字段缺少一致的辅助说明与键盘状态表达。
- 候选卡片将“选择”和“拒绝”并列，主操作不够突出；通过主次按钮样式、明确的 aria 文案和反馈状态强化选择路径，不改变 API 行为。
- 顶部状态、理解区和结果区需要使用语义化 live region，避免异步状态只靠颜色或视觉 toast 传达。
- 空态、加载态、错误态已有基础实现；补充可恢复性提示、状态角色和更清晰的 loading 进度表达。

## Audit：响应式、可访问性、状态和性能

- 窄屏时右侧记忆区隐藏，工作台仍需让左侧输入和中间候选保持可用；补充单列布局、紧凑间距和横向可滚动模式控件。
- 交互控件需有可见 focus-visible 样式；装饰性 status dot 不应成为状态的唯一表达。
- 图片已有 lazy loading 与失败提示；补充图片容器的可访问名称，并确保 loading/error/retry 状态不会造成重复提交。
- 历史面板已有失败文字但缺少显式 retry；本轮只加强前端状态提示，不新增 endpoint 或 API 契约。

## 有边界的 polish

1. 仅修改 `apps/web/index.html`、`apps/web/app.js`、`apps/web/styles.css`、`apps/web/interactive.css` 与本评审记录。
2. 不改变 API path、method、body 或响应 shape；不添加生产依赖。
3. 保持深色工作台与候选图片为视觉重点，改善 hierarchy、focus、窄屏布局、异步状态与恢复提示。
4. `verification.html` 增加针对本轮行为的静态契约检查；先运行 RED，再实现并运行 GREEN。

## 非目标 / 未验证

- 未修改 `apps/api/**`、CI 或后端契约。
- 未使用真实 Provider 生成、真实 OIDC 或私有图片；这些需要部署环境和凭据，不能由静态验证替代。
- 浏览器验证使用本地静态服务器，不代表真实 API 闭环成功。

## 验收记录

- [x] RED：新增验证断言在实现前失败（记录于实现前评审阶段）
- [x] GREEN：静态验证页通过
- [x] `node --check apps/web/app.js`
- [x] 桌面浏览器实际打开并检查布局；窄屏适配通过 CSS/静态契约检查
- [x] diff 仅包含 `apps/web/**`（提交前审计）
