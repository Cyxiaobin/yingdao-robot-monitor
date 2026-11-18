// 登录页：小程序入口。先问后端登录态，未登录才展示表单。
// 会话 token 只存本地 storage；密码不落盘、不进日志。
const C = require('../../utils/constants');
const monitor = require('../../services/monitor');

Page({
  data: {
    username: '',
    password: '',
    backendBase: '',
    baseInput: '',
    errorMsg: '',
    checking: true,
    logging: false,
    showBase: false
  },

  onLoad() {
    const base = C.getRestBase();
    this.setData({ backendBase: base, baseInput: base });
    this.checkSession();
  },

  async checkSession() {
    try {
      const me = await monitor.getMe();
      // AUTH_REQUIRED=0 的服务端直接放行；已登录的会话带着 token 进看板
      if (me.authEnabled === false || me.authenticated) {
        C.setAuth(me.token || C.getAuthToken(),
          { username: me.username || 'local', role: me.role || 'user' });
        this.goDashboard();
        return;
      }
    } catch (err) {
      this.setData({ errorMsg: '后端不可达，请检查下方地址与网络' });
    }
    this.setData({ checking: false });
  },

  goDashboard() {
    wx.reLaunch({ url: '/pages/dashboard/dashboard' });
  },

  onUserInput(e) { this.setData({ username: e.detail.value, errorMsg: '' }); },
  onPwdInput(e) { this.setData({ password: e.detail.value, errorMsg: '' }); },
  onBaseInput(e) { this.setData({ baseInput: e.detail.value }); },

  onToggleBase() { this.setData({ showBase: !this.data.showBase }); },

  onSaveBase() {
    const base = C.setRestBase(this.data.baseInput);
    this.setData({ backendBase: base, baseInput: base, errorMsg: '' });
    wx.showToast({ title: '后端地址已保存', icon: 'none' });
    this.checkSession();
  },

  async onSubmit() {
    const username = String(this.data.username || '').trim();
    const password = String(this.data.password || '');
    if (!username || !password) {
      this.setData({ errorMsg: '请填写账号与密码' });
      return;
    }
    this.setData({ logging: true, errorMsg: '' });
    try {
      const out = await monitor.login(username, password);
      this.setData({ logging: false, password: '' });
      if (!out.success) {
        this.setData({ errorMsg: out.msg || '账号或密码错误' });
        return;
      }
      C.setAuth(out.token || '', { username: out.username, role: out.role });
      if (out.mustChangePassword) {
        wx.showToast({ title: '首次登录请到设置里改密', icon: 'none' });
      }
      this.goDashboard();
    } catch (err) {
      this.setData({ logging: false, errorMsg: '登录失败：' + (err.message || '网络异常') });
    }
  }
});
