const test = require('node:test');
const assert = require('node:assert/strict');
const f = require('../utils/format');

test('formatDuration 覆盖秒 / 分 / 小时', () => {
  assert.equal(f.formatDuration(0), '0s');
  assert.equal(f.formatDuration(45), '45s');
  assert.equal(f.formatDuration(60), '1m');
  assert.equal(f.formatDuration(135), '2m15s');
  assert.equal(f.formatDuration(3720), '1h2m');
});

test('parseTime 兼容影刀格式与 ISO 格式', () => {
  const a = f.parseTime('2026-11-16 15:00:00');
  const b = f.parseTime('2026-11-16T15:00:00');
  assert.equal(a, b);
  assert.equal(f.parseTime(''), null);
  assert.equal(f.parseTime('not-a-time'), null);
});

test('relativeTime 注入 now 得到稳定结果', () => {
  const now = f.parseTime('2026-11-16 15:00:00');
  assert.equal(f.relativeTime('2026-11-16 15:00:00', now), '刚刚');
  assert.equal(f.relativeTime('2026-11-16 14:57:00', now), '3分钟前');
  assert.equal(f.relativeTime('2026-11-16 13:00:00', now), '2小时前');
  assert.equal(f.relativeTime('2026-11-14 15:00:00', now), '2天前');
});

test('未知状态枚举兜底不崩溃', () => {
  assert.equal(f.botStatusOf('brand_new_enum').label, '未知');
  assert.equal(f.runStatusOf('brand_new_enum').state, 'unknown');
  assert.equal(f.botStatusOf('running').label, '运行中');
  assert.equal(f.runStatusOf('timeout').state, 'fail');
});

test('formatBot 产出 WXML 可直接绑定的字段', () => {
  const bot = f.formatBot({
    uuid: 'b1', name: 'admin@ydsc', ip: '10.0.0.79',
    status: 'running', current_app: '抖音电商罗盘抓取'
  });
  assert.equal(bot.statusLabel, '运行中');
  assert.equal(bot.currentApp, '抖音电商罗盘抓取');
  assert.ok(bot.statusColor.startsWith('#'));
  assert.ok(bot.statusBg.startsWith('#'));
});

test('formatRun 失败记录带截图入口与耗时', () => {
  const now = f.parseTime('2026-11-16 15:00:00');
  const run = f.formatRun({
    id: 'r1', app_name: '退单写入', status: 'fail',
    duration_sec: 135, create_time: '2026-11-16 14:57:00',
    remark: '元素未找到', screenshot_url: 'https://example.com/shot.png'
  }, now);
  assert.equal(run.state, 'fail');
  assert.equal(run.stateLabel, '失败');
  assert.equal(run.durationText, '2m15s · 3分钟前');
  assert.equal(run.hasScreenshot, true);
  assert.equal(run.screenshotUrl, 'https://example.com/shot.png');
});

test('真实枚举 finish / stopped 与失败详情入口', () => {
  assert.equal(f.runStatusOf('finish').state, 'success');
  assert.equal(f.runStatusOf('stopped').label, '已停止');
  assert.equal(f.runStatusOf('error').state, 'fail');
  const run = f.formatRun({
    id: 't2', app_name: '鲜活GO报数', status: 'error',
    bot_uuid: 'c2', remark: '运行异常'
  }, f.parseTime('2026-11-16 15:00:00'));
  assert.equal(run.state, 'fail');
  assert.equal(run.botUuid, 'c2');
  assert.equal(run.screenshotUrl, '');
  assert.equal(run.hasScreenshot, true); // 列表无截图，但可点开拉详情
});

test('formatSnapshot 完整转换并补默认值，跨天记录不进看板', () => {
  const now = f.parseTime('2026-11-16 15:00:00');
  const snapshot = {
    ts: '2026-11-16T15:00:00',
    overview: { bot_total: 4, bot_online: 3, runs_today: 4, success_rate: 50, error_count: 2 },
    bots: [{ uuid: 'b1', name: 'admin@ydsc', ip: '10.0.0.79', status: 'running' }],
    runs: [
      { id: 'r1', app_name: '抖音电商罗盘抓取', status: 'success',
        create_time: '2026-11-16 14:58:00', duration_sec: 120 },
      { id: 'r2', app_name: '昨天的流程', status: 'error',
        create_time: '2026-11-15 14:58:00', duration_sec: 30 }
    ]
  };
  const out = f.formatSnapshot(snapshot, now);
  assert.equal(out.overview.success_rate, 50);
  assert.equal(out.bots.length, 1);
  assert.equal(out.runs.length, 1, '仅当天兜底过滤');
  assert.equal(out.runs[0].id, 'r1');
  assert.ok(out.runs[0].durationText.indexOf('2m') === 0);
  assert.deepEqual(f.formatSnapshot(null).overview, f.safeOverview({}));
});

test('safeOverview 缺字段补零', () => {
  assert.deepEqual(f.safeOverview({ runs_today: 3 }), {
    bot_total: 0, bot_online: 0, runs_today: 3, success_rate: 0, error_count: 0
  });
  assert.equal(f.safeOverview({ success_rate: '95' }).success_rate, 95);
});
