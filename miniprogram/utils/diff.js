// 增量应用：把后端 delta 帧转成 setData 的局部更新路径（E-02：不整包 setData）。
const { formatBot, formatRun, safeOverview } = require('./format');
const { MAX_RUNS } = require('./constants');
const { filterFormatted } = require('./today');

function hasChanges(delta) {
  if (!delta) return false;
  return Boolean(
    (delta.bots && delta.bots.length) ||
    (delta.runs && delta.runs.length) ||
    delta.overview
  );
}

function applyDelta(pageData, delta, now) {
  if (!hasChanges(delta)) return {};

  const patch = {};
  if (delta.overview) patch.overview = safeOverview(delta.overview);
  if (delta.ts) patch.ts = delta.ts;

  const bots = (pageData.bots || []).slice();
  let appended = false;
  (delta.bots || []).forEach(function (change) {
    const formatted = formatBot(change.bot);
    const idx = bots.findIndex(function (b) { return b.uuid === change.uuid; });
    if (idx >= 0) {
      patch['bots[' + idx + ']'] = formatted;
      bots[idx] = formatted;
    } else {
      bots.push(formatted);
      appended = true;
    }
  });
  if (appended) {
    // 整体替换与局部路径不能同时出现在一次 setData 里，优先整体
    Object.keys(patch).forEach(function (key) {
      if (key.indexOf('bots[') === 0) delete patch[key];
    });
    patch.bots = bots;
  }

  const seen = {};
  (pageData.runs || []).forEach(function (r) { seen[r.id] = true; });
  const fresh = filterFormatted((delta.runs || [])
    .map(function (r) { return formatRun(r, now); }), new Date(now || Date.now()))
    .filter(function (r) { return !seen[r.id]; });
  if (fresh.length) {
    patch.runs = fresh.concat(pageData.runs || []).slice(0, MAX_RUNS);
  }
  return patch;
}

module.exports = { hasChanges, applyDelta };
