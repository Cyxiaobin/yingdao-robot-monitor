const test = require('node:test');
const assert = require('node:assert/strict');
const { applyDelta, hasChanges } = require('../utils/diff');
const { formatBot, formatRun, safeOverview } = require('../utils/format');
const { MAX_RUNS } = require('../utils/constants');

const NOW = Date.parse('2026/11/16 15:00:00');
const TODAY_TIME = '2026-11-16 15:00:00';

function pageData() {
  return {
    overview: safeOverview({ bot_total: 2, bot_online: 2 }),
    bots: [
      formatBot({ uuid: 'b1', name: 'bot-1', status: 'running' }),
      formatBot({ uuid: 'b2', name: 'bot-2', status: 'idle' })
    ],
    runs: [formatRun({ id: 'r1', app_name: '已存在记录', status: 'success' }, NOW)]
  };
}

test('无变化帧返回空 patch', () => {
  assert.equal(hasChanges(null), false);
  assert.equal(hasChanges({}), false);
  assert.deepEqual(applyDelta(pageData(), null, NOW), {});
});

test('状态变化只生成局部路径，不整包 setData', () => {
  const delta = {
    overview: { bot_total: 2, bot_online: 2, runs_today: 2, success_rate: 100, error_count: 0 },
    bots: [{ uuid: 'b2', from: 'idle', to: 'running', bot: { uuid: 'b2', name: 'bot-2', status: 'running' } }],
    runs: [],
    ts: '2026-11-16T15:00:05'
  };
  const patch = applyDelta(pageData(), delta, NOW);
  assert.equal(patch['bots[1]'].statusLabel, '运行中');
  assert.equal(patch['bots[0]'], undefined);
  assert.equal(patch.bots, undefined);
  assert.equal(patch.overview.runs_today, 2);
  assert.equal(patch.ts, delta.ts);
});

test('新增机器人时整体替换，且不残留局部路径', () => {
  const delta = {
    bots: [{ uuid: 'b9', bot: { uuid: 'b9', name: 'bot-9', status: 'offline' } }],
    runs: []
  };
  const patch = applyDelta(pageData(), delta, NOW);
  assert.equal(patch.bots.length, 3);
  assert.equal(patch.bots[2].uuid, 'b9');
  assert.equal(Object.keys(patch).filter(k => k.indexOf('bots[') === 0).length, 0);
});

test('新运行记录插入头部并去重', () => {
  const delta = {
    runs: [
      { id: 'r2', app_name: '新记录', status: 'fail', remark: '元素未找到', create_time: TODAY_TIME },
      { id: 'r1', app_name: '重复记录', status: 'success', create_time: TODAY_TIME }
    ]
  };
  const patch = applyDelta(pageData(), delta, NOW);
  assert.equal(patch.runs.length, 2);
  assert.equal(patch.runs[0].id, 'r2');
  assert.equal(patch.runs[1].id, 'r1');
});

test('跨天增量记录不会进入当天看板', () => {
  const delta = { runs: [
    { id: 'old', app_name: '昨天的流程', status: 'success', create_time: '2026-11-15 09:00:00' },
    { id: 'new', app_name: '今天的流程', status: 'success', create_time: TODAY_TIME }
  ]};
  const patch = applyDelta(pageData(), delta, NOW);
  assert.deepEqual(patch.runs.map(r => r.id), ['new', 'r1']);
});

test('运行记录不超过 MAX_RUNS', () => {
  const many = [];
  for (let i = 0; i < 30; i++) {
    many.push({ id: 'new-' + i, app_name: '应用' + i, status: 'success',
                create_time: TODAY_TIME });
  }
  const patch = applyDelta(pageData(), { runs: many }, NOW);
  assert.equal(patch.runs.length, MAX_RUNS);
  assert.equal(patch.runs[0].id, 'new-0');
});
