// 看板三段筛选（机器人 / 运行中 / 已完成）。
// 纯函数，不依赖 wx，可被 Node 单测直接 require；WXML 不能调用函数，字段在此预处理。
// 约定：formatRun 产出的 state 为 success / fail / running / unknown。
// 失败、已停止、超时记录统一放「异常」Tab，三段里不重复展示。
const SEGMENTS = ['bots', 'running', 'done'];
const TITLES = {
  running: '运行中的流程',
  done: '已完成的流程'
};
const EMPTY_TEXT = {
  running: '当前没有运行中的流程',
  done: '暂无已完成的流程'
};

function isSegment(value) {
  return SEGMENTS.indexOf(value) >= 0;
}

function filterRuns(runs, segment) {
  const list = runs || [];
  if (segment === 'running') {
    return list.filter(function (r) { return r.state === 'running'; });
  }
  if (segment === 'done') {
    return list.filter(function (r) { return r.state === 'success'; });
  }
  return [];
}

function segmentTitle(segment) {
  return TITLES[segment] || '运行记录';
}

function emptyText(segment) {
  return EMPTY_TEXT[segment] || '暂无运行记录';
}

function countOf(runs, segment) {
  return filterRuns(runs, segment).length;
}

module.exports = {
  SEGMENTS: SEGMENTS,
  isSegment: isSegment,
  filterRuns: filterRuns,
  segmentTitle: segmentTitle,
  emptyText: emptyText,
  countOf: countOf
};
