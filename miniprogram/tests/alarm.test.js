const test = require('node:test');
const assert = require('node:assert/strict');
const { buildAlarms, countUnhandled, markHandled } = require('../utils/alarm');

const runs = [
  { id: 't1', appName: '鲜活GO报数', state: 'fail', status: 'error',
    stateLabel: '失败', stateColor: '#e24b4a', remark: '运行异常',
    durationText: '1m14s · 3分钟前', botUuid: 'bot-1',
    hasScreenshot: true, screenshotUrl: '' },
  { id: 't2', appName: '商超订单同步', state: 'success', status: 'finish',
    stateLabel: '成功', stateColor: '#1d9e75', remark: '结束任务',
    durationText: '1m36s', botUuid: 'bot-2', hasScreenshot: false },
  { id: 't3', appName: '天香保百', state: 'fail', status: 'stopped',
    stateLabel: '已停止', stateColor: '#d97706', remark: '',
    durationText: '3m', botUuid: 'bot-3', hasScreenshot: false },
  { id: 't4', appName: '银企直连', state: 'running', status: 'running',
    stateLabel: '运行中', stateColor: '#378add', remark: '', botUuid: 'bot-4' }
];

test('只保留失败记录并补齐展示字段', () => {
  const out = buildAlarms(runs, {});
  assert.equal(out.length, 2);
  assert.equal(out[0].appName, '鲜活GO报数');
  assert.equal(out[0].reason, '运行异常');
  assert.equal(out[0].botUuid, 'bot-1');
  assert.equal(out[1].reason, '任务已停止'); // stopped 且无 remark 时的兜底文案
  assert.equal(countUnhandled(runs, {}), 2);
});

test('已处理 / 忽略的记录不再出现', () => {
  const handled = markHandled({}, 't1', 'done');
  const both = markHandled(handled, 't3', 'ignored');
  assert.equal(buildAlarms(runs, both).length, 0);
  assert.equal(countUnhandled(runs, both), 0);
});

test('markHandled 不修改原对象', () => {
  const original = { t1: 'done' };
  const next = markHandled(original, 't2', 'ignored');
  assert.deepEqual(original, { t1: 'done' });
  assert.deepEqual(next, { t1: 'done', t2: 'ignored' });
});

test('空输入不崩溃', () => {
  assert.deepEqual(buildAlarms(null, null), []);
  assert.equal(countUnhandled([], {}), 0);
});
