const test = require('node:test');
const assert = require('node:assert/strict');
const { formatLogs, logsNotice } = require('../utils/logs');

test('真实日志字段 text / 中文 level 正确映射', () => {
  const out = formatLogs([
    { time: '11/16/2026 17:00:11', level: '信息', text: '开始执行...', logId: 1 },
    { time: '11/16/2026 17:01:14', level: '错误', text: '无效的截图区域', logId: 2 }
  ]);
  assert.equal(out[0].content, '开始执行...');
  assert.equal(out[0].isError, false);
  assert.equal(out[1].isError, true);
  assert.equal(out[1].logId, 2);
});

test('兼容旧 MOCK 字段 content / ERROR，缺 logId 时用下标兜底', () => {
  const out = formatLogs([{ time: 't', level: 'ERROR', content: '元素未找到' }]);
  assert.equal(out[0].content, '元素未找到');
  assert.equal(out[0].isError, true);
  assert.equal(out[0].logId, 0);
});

test('空输入不崩溃', () => {
  assert.deepEqual(formatLogs(null), []);
  assert.deepEqual(formatLogs([]), []);
});

test('机器人离线时给出降级提示，有日志时不打扰', () => {
  assert.equal(logsNotice([], '原因：机器人未连接，无法查询日志'),
    '日志暂不可用：原因：机器人未连接，无法查询日志');
  assert.equal(logsNotice([{ content: 'ok' }], '机器人未连接'), '');
  assert.equal(logsNotice([], ''), '');
  assert.equal(logsNotice(null, 'X'.repeat(200)).length <= 70, true);
});
