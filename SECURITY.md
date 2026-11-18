# 安全策略

## 报告问题

发现安全问题时不要开公开 issue。请通过 GitHub 的
[私密漏洞报告](https://github.com/Cyxiaobin/yingdao-robot-monitor/security/advisories/new)
提交，或者在 issue 里只描述影响范围、约我私下沟通细节。

请附上：

- 受影响的版本或提交号
- 复现方式
- 你认为的影响面（能读到别人的数据、能触发写操作、能拿到密钥……）

## 部署方需要知道的

这个项目默认按「企业内部工具」设计，直接暴露到公网前请确认下面几条：

1. `SUPER_ADMIN_PASSWORD` 必须改掉默认的 `admin123`，并且保持 `ENFORCE_PASSWORD_CHANGE=1`
2. `CALLBACK_TOKEN` 必配，否则 `/api/callback` 任何人都能 POST
3. `ADMIN_TOKEN` 建议配置，否则改影刀凭证只靠登录态把关
4. `STRICT_REAL=1` 必配，避免密钥失效时静默返回假数据而没人发现
5. Nginx 日志必须排除 query string。影刀 token 接口把 Secret 放在 URL 里，默认日志格式会把它完整写进 access.log
6. `.env` 权限设 600，不要给它建软链到 web 目录

## 不在范围内

- 影刀开放 API 自身的漏洞，请找影刀官方
- 使用者自己把密钥提交进 git 导致的问题
- 已经按上面六条配置好、但仍然要求「免登录对外网开放」的场景
