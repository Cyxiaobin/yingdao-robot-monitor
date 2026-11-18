## 这个 PR 做了什么

<!-- 一句话说清。关联的 issue 用 #123 引用 -->

## 改动范围

- [ ] 后端
- [ ] 小程序
- [ ] 浏览器看板
- [ ] 部署配置 / 文档

## 验证方式

<!-- 说明你怎么确认改动是有效的，贴测试结果或截图 -->

```bash
cd backend && python -m pytest
node --test miniprogram/tests/*.test.js
node miniprogram/tests/static-check.js
```

## 自查

- [ ] 跑完后端与小程序测试，全部通过
- [ ] 没有提交 `.env`、`users.json` 或任何真实密钥
- [ ] 新增的界面文案与日志里没有内部 IP、真实业务名称
- [ ] 涉及写操作（启动 / 停止 / 重试）的改动，已确认二次确认弹窗仍然生效
