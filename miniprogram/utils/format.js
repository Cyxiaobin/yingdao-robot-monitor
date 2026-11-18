// 纯展示逻辑：不依赖 wx，可被 Node 直接 require 做单元测试。
// WXML 不能调用函数，所有展示字段必须在这里预处理好。
const { filterFormatted } = require('./today');

// 影刀 status 真实枚举需以官方《机器人状态枚举值说明》核实；未知值统一兜底为 unknown。
const BOT_STATUS_MAP = {
  running: { label: '运行中', color: '#378add', bg: '#e6f1fb' },
  busy: { label: '运行中', color: '#378add', bg: '#e6f1fb' },
  executing: { label: '运行中', color: '#378add', bg: '#e6f1fb' },
  idle: { label: '空闲', color: '#1d9e75', bg: '#e1f5ee' },
  online: { label: '空闲', color: '#1d9e75', bg: '#e1f5ee' },
  free: { label: '空闲', color: '#1d9e75', bg: '#e1f5ee' },
  error: { label: '报错', color: '#e24b4a', bg: '#fcebeb' },
  exception: { label: '报错', color: '#e24b4a', bg: '#fcebeb' },
  fail: { label: '报错', color: '#e24b4a', bg: '#fcebeb' },
  failed: { label: '报错', color: '#e24b4a', bg: '#fcebeb' },
  offline: { label: '离线', color: '#888780', bg: '#f1efe8' },
  disconnected: { label: '离线', color: '#888780', bg: '#f1efe8' },
  off: { label: '离线', color: '#888780', bg: '#f1efe8' }
};

const FALLBACK_BOT = { label: '未知', color: '#888780', bg: '#f1efe8' };

const RUN_STATUS_MAP = {
  success: { state: 'success', label: '成功', color: '#1d9e75' },
  succeed: { state: 'success', label: '成功', color: '#1d9e75' },
  finished: { state: 'success', label: '成功', color: '#1d9e75' },
  completed: { state: 'success', label: '成功', color: '#1d9e75' },
  done: { state: 'success', label: '成功', color: '#1d9e75' },
  finish: { state: 'success', label: '成功', color: '#1d9e75' },
  stopped: { state: 'fail', label: '已停止', color: '#d97706' },
  fail: { state: 'fail', label: '失败', color: '#e24b4a' },
  failed: { state: 'fail', label: '失败', color: '#e24b4a' },
  error: { state: 'fail', label: '失败', color: '#e24b4a' },
  exception: { state: 'fail', label: '失败', color: '#e24b4a' },
  timeout: { state: 'fail', label: '失败', color: '#e24b4a' },
  cancel: { state: 'fail', label: '失败', color: '#e24b4a' },
  cancelled: { state: 'fail', label: '失败', color: '#e24b4a' },
  running: { state: 'running', label: '运行中', color: '#378add' },
  executing: { state: 'running', label: '运行中', color: '#378add' },
  waiting: { state: 'running', label: '运行中', color: '#378add' },
  pending: { state: 'running', label: '运行中', color: '#378add' }
};

const FALLBACK_RUN = { state: 'unknown', label: '未知', color: '#888780' };

function parseTime(value) {
  if (!value) return null;
  // iOS 小程序对 "yyyy-MM-dd HH:mm:ss" 解析不稳定，统一转 "yyyy/MM/dd HH:mm:ss"
  const normalized = String(value)
    .replace('T', ' ')
    .replace(/-/g, '/')
    .replace(/\.\d+.*$/, '')
    .replace(/Z$/, '')
    .trim();
  const ts = Date.parse(normalized);
  return Number.isNaN(ts) ? null : ts;
}

function formatDuration(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  if (s < 60) return s + 's';
  const m = Math.floor(s / 60);
  const rest = s % 60;
  if (m < 60) return rest ? m + 'm' + rest + 's' : m + 'm';
  const h = Math.floor(m / 60);
  return h + 'h' + (m % 60) + 'm';
}

function relativeTime(value, now) {
  const ts = parseTime(value);
  if (ts === null) return '';
  const base = now || Date.now();
  const diff = Math.max(0, Math.floor((base - ts) / 1000));
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
  if (diff < 86400) return Math.floor(diff / 3600) + '小时前';
  return Math.floor(diff / 86400) + '天前';
}

function botStatusOf(raw) {
  return BOT_STATUS_MAP[String(raw || '').toLowerCase()] || FALLBACK_BOT;
}

function runStatusOf(raw) {
  return RUN_STATUS_MAP[String(raw || '').toLowerCase()] || FALLBACK_RUN;
}

function formatBot(raw) {
  const bot = raw || {};
  const style = botStatusOf(bot.status);
  return {
    uuid: bot.uuid || '',
    name: bot.name || '未命名机器人',
    ip: bot.ip || '',
    status: bot.status || 'unknown',
    currentApp: bot.current_app || bot.currentApp || '',
    machineName: bot.machine_name || bot.machineName || '',
    statusLabel: style.label,
    statusColor: style.color,
    statusBg: style.bg
  };
}

function formatRun(raw, now) {
  const run = raw || {};
  const style = runStatusOf(run.status);
  const meta = [formatDuration(run.duration_sec), relativeTime(run.create_time, now)]
    .filter(Boolean)
    .join(' · ');
  return {
    id: run.id || '',
    appName: run.app_name || run.appName || '未命名应用',
    status: run.status || 'unknown',
    state: style.state,
    stateLabel: style.label,
    stateColor: style.color,
    durationText: meta,
    createTime: run.create_time || run.createTime || '',   // 供「仅当天」兜底过滤
    remark: run.remark || '',
    screenshotUrl: run.screenshot_url || run.screenshotUrl || '',
    botUuid: run.bot_uuid || run.botUuid || '',
    // 列表接口无截图字段：失败记录也可点开，由后端 detail 补 screenshotUrl
    hasScreenshot: Boolean(run.screenshot_url || run.screenshotUrl ||
      (style.state === 'fail' && run.id && (run.bot_uuid || run.botUuid)))
  };
}

function safeOverview(raw) {
  const o = raw || {};
  return {
    bot_total: Number(o.bot_total) || 0,
    bot_online: Number(o.bot_online) || 0,
    runs_today: Number(o.runs_today) || 0,
    success_rate: Number(o.success_rate) || 0,
    error_count: Number(o.error_count) || 0
  };
}

function formatSnapshot(snapshot, now) {
  const data = snapshot || {};
  // 后端已按当天过滤；这里兜底旧版服务端 / 演示数据里的跨天记录
  const runs = filterFormatted(
    (data.runs || []).map(function (r) { return formatRun(r, now); }),
    new Date(now || Date.now())
  );
  return {
    ts: data.ts || '',
    overview: safeOverview(data.overview),
    bots: (data.bots || []).map(formatBot),
    runs: runs
  };
}

module.exports = {
  BOT_STATUS_MAP,
  RUN_STATUS_MAP,
  parseTime,
  formatDuration,
  relativeTime,
  botStatusOf,
  runStatusOf,
  formatBot,
  formatRun,
  safeOverview,
  formatSnapshot
};
