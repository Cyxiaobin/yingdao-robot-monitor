# 更新记录

## 2026-11-18 — 生产安全加固

安全审查后集中修复 8 项，公网部署前必须处理的四类风险：

- **回调鉴权**：`/api/callback` 增加 `X-Callback-Token` 校验，未配 `CALLBACK_TOKEN` 时保持本地兼容
- **强制改密**：`ENFORCE_PASSWORD_CHANGE=1`（默认开）时，未改初始密码的用户只允许调用改密接口
- **写操作收紧到管理员**：运行 / 重试 / 停止 / 改凭证 / 刷新目录 5 类接口提升为 admin 专属，普通用户保留只读监控
- **密钥不进日志**：影刀 token 接口把 Secret 放在 URL query，代码层改不了，改为 `deploy/nginx.conf.example` 中日志格式只记 `$uri` 不含 `$args`
- **WS token 改走 header**：小程序端 token 从 URL query 移到 `Authorization` header；浏览器看板受原生 WebSocket 限制仍用 query，后端双通道兼容
- **`STRICT_REAL=1`**：生产环境无凭证时直接启动失败，不再静默降级成 mock 假数据
- **账号库原子写**：`users.json` 改为临时文件 + `os.replace`，进程崩溃不会写坏账号库
- **部署约束成文**：会话内存态「不可多实例」写入文档

## 2026-11-17 — 账号体系与当天数据

- **登录 + 账号管理**：新增 `pages/login/login` 作为首页；后端 PBKDF2-HMAC-SHA256 加盐哈希 + 内存会话 token；超级管理员可增删普通用户、重置密码；角色校验放在后端中间件（403 强校验），不只是前端隐藏
- **只展示当天运行**：`aggregator.filter_today()` 在服务端剔除跨天与无时间记录，小程序 `utils/today.js` 对首屏快照与 WS delta 双重兜底
- **底部导航加高**：浏览器看板与小程序同步调整 padding，解决底部 Tab 与内容区挤压

## 2026-11-17 — UI 重做与 6 项能力补齐

- **UI 重做**：深色渐变 Hero + 光晕、悬浮白卡、SVG 图标、时间轴运行列表、状态呼吸动效、毛玻璃底部导航、底部抽屉详情
- **异常流程重试**：二次确认 → `POST /api/control/retry`，先校验状态可重试，再由 `process/detail` 取 `jobUuid` 调 `job/retry`
- **失败截图**：每条失败记录可全屏看图，详情抽屉内也有缩略图
- **异常详情 + 错误日志**：状态 / 耗时 / 时间 / 编号 + 错误备注 + 错误日志列表（错误级标红）+ 截图 + 重试
- **搜索已发布流程并运行**：新增「应用」Tab，启动前校验 `appId` 真实存在且已发布
- **「关于」升级为「设置」**：后端地址、影刀 AccessKey、管理口令，保存到 `.env` 并热更新生效

**Tab 结构**：看板 / 异常 / 应用 / 设置。看板内三段互斥筛选（机器人 / 运行中 / 已完成），失败与超时统一放「异常」Tab。

## 2026-11-16 — 影刀开放 API 联调

真实环境联调通过，修正若干与初始假设不符的接口结构：

- 应用列表实际是 `POST /oapi/app/open/query/list`（不是 `dispatch/v2`），响应 `data` 为数组、分页在顶层 `page`
- 「已发布」判据为 `publishTime` 非空 + `appType == 'app'`
- 启动用 `POST /oapi/dispatch/v2/job/start`，`robotUuid` 填应用 `appId`，`accountName` 取 `client/list` 的 `robotClientName`
- 重试用 `POST /oapi/dispatch/v2/job/retry` 传 `{jobUuid}`
- `process/detail` 必须传**匹配的**机器人 uuid，否则返回空数组

详见 `docs/字段对照表.md`。
