// 机器人详情页：基础信息 + 当前状态 + 运行日志 + 安全停止。
// 日志真实字段为 time / level / text / logId，统一由 utils/logs.js 映射成展示字段。
const monitor = require('../../services/monitor');
const { formatLogs, logsNotice } = require('../../utils/logs');

function decode(value) {
  try { return decodeURIComponent(value || ''); } catch (e) { return value || ''; }
}

Page({
  data: {
    uuid: '',
    name: '',
    ip: '',
    currentApp: '',
    status: '',
    statusLabel: '未知',
    statusColor: '#888780',
    statusBg: '#f1efe8',
    runId: '',
    runBot: '',
    jobUuid: '',
    logs: [],
    loading: true,
    errorMsg: ''
  },

  onLoad(options) {
    this.setData({
      uuid: decode(options.uuid),
      name: decode(options.name),
      ip: decode(options.ip),
      currentApp: decode(options.currentApp),
      status: decode(options.status),
      statusLabel: decode(options.statusLabel) || '未知',
      statusColor: decode(options.statusColor) || '#888780',
      statusBg: decode(options.statusBg) || '#f1efe8',
      runId: decode(options.runId),
      runBot: decode(options.runBot)
    });
    this.loadLogs();
  },

  onPullDownRefresh() {
    this.loadLogs(true);
  },

  async loadLogs(isRefresh) {
    try {
      const res = await monitor.fetchBotLogs(this.data.uuid);
      const rows = formatLogs(res.logs);
      this.setData({
        logs: rows,
        jobUuid: res.jobUuid || '',
        loading: false,
        errorMsg: logsNotice(rows, res.error)
      });
    } catch (err) {
      this.setData({ loading: false, errorMsg: err.message || '日志加载失败' });
    } finally {
      if (isRefresh) wx.stopPullDownRefresh();
    }
  },

  onRetryTap() {
    this.setData({ loading: true, errorMsg: '' });
    this.loadLogs();
  },

  onStopTap() {
    const { runId, runBot, uuid } = this.data;
    if (!runId) return;
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
          const out = await monitor.stopByTask(runId, runBot || uuid);
          wx.hideLoading();
          if (out.success) {
            wx.showToast({ title: '已发送停止指令', icon: 'none' });
            self.loadLogs();
          } else {
            wx.showToast({ title: out.msg || '停止失败', icon: 'none' });
          }
        } catch (err) {
          wx.hideLoading();
          wx.showToast({ title: '网络异常，停止失败', icon: 'none' });
        }
      }
    });
  }
});
