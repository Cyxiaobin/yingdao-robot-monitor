// 运行时冒烟：用最小 wx 模拟环境真正执行 dashboard 页面逻辑。
// 目的不是替代微信开发者工具，而是提前抓出 undefined 引用、字段拼写、条件链运行时错误。
const test = require('node:test');
const assert = require('node:assert/strict');

// 运行记录只在当天展示：测试数据按「执行测试的当天」生成，避免日期漂移导致失败
const TODAY = (function () {
  const d = new Date();
  const p = function (n) { return ('0' + n).slice(-2); };
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
})();
function at(time) { return TODAY + ' ' + time; }
function yesterday(time) {
  const d = new Date(TODAY + 'T00:00:00');
  d.setDate(d.getDate() - 1);
  const p = function (n) { return ('0' + n).slice(-2); };
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + time;
}

const SNAPSHOT = {
  ts: TODAY + 'T16:30:00',
  overview: { bot_total: 3, bot_online: 2, runs_today: 5, success_rate: 80, error_count: 1 },
  bots: [
    { uuid: 'b1', name: 'A@demo', ip: '10.0.8.6', status: 'running' },
    { uuid: 'b2', name: 'B@demo', ip: '10.0.8.7', status: 'idle' },
    { uuid: 'b3', name: 'C@demo', ip: '10.0.8.8', status: 'offline' }
  ],
  runs: [
    { id: 'r1', app_name: '流程甲', status: 'running', create_time: at('16:29:00'), duration_sec: 60, bot_uuid: 'b1' },
    { id: 'r2', app_name: '流程乙', status: 'finish', create_time: at('16:20:00'), duration_sec: 90, bot_uuid: 'b2' },
    { id: 'r3', app_name: '流程丙', status: 'error', create_time: at('16:10:00'), duration_sec: 30, remark: '元素未找到', bot_uuid: 'b2' },
    { id: 'r4', app_name: '流程丁', status: 'finish', create_time: at('16:00:00'), duration_sec: 45, bot_uuid: 'b1' },
    // 跨天记录：后端已过滤，这里验证前端兜底也不会把它放进看板
    { id: 'r5', app_name: '昨天的流程', status: 'finish', create_time: yesterday('23:50:00'), duration_sec: 10, bot_uuid: 'b1' }
  ]
};

const SETTINGS = {
  baseUrl: 'https://api.yingdao.com', mockMode: false, hasCredentials: true,
  accessKeyIdMasked: 'Rcr***form', adminTokenRequired: false,
  allowRemoteControl: true, pollInterval: 5, authEnabled: true, onlyToday: true, date: TODAY
};

const USERS = {
  success: true, total: 2, users: [
    { username: 'admin', role: 'admin', builtin: true, createdAt: TODAY + 'T08:00:00' },
    { username: 'zhangsan', role: 'user', builtin: false, createdAt: TODAY + 'T09:00:00' }
  ]
};

const APPS = {
  keyword: '', total: 2, page: 1, size: 20,
  apps: [
    { appId: 'a1', appName: '商超-退单写入', version: '7', ownerName: '张伟', publishTime: TODAY + 'T09:30:00', published: true },
    { appId: 'a2', appName: '应收三表匹配', version: '12', ownerName: '财务共享', publishTime: yesterday('08:00:00'), published: true }
  ]
};

function installWxMock() {
  const storage = {};
  const jumps = [];
  global.wx = {
    getStorageSync(k) { return storage[k]; },
    setStorageSync(k, v) { storage[k] = v; },
    removeStorageSync(k) { delete storage[k]; },
    jumps: jumps,
    request(opt) {
      const url = String(opt.url || '');
      let body = {};
      if (url.indexOf('/api/auth/me') >= 0) {
        body = { authEnabled: true, authenticated: true, username: 'admin', role: 'admin' };
      } else if (url.indexOf('/api/auth/users') >= 0) {
        body = USERS;
      } else if (url.indexOf('/api/auth/') >= 0) {
        body = { success: true, msg: 'ok' };
      } else if (url.indexOf('/api/snapshot') >= 0) body = { data: SNAPSHOT };
      else if (url.indexOf('/api/settings') >= 0 && url.indexOf('/test') < 0 && url.indexOf('/credentials') < 0) body = SETTINGS;
      else if (url.indexOf('/api/apps/search') >= 0) body = APPS;
      else if (url.indexOf('/api/apps/refresh') >= 0) body = { success: true, published: 2 };
      else if (url.indexOf('/health') >= 0) body = { status: 'ok', mock_mode: false };
      else if (url.indexOf('/logs') >= 0) body = { logs: [] };
      else if (url.indexOf('/detail') >= 0) body = { jobs: [{ remark: '元素未找到', screenshotUrl: '' }] };
      else body = { success: true };
      setTimeout(function () { opt.success && opt.success({ statusCode: 200, data: body }); }, 0);
    },
    connectSocket() {
      return {
        onOpen() {}, onMessage() {}, onError() {}, onClose() {},
        send() {}, close() {}
      };
    },
    reLaunch(opt) { jumps.push(opt.url); },
    showToast() {}, showLoading() {}, hideLoading() {}, stopPullDownRefresh() {},
    showModal(opt) { if (opt.success) opt.success({ confirm: false }); },
    navigateTo() {}, previewImage() {}
  };
}

function loadPage() {
  let config = null;
  global.Page = function (cfg) { config = cfg; };
  const file = require.resolve('../pages/dashboard/dashboard.js');
  delete require.cache[file];
  require(file);
  assert.ok(config, 'dashboard.js 未调用 Page()');
  const page = Object.assign({}, config, {
    data: JSON.parse(JSON.stringify(config.data)),
    setData(patch, cb) {
      Object.assign(this.data, patch);
      if (cb) cb.call(this);
    }
  });
  return page;
}

async function tick(n) {
  for (let i = 0; i < (n || 3); i += 1) {
    await new Promise(function (r) { setTimeout(r, 0); });
  }
}

test('onLoad 拉全量后：概览/机器人/三段筛选字段齐全', async () => {
  installWxMock();
  const page = loadPage();
  page.onLoad();
  await tick(6);
  assert.equal(page.data.overview.bot_total, 3);
  assert.equal(page.data.bots.length, 3);
  assert.equal(page.data.shownBots.length, 3);
  assert.equal(page.data.shownBots[0].initials, 'AD');
  assert.equal(page.data.botOptions.length, 3); // 默认 + 2 台非离线
  assert.equal(page.data.shownRuns.length, 0);  // 默认机器人标签互斥
  assert.equal(page.data.runs.length, 4);       // 昨天的 r5 被「仅当天」兜底剔除
  assert.equal(page.data.settingsLoaded, true);
  assert.equal(page.data.allowControl, true);
  assert.equal(page.data.connected, false); // ws 模拟未触发 onOpen
  page.onUnload();
});

test('三段筛选互斥：运行中 1 条 / 已完成 2 条 / 机器人 0 条', async () => {
  installWxMock();
  const page = loadPage();
  page.onLoad();
  await tick(6);

  page.onSegmentTap({ currentTarget: { dataset: { segment: 'running' } } });
  assert.equal(page.data.segmentTitle, '运行中的流程');
  assert.deepEqual(page.data.shownRuns.map(r => r.id), ['r1']);

  page.onSegmentTap({ currentTarget: { dataset: { segment: 'done' } } });
  assert.equal(page.data.segmentTitle, '已完成的流程');
  assert.deepEqual(page.data.shownRuns.map(r => r.id), ['r2', 'r4']);

  page.onSegmentTap({ currentTarget: { dataset: { segment: 'bots' } } });
  assert.equal(page.data.shownRuns.length, 0);
  assert.equal(page.data.shownBots.length, 3);

  // 非法标签不改变状态
  page.onSegmentTap({ currentTarget: { dataset: { segment: 'nope' } } });
  assert.equal(page.data.segment, 'bots');
  page.onUnload();
});

test('4 Tab 切换：异常有 1 条，应用页自动拉到 2 个已发布流程', async () => {
  installWxMock();
  const page = loadPage();
  page.onLoad();
  await tick(6);

  assert.equal(page.data.alarms.length, 1);
  assert.equal(page.data.alarmCount, 1);

  page.onTabTap({ currentTarget: { dataset: { tab: 'apps' } } });
  await tick(6);
  assert.equal(page.data.activeTab, 'apps');
  assert.equal(page.data.apps.length, 2);
  assert.equal(page.data.appTotal, 2);
  assert.equal(page.data.apps[0].publishTime, TODAY + ' 09:30');

  page.onTabTap({ currentTarget: { dataset: { tab: 'settings' } } });
  assert.equal(page.data.activeTab, 'settings');
  page.onUnload();
});

test('详情抽屉：并行拉详情与日志，失败记录可重试', async () => {
  installWxMock();
  const page = loadPage();
  page.onLoad();
  await tick(6);

  page.onDrawerTap({ currentTarget: { dataset: { id: 'r3', bot: 'b2', mode: 'detail' } } });
  await tick(6);
  assert.equal(page.data.drawerShow, true);
  assert.equal(page.data.drawerRun.appName, '流程丙');
  assert.equal(page.data.drawerRemark, '元素未找到');
  assert.equal(page.data.drawerCanRetry, true);
  assert.equal(page.data.drawerLoading, false);

  page.onCloseDrawer();
  assert.equal(page.data.drawerShow, false);
  page.onUnload();
});

test('标记异常已处理后，未处理数归零', async () => {
  installWxMock();
  const page = loadPage();
  page.onLoad();
  await tick(6);
  page.onMarkAlarm({ currentTarget: { dataset: { id: 'r3' } } });
  assert.equal(page.data.alarmCount, 0);
  assert.equal(page.data.handledCount, 1);
  page.onUnload();
});

test('登录态：管理员身份加载账号列表，普通用户角色不在此页出现管理区块', async () => {
  installWxMock();
  const page = loadPage();
  page.onLoad();
  await tick(6);
  assert.equal(page.data.currentUser, 'admin');
  assert.equal(page.data.currentRole, '超级管理员');
  assert.equal(page.data.isAdmin, true);
  assert.equal(page.data.userCount, 2);
  assert.equal(page.data.users[1].roleText, '普通用户');
  assert.equal(page.data.users[1].firstLetter, 'Z');
  assert.equal(page.data.users[1].createdText, TODAY + ' 09:00');
  assert.equal(page.data.scopeLabel, '仅当天 ' + TODAY);
  page.onUnload();
});

test('账号管理：创建普通用户 / 二次确认后删除 / 退出登录回登录页', async () => {
  installWxMock();
  const page = loadPage();
  page.onLoad();
  await tick(6);

  page.onNewUserInput({ detail: { value: 'lisi' } });
  page.onNewUserPwd({ detail: { value: '123456' } });
  await page.onAddUser();
  await tick(4);
  assert.ok(page.data.accountMsg.indexOf('已创建') >= 0);
  assert.equal(page.data.newUserInput, '');
  assert.equal(page.data.newUserPwd, '');

  global.wx.showModal = function (opt) { if (opt.success) opt.success({ confirm: true }); };
  page.onDeleteUser({ currentTarget: { dataset: { user: 'zhangsan' } } });
  await tick(6);
  assert.ok(page.data.accountMsg.length > 0);

  await page.onLogout();
  await tick(4);
  assert.deepEqual(global.wx.jumps, ['/pages/login/login']);
  page.onUnload();
});

test('修改密码：少于 6 位被拦下，成功后清空输入并回登录页', async () => {
  installWxMock();
  const page = loadPage();
  page.onLoad();
  await tick(6);

  page.onOldPwdInput({ detail: { value: 'oldpwd' } });
  page.onNewPwdInput({ detail: { value: '123' } });
  await page.onChangePassword();
  assert.equal(global.wx.jumps.length, 0, '弱密码不应发起改密');

  page.onNewPwdInput({ detail: { value: 'newpwd123' } });
  await page.onChangePassword();
  await tick(4);
  assert.equal(page.data.newPwdInput, '');
  assert.deepEqual(global.wx.jumps, ['/pages/login/login']);
  page.onUnload();
});
