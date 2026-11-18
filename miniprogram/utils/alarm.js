// 报警列表纯逻辑：不依赖 wx，可被 Node 直接 require 做单元测试。
// 入参是 formatSnapshot 处理后的 runs（已带 state / stateLabel / botUuid 等展示字段）。

function buildAlarms(runs, handled) {
  const map = handled || {};
  return (runs || [])
    .filter(function (r) { return r && r.state === 'fail' && !map[r.id]; })
    .map(function (r) {
      return {
        id: r.id || '',
        appName: r.appName || '未命名应用',
        status: r.status || '',
        stateLabel: r.stateLabel || '异常',
        stateColor: r.stateColor || '#e24b4a',
        reason: r.remark || (r.status === 'stopped' ? '任务已停止' : '运行异常'),
        timeText: r.durationText || '',
        botUuid: r.botUuid || '',
        hasScreenshot: Boolean(r.hasScreenshot),
        screenshotUrl: r.screenshotUrl || ''
      };
    });
}

function countUnhandled(runs, handled) {
  return buildAlarms(runs, handled).length;
}

function markHandled(handled, id, value) {
  const next = Object.assign({}, handled || {});
  if (id) next[id] = value || 'done';
  return next;
}

module.exports = { buildAlarms, countUnhandled, markHandled };
