// 后端通信层：REST 首屏 + WebSocket 实时推送（断线自动重连）。
// wx.connectSocket 返回 SocketTask、SocketTask.onXxx 等能力的基础库版本要求，需以官方文档核实。
const C = require('../utils/constants');

// headers 可选：设置页保存凭证时用于携带 X-Admin-Token（口令不落盘、不进日志）
// 所有 /api/* 请求统一附带会话 token；401 由后端中间件返回，清登录态并回登录页。
// 401 时并发请求可能同时触发跳转，1 秒内只 reLaunch 一次，避免登录页被重复打开。
let relaunching = false;
function goLogin() {
  C.clearAuth();
  if (relaunching) return;
  relaunching = true;
  if (typeof wx !== 'undefined' && wx.reLaunch) {
    wx.reLaunch({ url: '/pages/login/login' });
  }
  setTimeout(function () { relaunching = false; }, 1000);
}

function request(path, method, data, headers) {
  return new Promise(function (resolve, reject) {
    const token = C.getAuthToken();
    wx.request({
      url: C.getRestBase() + path,
      method: method || 'GET',
      data: data || {},
      header: Object.assign(
        { 'Content-Type': 'application/json' },
        token ? { 'Authorization': 'Bearer ' + token } : {},
        headers || {}
      ),
      timeout: 15000,
      success: function (res) {
        if (res.statusCode === 401 && path.indexOf('/api/auth/') !== 0) {
          goLogin();
          reject(new Error('登录已过期，请重新登录'));
          return;
        }
        if (res.statusCode >= 200 && res.statusCode < 300) resolve(res.data);
        else reject(new Error('HTTP ' + res.statusCode));
      },
      fail: function (err) {
        reject(new Error(err.errMsg || '网络请求失败'));
      }
    });
  });
}

function query(params) {
  const parts = [];
  Object.keys(params || {}).forEach(function (k) {
    if (params[k] === '' || params[k] === undefined || params[k] === null) return;
    parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(params[k]));
  });
  return parts.length ? '?' + parts.join('&') : '';
}

function fetchSnapshot() {
  return request('/api/snapshot', 'GET');
}

function fetchBotLogs(botUuid) {
  return request('/api/bot/' + encodeURIComponent(botUuid) + '/logs', 'GET');
}

function fetchRunDetail(runId, botUuid) {
  return request('/api/run/' + encodeURIComponent(runId) + '/detail' +
    query({ botUuid: botUuid }), 'GET');
}

// 按运行记录查错误日志（后端内部 process/detail -> job/log/search）
function fetchRunLogs(runId, botUuid) {
  return request('/api/run/' + encodeURIComponent(runId) + '/logs' +
    query({ botUuid: botUuid }), 'GET');
}

function testConnection() {
  return request('/health', 'GET');
}

function stopJob(jobUuid) {
  return request('/api/control/stop', 'POST', { jobUuid: jobUuid });
}

// 前端只持有 taskUuid；后端负责查 process/detail 换成 jobUuid 再停
function stopByTask(taskUuid, botUuid) {
  return request('/api/control/stop-by-task', 'POST',
    { taskUuid: taskUuid, botUuid: botUuid || '' });
}

// ---- 应用搜索 / 远程运行 / 异常重试 ----

function searchApps(keyword, page, size) {
  return request('/api/apps/search' + query({
    keyword: keyword || '', page: page || 1, size: size || 20
  }), 'GET');
}

function refreshApps() {
  return request('/api/apps/refresh', 'POST');
}

function startApp(appId, accountName) {
  return request('/api/control/start', 'POST',
    { appId: appId, accountName: accountName || '', params: [] });
}

function retryRun(taskUuid, botUuid) {
  return request('/api/control/retry', 'POST',
    { taskUuid: taskUuid, botUuid: botUuid || '' });
}

// ---- 登录与账号管理（仅「账号管理」接口要求超级管理员） ----

function login(username, password) {
  return request('/api/auth/login', 'POST', { username: username, password: password });
}

function getMe() {
  return request('/api/auth/me', 'GET');
}

function logout() {
  return request('/api/auth/logout', 'POST');
}

function changePassword(oldPassword, newPassword) {
  return request('/api/auth/password', 'POST',
    { oldPassword: oldPassword, newPassword: newPassword });
}

function listUsers() {
  return request('/api/auth/users', 'GET');
}

function addUser(username, password) {
  return request('/api/auth/users', 'POST', { username: username, password: password });
}

function deleteUser(username) {
  return request('/api/auth/users/' + encodeURIComponent(username), 'DELETE');
}

function resetUserPassword(username, newPassword) {
  return request('/api/auth/users/' + encodeURIComponent(username) + '/reset', 'POST',
    { newPassword: newPassword });
}

// ---- 设置：密钥只提交到后端写 .env，不回显、不落前端存储 ----

function getSettings() {
  return request('/api/settings', 'GET');
}

function testCredentials() {
  return request('/api/settings/test', 'POST');
}

function saveCredentials(accessKeyId, accessKeySecret, adminToken) {
  const headers = adminToken ? { 'X-Admin-Token': adminToken } : {};
  return request('/api/settings/credentials', 'POST', {
    accessKeyId: accessKeyId,
    accessKeySecret: accessKeySecret
  }, headers);
}

function connect(handlers) {
  const h = handlers || {};
  let socket = null;
  let closed = false;
  let retries = 0;
  let reconnectTimer = null;
  let heartbeatTimer = null;

  function clearTimers() {
    if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  }

  function scheduleReconnect() {
    if (closed || reconnectTimer) return;
    const delay = Math.min(
      C.RECONNECT_BASE_MS * Math.pow(2, retries),
      C.RECONNECT_MAX_MS
    );
    retries += 1;
    reconnectTimer = setTimeout(function () {
      reconnectTimer = null;
      open();
    }, delay);
  }

  function dispatch(raw) {
    if (raw === 'pong') return;
    let msg;
    try { msg = JSON.parse(raw); } catch (e) { return; }
    if (msg.type === 'snapshot' && h.onSnapshot) h.onSnapshot(msg);
    else if (msg.type === 'delta' && h.onDelta) h.onDelta(msg.data);
    else if (msg.type === 'alarm' && h.onAlarm) h.onAlarm(msg.data);
    else if (msg.type === 'callback' && h.onCallback) h.onCallback(msg.data);
    else if (msg.type === 'control_result' && h.onControlResult) h.onControlResult(msg.data);
  }

  function open() {
    if (closed) return;
    // token 走 header，不进 URL query（避免反代日志泄漏会话凭证）
    socket = wx.connectSocket({ url: C.getWsUrl(), header: C.getWsHeaders() });
    socket.onOpen(function () {
      retries = 0;
      if (h.onOpen) h.onOpen();
      heartbeatTimer = setInterval(function () {
        if (socket) socket.send({ data: 'ping' });
      }, C.HEARTBEAT_MS);
    });
    socket.onMessage(function (res) { dispatch(res.data); });
    socket.onError(function (err) {
      if (h.onError) h.onError(err);
    });
    socket.onClose(function () {
      clearTimers();
      if (h.onClose) h.onClose();
      scheduleReconnect();
    });
  }

  open();

  return {
    // 页面 onUnload 必须调用，否则定时器与监听会泄漏（E-09）
    close: function () {
      closed = true;
      clearTimers();
      if (socket) {
        try { socket.close({ code: 1000 }); } catch (e) { /* 已断开 */ }
        socket = null;
      }
    }
  };
}

module.exports = {
  request,
  query,
  fetchSnapshot,
  fetchBotLogs,
  fetchRunDetail,
  fetchRunLogs,
  testConnection,
  stopJob,
  stopByTask,
  searchApps,
  refreshApps,
  startApp,
  retryRun,
  getSettings,
  testCredentials,
  saveCredentials,
  login,
  getMe,
  logout,
  changePassword,
  listUsers,
  addUser,
  deleteUser,
  resetUserPassword,
  connect
};
