// 全局入口。WebSocket 连接由页面持有并在 onUnload 中关闭，不放全局，
// 避免页面销毁后仍有回调写入已卸载页面（E-09）。
App({
  globalData: {
    // 记录最后一次连接状态，供详情页展示
    connected: false
  },

  onLaunch() {
    // 登录态在 pages/login + utils/constants.js（自建账号体系，不调用 wx.login、
    // 不采集 openid/手机号）；阶段5 再在此处理订阅消息授权。
  }
});
