// 仅展示当天运行：后端已按当天过滤，这里做前端兜底（旧版服务端 / 演示数据）。
// 纯函数，不依赖 wx，可被 Node 单测直接 require。

function pad(n) { return ('0' + n).slice(-2); }

function dateKey(value) {
  const d = value instanceof Date ? value : new Date(value);
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
}

function recordDate(run) {
  const raw = String((run && (run.create_time || run.start_time)) || '')
    .replace('T', ' ')
    .trim();
  return raw.slice(0, 10);
}

function filterToday(runs, now) {
  const key = dateKey(now || new Date());
  return (runs || []).filter(function (run) { return recordDate(run) === key; });
}

// formatRun 之后的展示对象用 createTime 字段
function filterFormatted(runs, now) {
  const key = dateKey(now || new Date());
  return (runs || []).filter(function (run) {
    const raw = String((run && (run.createTime || run.create_time)) || '')
      .replace('T', ' ').trim();
    return raw.slice(0, 10) === key;
  });
}

function scopeLabel(now) {
  const key = dateKey(now || new Date());
  return '仅当天 ' + key;
}

module.exports = { pad, dateKey, recordDate, filterToday, filterFormatted, scopeLabel };
