// 后端地址配置。
// 默认值是本机局域网 IP（真机预览用）；「我的」页可随时覆盖，存在本地 storage。
// 上线：CURRENT 改为 'prod'，并在小程序后台配置 request / socket 合法域名（必须 HTTPS / wss）。
const ENV = {
  dev: { restBase: 'http://192.168.1.100:8000' },
  prod: { restBase: 'https://your-domain.example.com' }
};

const CURRENT = 'dev';
const STORAGE_KEY = 'yd_backend_base';
const HANDLED_KEY = 'yd_handled_alarms';
// 登录态：只存会话 token 与展示用的用户名/角色，绝不存密码或影刀密钥
const AUTH_TOKEN_KEY = 'yd_auth_token';
const AUTH_USER_KEY = 'yd_auth_user';

function normalizeBase(input) {
  let s = String(input || '').trim().replace(/\/+$/, '');
  if (!s) return ENV[CURRENT].restBase;
  // 允许只填 192.168.1.100:8000，自动补协议
  if (!/^https?:\/\//i.test(s)) s = 'http://' + s;
  return s;
}

function wsUrlOf(base) {
  return normalizeBase(base)
    .replace(/^https:\/\//i, 'wss://')
    .replace(/^http:\/\//i, 'ws://') + '/ws';
}

function getRestBase() {
  if (typeof wx !== 'undefined' && wx.getStorageSync) {
    try {
      const saved = wx.getStorageSync(STORAGE_KEY);
      if (saved) return normalizeBase(saved);
    } catch (e) { /* 读不到就用默认 */ }
  }
  return ENV[CURRENT].restBase;
}

function getWsUrl() {
  return wsUrlOf(getRestBase());
}

// WebSocket 握手参数：token 走 header，不进 URL（避免被反代 access log 记录）。
// 后端 /ws 同时兼容 ?token= 与 Authorization header；浏览器看板用原生 WebSocket 只能走前者。
function getWsHeaders() {
  const token = getAuthToken();
  return token ? { 'Authorization': 'Bearer ' + token } : {};
}

function getAuthToken() {
  if (typeof wx !== 'undefined' && wx.getStorageSync) {
    try { return wx.getStorageSync(AUTH_TOKEN_KEY) || ''; } catch (e) { return ''; }
  }
  return '';
}

function getAuthUser() {
  if (typeof wx !== 'undefined' && wx.getStorageSync) {
    try { return wx.getStorageSync(AUTH_USER_KEY) || {}; } catch (e) { return {}; }
  }
  return {};
}

function setAuth(token, user) {
  if (typeof wx !== 'undefined' && wx.setStorageSync) {
    try {
      wx.setStorageSync(AUTH_TOKEN_KEY, token || '');
      wx.setStorageSync(AUTH_USER_KEY, user || {});
    } catch (e) { /* 存储不可用时本次会话仍有效 */ }
  }
}

function clearAuth() {
  if (typeof wx !== 'undefined' && wx.removeStorageSync) {
    try {
      wx.removeStorageSync(AUTH_TOKEN_KEY);
      wx.removeStorageSync(AUTH_USER_KEY);
    } catch (e) { /* 忽略 */ }
  }
}

function setRestBase(base) {
  const value = normalizeBase(base);
  if (typeof wx !== 'undefined' && wx.setStorageSync) {
    wx.setStorageSync(STORAGE_KEY, value);
  }
  return value;
}

function clearRestBase() {
  if (typeof wx !== 'undefined' && wx.removeStorageSync) {
    wx.removeStorageSync(STORAGE_KEY);
  }
  return ENV[CURRENT].restBase;
}

module.exports = {
  REST_BASE: ENV[CURRENT].restBase,
  WS_URL: wsUrlOf(ENV[CURRENT].restBase),
  ENV_NAME: CURRENT,
  STORAGE_KEY: STORAGE_KEY,
  HANDLED_KEY: HANDLED_KEY,
  AUTH_TOKEN_KEY: AUTH_TOKEN_KEY,
  AUTH_USER_KEY: AUTH_USER_KEY,
  HEARTBEAT_MS: 25000,
  RECONNECT_BASE_MS: 2000,
  RECONNECT_MAX_MS: 30000,
  MAX_RUNS: 20,
  normalizeBase: normalizeBase,
  wsUrlOf: wsUrlOf,
  getRestBase: getRestBase,
  getWsUrl: getWsUrl,
  getWsHeaders: getWsHeaders,
  getAuthToken: getAuthToken,
  getAuthUser: getAuthUser,
  setAuth: setAuth,
  clearAuth: clearAuth,
  setRestBase: setRestBase,
  clearRestBase: clearRestBase
};
