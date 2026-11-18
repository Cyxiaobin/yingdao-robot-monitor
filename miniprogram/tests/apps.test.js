const test = require('node:test');
const assert = require('node:assert/strict');
const a = require('../utils/apps');

test('formatApp 补齐展示字段并判断可运行', () => {
  const out = a.formatApp({
    appId: 'app-001', appName: '商超-退单写入', version: 7,
    ownerName: '张伟', publishTime: '2026-11-17T09:30:00', published: true
  });
  assert.equal(out.appId, 'app-001');
  assert.equal(out.version, '7');
  assert.equal(out.publishTime, '2026-11-17 09:30');
  assert.equal(out.runnable, true);
});

test('未发布 / 无 appId 的应用不可运行', () => {
  assert.equal(a.formatApp({ appId: 'x', published: false }).runnable, false);
  assert.equal(a.formatApp({ published: true }).runnable, false);
  assert.equal(a.formatApp({}).published, true); // 缺省按已发布兜底，避免后端未给字段时全不可点
  assert.equal(a.formatApp({}).runnable, false);
});

test('formatApp 空输入不崩溃', () => {
  const out = a.formatApp(null);
  assert.equal(out.appName, '未命名流程');
  assert.equal(out.version, '-');
  assert.equal(out.ownerName, '未知负责人');
  assert.deepEqual(a.formatApps(null), []);
});

test('mergeApps 按 appId 去重且保持顺序', () => {
  const first = [{ appId: 'a' }, { appId: 'b' }];
  const more = [{ appId: 'b' }, { appId: 'c' }];
  assert.deepEqual(a.mergeApps(first, more).map(x => x.appId), ['a', 'b', 'c']);
  assert.deepEqual(a.mergeApps(null, null), []);
});

test('botOptions 首项是默认，且过滤离线机器人', () => {
  const bots = [
    { name: 'A@demo', status: 'idle' },
    { name: 'B@demo', status: 'offline' },
    { name: 'C@demo', status: 'running' },
    { name: 'D@demo', status: 'disconnected' }
  ];
  assert.deepEqual(a.botOptions(bots), ['默认（影刀自动分配）', 'A@demo', 'C@demo']);
  assert.deepEqual(a.botOptions([]), ['默认（影刀自动分配）']);
});

test('accountNameOf：索引 0 为空表示影刀自动分配', () => {
  const opts = ['默认（影刀自动分配）', 'A@demo', 'C@demo'];
  assert.equal(a.accountNameOf(opts, 0), '');
  assert.equal(a.accountNameOf(opts, 1), 'A@demo');
  assert.equal(a.accountNameOf(opts, 9), '');
  assert.equal(a.accountNameOf(opts, undefined), '');
});

test('shortTime 兼容空格分隔与空值', () => {
  assert.equal(a.shortTime('2026-11-17 09:30:22'), '2026-11-17 09:30');
  assert.equal(a.shortTime(''), '');
  assert.equal(a.shortTime(null), '');
});
