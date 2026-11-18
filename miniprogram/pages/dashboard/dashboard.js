// 看板页：4 Tab（看板 / 异常 / 应用 / 设置）+ 看板内三段筛选（机器人 / 运行中 / 已完成）。
// 数据链路：首屏 REST 拉全量 → WebSocket 增量更新；异常/应用/设置走后端 9 个新端点。
// 所有展示字段在 utils 里预处理，WXML 不调用函数；setData 只传变化字段。
const { formatSnapshot, safeOverview } = require('../../utils/format');
const { applyDelta } = require('../../utils/diff');
const C = require('../../utils/constants');
const { buildAlarms, markHandled } = require('../../utils/alarm');
const segments = require('../../utils/segments');
const appUtil = require('../../utils/apps');
const { formatLogs, logsNotice } = require('../../utils/logs');
const today = require('../../utils/today');
const monitor = require('../../services/monitor');

const EMPTY_OVERVIEW = safeOverview({});
const APP_PAGE_SIZE = 20;
// job/retry 官方说明：仅「异常」或「已停止」状态可重试
const RETRYABLE = ['error', 'fail', 'failed', 'stopped', 'timeout', 'exception', 'cancel', 'cancelled'];

function readHandled() {
  try { return wx.getStorageSync(C.HANDLED_KEY) || {}; } catch (e) { return {}; }
}

function saveHandled(map) {
  try { wx.setStorageSync(C.HANDLED_KEY, map); } catch (e) { /* 存储不可用时本次会话仍有效 */ }
}

function canRetry(run, allowControl) {
  return Boolean(run) && run.state === 'fail' &&
    RETRYABLE.indexOf(String(run.status || '').toLowerCase()) >= 0 &&
    allowControl !== false;
}

Page({
  data: {
    overview: EMPTY_OVERVIEW,
    bots: [],
    shownBots: [],
    runs: [],
    shownRuns: [],
    alarms: [],
    alarmCount: 0,
    activeTab: 'board',
    segment: 'bots',
    segmentTitle: '机器人状态',
    segmentEmpty: '暂无机器人数据',
    ts: '',
    tsShort: '--:--',
    errorMsg: '',
    envName: C.ENV_NAME,
    backendBase: '',
    baseInput: '',
    connState: '未测试',
    handledCount: 0,
    loading: true,
    connected: false,
    // 应用（搜索已发布流程并运行）
    keyword: '',
    apps: [],
    appTotal: 0,
    appPage: 1,
    appHasMore: false,
    appLoading: false,
    appMsg: '',
    botOptions: ['默认（影刀自动分配）'],
    accountIndex: 0,
    allowControl: true,
    // 设置（凭证只提交后端，不落前端存储）
    settings: {},
    settingsLoaded: false,
    keyIdInput: '',
    keySecretInput: '',
    tokenInput: '',
    credState: '',
    // 详情抽屉：备注 / 错误日志 / 现场截图 / 重试
    drawerShow: false,
    drawerLoading: false,
    drawerRun: {},
    drawerRemark: '',
    drawerShot: '',
    drawerLogs: [],
    drawerLogNotice: '',
    drawerCanRetry: false,
    // 登录与账号（仅账号管理区块是管理员专属）
    currentUser: '',
    currentRole: '',
    isAdmin: false,
    authEnabled: true,
    scopeLabel: today.scopeLabel(),
    accountMsg: '',
    users: [],
    userCount: 0,
    newUserInput: '',
    newUserPwd: '',
    oldPwdInput: '',
    newPwdInput: ''
  },

  onLoad() {
    this._conn = null;
    this._handled = readHandled();
    const base = C.getRestBase();
    this.setData({
      backendBase: base,
      baseInput: base,
      handledCount: Object.keys(this._handled).length
    });
    this.loadSnapshot();
    this.connectWs();
    this.loadSettings();
    this.checkAuth();
  },

  /* ---------- 登录态 ---------- */

  goLogin() {
    C.clearAuth();
    if (this._conn) { this._conn.close(); this._conn = null; }
    wx.reLaunch({ url: '/pages/login/login' });
  },

  async checkAuth() {
    try {
      const me = await monitor.getMe();
      // authEnabled=false 表示服务端关闭了鉴权（本地调试），无需 token
      if (me.authEnabled !== false && !me.authenticated) {
        this.goLogin();
        return;
      }
      this.setData({
        currentUser: me.username || C.getAuthUser().username || 'local',
        currentRole: me.role === 'admin' ? '超级管理员' : '普通用户',
        isAdmin: me.role === 'admin',
        authEnabled: me.authEnabled !== false
      });
      if (me.role === 'admin') this.loadUsers();
    } catch (err) {
      // 后端暂时不可达时不强制踢回登录页，看板自身已有错误提示与重试
      this.setData({ currentUser: C.getAuthUser().username || '未登录' });
    }
  },

  async loadUsers() {
    try {
      const res = await monitor.listUsers();
      // WXML 不调用函数：角色文案 / 首字母 / 时间在 JS 里预生成
      const users = (res.users || []).map(function (u) {
        const name = String(u.username || '?');
        return Object.assign({}, u, {
          firstLetter: name.slice(0, 1).toUpperCase(),
          roleText: u.role === 'admin' ? '超级管理员' : '普通用户',
          createdText: String(u.createdAt || '').replace('T', ' ').slice(0, 16) || '—'
        });
      });
      this.setData({ users: users, userCount: users.length });
    } catch (err) {
      this.setData({ accountMsg: '账号列表加载失败：' + (err.message || '网络异常') });
    }
  },

  /* ---------- 账号：本人改密 / 退出登录 / 管理员增删普通用户 ---------- */

  async onLogout() {
    try { await monitor.logout(); } catch (err) { /* 服务端不可达也要清掉本地登录态 */ }
    this.goLogin();
  },

  onOldPwdInput(e) { this.setData({ oldPwdInput: e.detail.value }); },
  onNewPwdInput(e) { this.setData({ newPwdInput: e.detail.value }); },
  onNewUserInput(e) { this.setData({ newUserInput: e.detail.value }); },
  onNewUserPwd(e) { this.setData({ newUserPwd: e.detail.value }); },

  async onChangePassword() {
    const oldPwd = String(this.data.oldPwdInput || '');
    const newPwd = String(this.data.newPwdInput || '');
    if (newPwd.length < 6) {
      wx.showToast({ title: '新密码至少 6 位', icon: 'none' });
      return;
    }
    wx.showLoading({ title: '修改中', mask: true });
    try {
      const out = await monitor.changePassword(oldPwd, newPwd);
      wx.hideLoading();
      if (!out.success) {
        this.setData({ accountMsg: out.msg || '修改失败' });
        return;
      }
      // 服务端改密后已吊销旧会话，清本地并回登录页
      this.setData({ oldPwdInput: '', newPwdInput: '', accountMsg: out.msg || '密码已修改' });
      wx.showToast({ title: '请重新登录', icon: 'none' });
      this.goLogin();
    } catch (err) {
      wx.hideLoading();
      this.setData({ accountMsg: '修改失败：' + (err.message || '网络异常') });
    }
  },

  async onAddUser() {
    const username = String(this.data.newUserInput || '').trim();
    const password = String(this.data.newUserPwd || '');
    if (!username || password.length < 6) {
      wx.showToast({ title: '请填账号与至少 6 位密码', icon: 'none' });
      return;
    }
    wx.showLoading({ title: '创建中', mask: true });
    try {
      const out = await monitor.addUser(username, password);
      wx.hideLoading();
      if (!out.success) {
        this.setData({ accountMsg: out.msg || '创建失败' });
        wx.showToast({ title: out.msg || '创建失败', icon: 'none' });
        return;
      }
      this.setData({ newUserInput: '', newUserPwd: '', accountMsg: '已创建：' + username });
      wx.showToast({ title: '普通用户已创建', icon: 'none' });
      this.loadUsers();
    } catch (err) {
      wx.hideLoading();
      this.setData({ accountMsg: '创建失败：' + (err.message || '网络异常') });
    }
  },

  onRefreshUsers() {
    this.loadUsers();
    wx.showToast({ title: '已刷新', icon: 'none' });
  },

  onDeleteUser(e) {
    const name = String(e.currentTarget.dataset.user || '');
    if (!name) return;
    const self = this;
    wx.showModal({
      title: '删除这个账号？',
      content: '账号「' + name + '」将立即无法登录；内置超级管理员不可删除。',
      confirmText: '确认删除',
      confirmColor: '#e24b4a',
      success: async function (res) {
        if (!res.confirm) return;
        wx.showLoading({ title: '删除中', mask: true });
        try {
          const out = await monitor.deleteUser(name);
          wx.hideLoading();
          self.setData({ accountMsg: out.msg || (out.success ? '已删除' : '删除失败') });
          wx.showToast({ title: out.success ? '账号已删除' : (out.msg || '删除失败'), icon: 'none' });
          self.loadUsers();
        } catch (err) {
          wx.hideLoading();
          self.setData({ accountMsg: '删除失败：' + (err.message || '网络异常') });
        }
      }
    });
  },

  onUnload() {
    if (this._conn) {
      this._conn.close();
      this._conn = null;
    }
  },

  onPullDownRefresh() {
    this.loadSnapshot(true);
  },

  /* ---------- 数据层 ---------- */

  _applySegment() {
    const segment = this.data.segment;
    const bots = this.data.bots || [];
    const runs = this.data.runs || [];
    // 首字母头像：WXML 不能做字符串处理，在这里预生成
    const shownBots = bots.map(function (b) {
      return Object.assign({}, b, {
        initials: String(b.name || '?').replace(/[^A-Za-z0-9]/g, '').slice(0, 2).toUpperCase() || 'R'
      });
    });
    this.setData({
      shownBots: shownBots,
      shownRuns: segment === 'bots' ? [] : segments.filterRuns(runs, segment).slice(0, C.MAX_RUNS),
      segmentTitle: segment === 'bots' ? '机器人状态' : segments.segmentTitle(segment),
      segmentEmpty: segment === 'bots' ? '暂无机器人数据' : segments.emptyText(segment),
      botOptions: appUtil.botOptions(bots)
    });
  },

  _refreshAlarms() {
    const alarms = buildAlarms(this.data.runs, this._handled);
    this.setData({ alarms: alarms, alarmCount: alarms.length });
  },

  _afterSnapshot(formatted) {
    const rawTs = String(formatted.ts || '').replace('T', ' ');
    this.setData({
      overview: formatted.overview,
      bots: formatted.bots,
      runs: formatted.runs,
      ts: formatted.ts,
      tsShort: rawTs.slice(11, 19) || '--:--',
      loading: false,
      errorMsg: ''
    });
    this._applySegment();
    this._refreshAlarms();
  },

  async loadSnapshot(isRefresh) {
    try {
      const res = await monitor.fetchSnapshot();
      this._afterSnapshot(formatSnapshot(res.data, Date.now()));
    } catch (err) {
      this.setData({ loading: false, errorMsg: err.message || '加载失败' });
      wx.showToast({ title: '加载失败', icon: 'none' });
    } finally {
      if (isRefresh) wx.stopPullDownRefresh();
    }
  },

  connectWs() {
    this._conn = monitor.connect({
      onOpen: () => this.setData({ connected: true }),
      onClose: () => this.setData({ connected: false }),
      onError: () => this.setData({ connected: false }),
      onSnapshot: (msg) => this._afterSnapshot(formatSnapshot(msg.data, Date.now())),
      onDelta: (delta) => {
        const patch = applyDelta(this.data, delta, Date.now());
        if (Object.keys(patch).length) {
          this.setData(patch, () => { this._applySegment(); this._refreshAlarms(); });
        }
      },
      onAlarm: (items) => {
        // 后端已做同因 5 分钟去重；这里只提示，不自动切 Tab 打扰用户
        if (items && items.length) wx.showToast({ title: '有新的运行异常', icon: 'none' });
      },
      onCallback: () => this.loadSnapshot(),
      onControlResult: () => this.loadSnapshot()
    });
  },

  /* ---------- 看板 ---------- */

  onRefreshTap() { this.loadSnapshot(true); },

  onRetryTap() {
    this.setData({ loading: true, errorMsg: '' });
    this.loadSnapshot();
    if (!this._conn) this.connectWs();
  },

  onTabTap(e) {
    const tab = e.currentTarget.dataset.tab;
    this.setData({ activeTab: tab });
    // 首次进应用页自动拉一批已发布流程，省一次点击
    if (tab === 'apps' && !this.data.apps.length && !this.data.appLoading) this.onSearchApps();
  },

  onSegmentTap(e) {
    const value = e.currentTarget.dataset.segment;
    if (!segments.isSegment(value)) return;
    this.setData({ segment: value }, () => this._applySegment());
  },

  onBotTap(e) {
    const d = e.currentTarget.dataset;
    // 顺带把该机器人正在运行的任务带给详情页，供「停止」按钮使用
    const running = (this.data.runs || []).find(function (r) {
      return r.botUuid === d.uuid && r.state === 'running';
    });
    wx.navigateTo({
      url: '/pages/bot-detail/bot-detail?uuid=' + encodeURIComponent(d.uuid) +
        '&name=' + encodeURIComponent(d.name) +
        '&status=' + encodeURIComponent(d.status) +
        '&statusLabel=' + encodeURIComponent(d.statuslabel) +
        '&statusColor=' + encodeURIComponent(d.statuscolor) +
        '&statusBg=' + encodeURIComponent(d.statusbg) +
        '&ip=' + encodeURIComponent(d.ip) +
        '&currentApp=' + encodeURIComponent(d.currentapp) +
        '&runId=' + encodeURIComponent(running ? running.id : '') +
        '&runBot=' + encodeURIComponent(d.uuid)
    });
  },

  onStopTap(e) {
    const d = e.currentTarget.dataset;
    if (!d.task) return;
    const self = this;
    wx.showModal({
      title: '停止运行中的应用？',
      content: '这会中断机器人正在执行的业务任务，且不可撤销。请确认该任务确实需要中止。',
      confirmText: '确认停止',
      confirmColor: '#e24b4a',
      success: async function (res) {
        if (!res.confirm) return;
        wx.showLoading({ title: '正在停止', mask: true });
        try {
          const out = await monitor.stopByTask(d.task, d.bot);
          wx.hideLoading();
          if (out.success) {
            wx.showToast({ title: '已发送停止指令', icon: 'none' });
            self.loadSnapshot();
          } else {
            wx.showToast({ title: out.msg || '停止失败', icon: 'none' });
          }
        } catch (err) {
          wx.hideLoading();
          wx.showToast({ title: '网络异常，停止失败', icon: 'none' });
        }
      }
    });
  },

  /* ---------- 详情抽屉：备注 / 日志 / 截图 / 重试 ---------- */

  async onDrawerTap(e) {
    const d = e.currentTarget.dataset;
    const id = d.id;
    if (!id) return;
    const run = (this.data.runs || []).find(function (r) { return r.id === id; }) || {};
    this.setData({
      drawerShow: true,
      drawerLoading: true,
      drawerRun: run,
      drawerRemark: run.remark || '',
      drawerShot: run.screenshotUrl || '',
      drawerLogs: [],
      drawerLogNotice: '',
      drawerCanRetry: canRetry(run, this.data.allowControl)
    });
    try {
      // 列表接口不返回截图与错误备注，需 process/detail + log/search 两个端点补齐
      const [detail, logs] = await Promise.all([
        monitor.fetchRunDetail(id, d.bot).catch(function () { return { jobs: [] }; }),
        monitor.fetchRunLogs(id, d.bot).catch(function () {
          return { logs: [], error: '日志接口请求失败' };
        })
      ]);
      const job = (detail.jobs || [])[0] || {};
      this.setData({
        drawerShot: job.screenshotUrl || run.screenshotUrl || '',
        drawerRemark: job.remark || run.remark || '',
        drawerLogs: formatLogs(logs.logs),
        drawerLogNotice: logsNotice(logs.logs, logs.error),
        drawerLoading: false
      });
    } catch (err) {
      this.setData({ drawerLoading: false, drawerLogNotice: '详情加载失败，请稍后重试' });
    }
  },

  onCloseDrawer() {
    this.setData({ drawerShow: false });
  },

  onDrawerShotTap() {
    const url = this.data.drawerShot;
    if (url) wx.previewImage({ current: url, urls: [url] });
  },

  async onScreenshotTap(e) {
    const d = e.currentTarget.dataset;
    if (d.url) {
      wx.previewImage({ current: d.url, urls: [d.url] });
      return;
    }
    if (!d.id) return;
    try {
      const res = await monitor.fetchRunDetail(d.id, d.bot);
      const shots = (res.jobs || []).map(function (j) { return j.screenshotUrl; }).filter(Boolean);
      if (shots.length) wx.previewImage({ current: shots[0], urls: shots });
      else wx.showToast({ title: '暂无截图', icon: 'none' });
    } catch (err) {
      wx.showToast({ title: '详情加载失败', icon: 'none' });
    }
  },

  onRetryRunTap(e) {
    const d = e.currentTarget.dataset;
    if (!d.task) return;
    const self = this;
    wx.showModal({
      title: '重试这个异常流程？',
      content: '影刀会在原机器人上重新运行该任务，可能重复写入业务数据，请确认后再执行。',
      confirmText: '确认重试',
      confirmColor: '#e24b4a',
      success: async function (res) {
        if (!res.confirm) return;
        wx.showLoading({ title: '正在重试', mask: true });
        try {
          const out = await monitor.retryRun(d.task, d.bot);
          wx.hideLoading();
          if (out.success) {
            wx.showToast({ title: '已发送重试指令', icon: 'none' });
            self.setData({ drawerShow: false });
            self.loadSnapshot();
          } else {
            wx.showToast({ title: out.msg || '重试失败', icon: 'none' });
          }
        } catch (err) {
          wx.hideLoading();
          wx.showToast({ title: '网络异常，重试失败', icon: 'none' });
        }
      }
    });
  },

  /* ---------- 异常 Tab ---------- */

  onMarkAlarm(e) {
    this._handled = markHandled(this._handled, e.currentTarget.dataset.id, 'done');
    saveHandled(this._handled);
    this.setData({ handledCount: Object.keys(this._handled).length });
    this._refreshAlarms();
    wx.showToast({ title: '已标记处理', icon: 'none' });
  },

  onIgnoreAlarm(e) {
    this._handled = markHandled(this._handled, e.currentTarget.dataset.id, 'ignored');
    saveHandled(this._handled);
    this.setData({ handledCount: Object.keys(this._handled).length });
    this._refreshAlarms();
    wx.showToast({ title: '已忽略', icon: 'none' });
  },

  onClearHandled() {
    const self = this;
    wx.showModal({
      title: '恢复已处理记录',
      content: '将清空本地「已处理 / 已忽略」标记，历史异常会重新出现在报警列表。',
      success: function (res) {
        if (!res.confirm) return;
        self._handled = {};
        saveHandled({});
        self.setData({ handledCount: 0 });
        self._refreshAlarms();
        wx.showToast({ title: '已恢复', icon: 'none' });
      }
    });
  },

  onGoAppsTap() { this.setData({ activeTab: 'apps' }); },

  /* ---------- 应用 Tab：搜索已发布流程并运行 ---------- */

  onKeywordInput(e) { this.setData({ keyword: e.detail.value }); },

  onClearKeyword() { this.setData({ keyword: '' }); this.onSearchApps(); },

  async onSearchApps() {
    if (this.data.appLoading) return;
    this.setData({ appLoading: true, appMsg: '' });
    try {
      const res = await monitor.searchApps(this.data.keyword.trim(), 1, APP_PAGE_SIZE);
      const apps = appUtil.formatApps(res.apps);
      this.setData({
        apps: apps,
        appTotal: Number(res.total) || 0,
        appPage: 1,
        appHasMore: apps.length < (Number(res.total) || 0),
        appLoading: false,
        appMsg: res.error ? '搜索失败：' + res.error : ''
      });
    } catch (err) {
      this.setData({ appLoading: false, appMsg: '搜索失败：' + (err.message || '网络异常') });
    }
  },

  async onLoadMoreApps() {
    if (this.data.appLoading || !this.data.appHasMore) return;
    const nextPage = this.data.appPage + 1;
    this.setData({ appLoading: true });
    try {
      const res = await monitor.searchApps(this.data.keyword.trim(), nextPage, APP_PAGE_SIZE);
      const merged = appUtil.mergeApps(this.data.apps, appUtil.formatApps(res.apps));
      this.setData({
        apps: merged,
        appPage: nextPage,
        appHasMore: merged.length < (Number(res.total) || 0),
        appLoading: false
      });
    } catch (err) {
      this.setData({ appLoading: false, appMsg: '加载更多失败：' + (err.message || '网络异常') });
    }
  },

  async onRefreshApps() {
    wx.showLoading({ title: '刷新目录', mask: true });
    try {
      const res = await monitor.refreshApps();
      wx.hideLoading();
      wx.showToast({
        title: res.success ? '目录已刷新：' + res.published + ' 个' : (res.msg || '刷新失败'),
        icon: 'none'
      });
      this.onSearchApps();
    } catch (err) {
      wx.hideLoading();
      wx.showToast({ title: '刷新失败', icon: 'none' });
    }
  },

  onAccountChange(e) { this.setData({ accountIndex: Number(e.detail.value) || 0 }); },

  onRunAppTap(e) {
    const d = e.currentTarget.dataset;
    if (!d.id) return;
    const account = appUtil.accountNameOf(this.data.botOptions, this.data.accountIndex);
    const self = this;
    wx.showModal({
      title: '运行这个流程？',
      content: '将在影刀生产环境真实启动「' + (d.name || '该流程') + '」' +
        (account ? '（机器人：' + account + '）' : '（由影刀自动分配机器人）') + '，请确认。',
      confirmText: '确认运行',
      confirmColor: '#534ab7',
      success: async function (res) {
        if (!res.confirm) return;
        wx.showLoading({ title: '正在启动', mask: true });
        try {
          const out = await monitor.startApp(d.id, account);
          wx.hideLoading();
          if (out.success) {
            wx.showToast({ title: '已启动', icon: 'none' });
            self.loadSnapshot();
          } else {
            wx.showToast({ title: out.msg || '启动失败', icon: 'none' });
          }
        } catch (err) {
          wx.hideLoading();
          wx.showToast({ title: '网络异常，启动失败', icon: 'none' });
        }
      }
    });
  },

  /* ---------- 设置 Tab ---------- */

  async loadSettings() {
    try {
      const res = await monitor.getSettings();
      this.setData({
        settings: res || {},
        settingsLoaded: true,
        allowControl: res.allowRemoteControl !== false
      });
    } catch (err) {
      this.setData({ settingsLoaded: true, credState: '读取设置失败：' + (err.message || '网络异常') });
    }
  },

  onBaseInput(e) { this.setData({ baseInput: e.detail.value }); },

  onSaveBase() {
    const base = C.setRestBase(this.data.baseInput);
    this.setData({ backendBase: base, baseInput: base, connState: '已保存，正在重连...' });
    if (this._conn) { this._conn.close(); this._conn = null; }
    this.connectWs();
    this.loadSnapshot();
    this.loadSettings();
    wx.showToast({ title: '后端地址已更新', icon: 'none' });
  },

  async onTestBase() {
    wx.showLoading({ title: '测试连接', mask: true });
    try {
      const res = await monitor.testConnection();
      wx.hideLoading();
      this.setData({ connState: '连接正常 · ' + (res.mock_mode ? 'MOCK 模式' : '真实影刀数据') });
    } catch (err) {
      wx.hideLoading();
      this.setData({ connState: '连接失败：' + (err.message || '请检查地址与网络') });
    }
  },

  onResetBase() {
    const base = C.clearRestBase();
    this.setData({ backendBase: base, baseInput: base, connState: '已恢复默认' });
    if (this._conn) { this._conn.close(); this._conn = null; }
    this.connectWs();
    this.loadSnapshot();
    this.loadSettings();
  },

  onKeyIdInput(e) { this.setData({ keyIdInput: e.detail.value }); },
  onKeySecretInput(e) { this.setData({ keySecretInput: e.detail.value }); },
  onTokenInput(e) { this.setData({ tokenInput: e.detail.value }); },

  async onSaveCredentials() {
    const key = String(this.data.keyIdInput || '').trim();
    const secret = String(this.data.keySecretInput || '').trim();
    if (!key || !secret) {
      wx.showToast({ title: 'ID 与 Secret 都要填', icon: 'none' });
      return;
    }
    wx.showLoading({ title: '保存中', mask: true });
    try {
      const out = await monitor.saveCredentials(key, secret, this.data.tokenInput);
      wx.hideLoading();
      if (out.success) {
        // Secret 只存在页面内存这一瞬，提交后立即清空；不写 storage、不进日志
        this.setData({ keySecretInput: '', tokenInput: '', credState: '已保存并生效' });
        wx.showToast({ title: '凭证已生效', icon: 'none' });
        this.loadSettings();
        this.loadSnapshot();
      } else {
        this.setData({ credState: out.msg || '保存失败' });
        wx.showToast({ title: out.msg || '保存失败', icon: 'none' });
      }
    } catch (err) {
      wx.hideLoading();
      this.setData({ credState: '保存失败：' + (err.message || '网络异常') });
      wx.showToast({ title: '保存失败', icon: 'none' });
    }
  },

  async onTestCredentials() {
    wx.showLoading({ title: '验证凭证', mask: true });
    try {
      const out = await monitor.testCredentials();
      wx.hideLoading();
      this.setData({ credState: out.success
        ? '凭证可用 · 机器人 ' + out.botCount + ' 台'
        : '凭证不可用：' + (out.msg || '影刀拒绝') });
    } catch (err) {
      wx.hideLoading();
      this.setData({ credState: '验证失败：' + (err.message || '网络异常') });
    }
  }
});
