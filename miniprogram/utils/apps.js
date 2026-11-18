// 应用目录展示逻辑（搜索已发布流程 / 远程运行）。
// 后端 GET /api/apps/search 返回 data 为数组，字段：appId/appName/version/ownerName/publishTime/published。
// 纯函数，不依赖 wx，可被 Node 单测直接 require。
function shortTime(value) {
  return String(value || '').replace('T', ' ').slice(0, 16);
}

function formatApp(raw) {
  const a = raw || {};
  const published = a.published !== false;
  return {
    appId: a.appId || '',
    appName: a.appName || '未命名流程',
    version: String(a.version || '-'),
    ownerName: a.ownerName || '未知负责人',
    publishTime: shortTime(a.publishTime),
    published: published,
    runnable: Boolean(a.appId) && published
  };
}

function formatApps(rows) {
  return (rows || []).map(formatApp);
}

function mergeApps(existing, incoming) {
  // 「加载更多」时按 appId 去重，避免分页边界重复渲染
  const seen = {};
  const out = [];
  (existing || []).concat(incoming || []).forEach(function (a) {
    if (!a || !a.appId || seen[a.appId]) return;
    seen[a.appId] = 1;
    out.push(a);
  });
  return out;
}

function botOptions(bots) {
  // 只把非离线机器人放进 picker，避免选到无法执行的账号
  const names = (bots || [])
    .filter(function (b) { return b.status !== 'offline' && b.status !== 'disconnected'; })
    .map(function (b) { return b.name; });
  return ['默认（影刀自动分配）'].concat(names);
}

function accountNameOf(options, index) {
  // index 0 = 默认（不指定 accountName，由影刀自动分配）
  const i = Number(index) || 0;
  return i > 0 ? (options[i] || '') : '';
}

module.exports = {
  shortTime: shortTime,
  formatApp: formatApp,
  formatApps: formatApps,
  mergeApps: mergeApps,
  botOptions: botOptions,
  accountNameOf: accountNameOf
};
