# 参与开发

## 本地环境

```bash
git clone https://github.com/Cyxiaobin/yingdao-robot-monitor.git
cd yingdao-robot-monitor/backend
pip install -r requirements.txt
cp .env.example .env
```

没有影刀凭证也能开发，`.env` 里设 `YINGDAO_MOCK=1` 就会用内置 mock 数据跑。

## 改完先跑测试

```bash
cd backend && python -m pytest
node --test miniprogram/tests/*.test.js
node miniprogram/tests/static-check.js
```

三组都过再提 PR。CI 也会跑同样的命令，提交前自己跑一遍能省一轮往返。

## 代码约定

**后端**

- 配置一律走 `app/config.py` 的 `Settings`，不要在业务代码里直接读 `os.getenv`
- 新增接口要在 `main.py` 的鉴权中间件里判断清楚：普通用户能不能调。默认是「能」，所以写操作必须显式加上管理员限制
- 返回给前端的数据一律脱敏。Secret 不回显、不进日志、不进 WS 推送
- 测试放 `backend/tests/`，命名 `test_*.py`，用 `conftest.py` 里的 fixture

**小程序**

- 页面逻辑要和浏览器看板保持一致，两端共用同一套接口
- 新增的 `bindtap` / `bindinput` 方法必须在同名 `.js` 里定义，`static-check.js` 会拦
- 不要在 `miniprogram/` 下出现任何密钥值，哪怕是测试用

**文案**

- 界面和示例数据里不要出现真实公司名、真实业务系统名、真实人名
- 演示数据统一用 `RPABOT01@demo` 这类占位账号，IP 用 `10.0.0.x` / `192.168.1.x`

## 提交信息

```
类型: 简述

- 具体改了什么
- 为什么这么改
```

类型用 `feat` / `fix` / `refactor` / `docs` / `chore`。中英文都行，一条提交只做一件事。

## 提交 PR

- 说明改动范围和验证方式，模板会自动带出来
- 涉及界面的改动请附截图
- 涉及写操作（启动 / 停止 / 重试）的改动，说明是否影响二次确认逻辑

## 不要提交的东西

`.env`、`backend/data/users.json`、`project.private.config.json` 都已经写进 `.gitignore`。
如果你本地改过 `.gitignore`，提交前用 `git status` 再确认一遍，别把密钥带上去。
