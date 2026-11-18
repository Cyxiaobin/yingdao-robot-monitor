const test = require('node:test');
const assert = require('node:assert/strict');
const s = require('../utils/segments');

const runs = [
  { id: 'r1', state: 'running', status: 'running' },
  { id: 'r2', state: 'success', status: 'finish' },
  { id: 'r3', state: 'fail', status: 'error' },
  { id: 'r4', state: 'fail', status: 'stopped' },
  { id: 'r5', state: 'success', status: 'finish' },
  { id: 'r6', state: 'unknown', status: 'new_enum' }
];

test('isSegment 只认三个合法标签', () => {
  assert.equal(s.isSegment('bots'), true);
  assert.equal(s.isSegment('running'), true);
  assert.equal(s.isSegment('done'), true);
  assert.equal(s.isSegment('all'), false);
  assert.equal(s.isSegment('fail'), false);
  assert.equal(s.isSegment(''), false);
});

test('机器人标签不返回任何运行记录（互斥展示）', () => {
  assert.deepEqual(s.filterRuns(runs, 'bots'), []);
  assert.equal(s.countOf(runs, 'bots'), 0);
});

test('运行中只取 running，已完成只取 success', () => {
  assert.deepEqual(s.filterRuns(runs, 'running').map(r => r.id), ['r1']);
  assert.deepEqual(s.filterRuns(runs, 'done').map(r => r.id), ['r2', 'r5']);
});

test('失败/已停止/未知状态不混进已完成（异常 Tab 专属）', () => {
  const ids = s.filterRuns(runs, 'done').map(r => r.id);
  ['r3', 'r4', 'r6'].forEach(id => assert.equal(ids.indexOf(id), -1));
});

test('标题与空态文案随标签变化', () => {
  assert.equal(s.segmentTitle('running'), '运行中的流程');
  assert.equal(s.segmentTitle('done'), '已完成的流程');
  assert.equal(s.segmentTitle('bots'), '运行记录');
  assert.match(s.emptyText('running'), /没有运行中/);
  assert.match(s.emptyText('done'), /暂无已完成/);
});

test('空输入与未知标签不崩溃', () => {
  assert.deepEqual(s.filterRuns(null, 'done'), []);
  assert.deepEqual(s.filterRuns(undefined, 'running'), []);
  assert.deepEqual(s.filterRuns(runs, 'nope'), []);
});
