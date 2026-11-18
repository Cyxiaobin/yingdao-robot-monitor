// 登录态 / 仅当天过滤的前端单测。
// 覆盖：token 存取与 WS 拼参、请求自动带 Authorization、401 回登录页、跨天记录被剔除。
const test = require('node:test');
const assert = require('node:assert/strict');

const C = require('../utils/constants');
const today = require('../utils/today');
const monitor = require('../services/monitor');

function installWx(override) {
  const storage = {};
  global.wx = Object.assign({
    getStorageSync(k) { return storage[k]; },
    setStorageSync(k, v) { storage[k] = v; },
    removeStorageSync(k) { delete storage[k]; },
    request(opt) { setTimeout(function () { opt.success && opt.success({ statusCode: 200, data: {} }); }, 0); },
    reLaunch() {},
    connectSocket() {
      return { onOpen() {}, onMessage() {}, onError() {}, onClose() {}, send() {}, close() {} };
    }
  }, override || {});
  return storage;
}

test('setAuth / clearAuth：token 可读写，WS 走 header 且不进 URL', () => {
  installWx();
  C.setAuth('tok-abc', { username: 'admin', role: 'admin' });
  assert.equal(C.getAuthToken(), 'tok-abc');
  assert.equal(C.getAuthUser().role, 'admin');
  assert.equal(C.getWsUrl().indexOf('token='), -1, 'WS URL 不应带 token');
  assert.equal(C.getWsHeaders().Authorization, 'Bearer tok-abc', 'token 应走 header');

  C.clearAuth();
  assert.equal(C.getAuthToken(), '');
  assert.deepEqual(C.getAuthUser(), {});
  assert.deepEqual(C.getWsHeaders(), {}, '无 token 时 header 为空');
});

test('connectSocket 使用 header 携带 token，URL 无 query', () => {
  let seen = null;
  installWx({
    connectSocket(opt) {
      seen = opt;
      return { onOpen() {}, onMessage() {}, onError() {}, onClose() {}, send() {}, close() {} };
    }
  });
  C.setAuth('ws-token', { username: 'admin', role: 'admin' });
  monitor.connect({});
  assert.ok(seen, '应发起 connectSocket');
  assert.equal(seen.header.Authorization, 'Bearer ws-token');
  assert.equal(String(seen.url).indexOf('token='), -1, 'URL 不得泄漏 token');
  C.clearAuth();
});

test('请求自动附带 Bearer token；登录接口本身不触发 401 跳转', async () => {
  let seen = null;
  installWx({
    request(opt) {
      seen = opt;
      setTimeout(function () { opt.success({ statusCode: 200, data: { success: true } }); }, 0);
    }
  });
  C.setAuth('tok-xyz', { username: 'u', role: 'user' });
  const out = await monitor.login('u', 'pwd');
  assert.equal(out.success, true);
  assert.equal(seen.header.Authorization, 'Bearer tok-xyz');
  assert.ok(String(seen.url).indexOf('/api/auth/login') > 0);
  C.clearAuth();
});

test('401 时清登录态并回登录页', async () => {
  const jumps = [];
  installWx({
    request(opt) { setTimeout(function () { opt.success({ statusCode: 401, data: {} }); }, 0); },
    reLaunch(opt) { jumps.push(opt.url); }
  });
  C.setAuth('expired', { username: 'u', role: 'user' });
  await assert.rejects(() => monitor.getSettings(), /登录已过期/);
  assert.equal(C.getAuthToken(), '', '401 后本地 token 必须清除');
  assert.deepEqual(jumps, ['/pages/login/login']);
});

test('filterToday / filterFormatted 只保留当天，剔除昨天与无时间脏数据', () => {
  const now = new Date('2026/11/17 18:00:00');
  const raw = [
    { id: 'a', create_time: '2026-11-17 09:00:00' },
    { id: 'c', create_time: '2026-11-16 23:59:59' },
    { id: 'd' }
  ];
  const formatted = [
    { id: 'a', createTime: '2026-11-17 09:00:00' },
    { id: 'b', createTime: '2026-11-17T16:30:00' },
    { id: 'c', createTime: '2026-11-16 23:59:59' },
    { id: 'd' }
  ];
  assert.deepEqual(today.filterToday(raw, now).map(r => r.id), ['a']);
  assert.deepEqual(today.filterFormatted(formatted, now).map(r => r.id), ['a', 'b']);
  assert.equal(today.scopeLabel(now), '仅当天 2026-11-17');
  assert.equal(today.recordDate({ create_time: '2026-11-17T08:00:00' }), '2026-11-17');
});

test('formatSnapshot 对首屏响应也做当天兜底', () => {
  const { formatSnapshot } = require('../utils/format');
  const now = Date.parse('2026/11/17 18:00:00');
  const snap = formatSnapshot({
    ts: '2026-11-17T18:00:00',
    overview: { bot_total: 1, bot_online: 1, runs_today: 1, success_rate: 100, error_count: 0 },
    bots: [{ uuid: 'b1', name: 'A', status: 'idle' }],
    runs: [
      { id: 'today', app_name: '当天流程', status: 'finish', create_time: '2026-11-17 08:00:00' },
      { id: 'old', app_name: '昨天流程', status: 'error', create_time: '2026-11-16 08:00:00' }
    ]
  }, now);
  assert.deepEqual(snap.runs.map(r => r.id), ['today']);
  assert.equal(snap.bots.length, 1);
});
