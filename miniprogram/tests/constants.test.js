const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../utils/constants');

test('normalizeBase 补协议、去尾斜杠、空值回退默认', () => {
  assert.equal(C.normalizeBase('192.168.1.5:8000/'), 'http://192.168.1.5:8000');
  assert.equal(C.normalizeBase('https://a.example.com/'), 'https://a.example.com');
  assert.equal(C.normalizeBase(''), C.REST_BASE);
});

test('wsUrlOf 正确把 http 转 ws、https 转 wss', () => {
  assert.equal(C.wsUrlOf('http://192.168.1.5:8000'), 'ws://192.168.1.5:8000/ws');
  assert.equal(C.wsUrlOf('https://a.example.com'), 'wss://a.example.com/ws');
});

test('Node 环境无 wx 时地址读取不报错', () => {
  assert.equal(C.getRestBase(), C.REST_BASE);
  assert.equal(C.getWsUrl(), C.WS_URL);
  assert.ok(C.getWsUrl().endsWith('/ws'));
});

test('默认地址是本机局域网 IP 而非示例占位符', () => {
  // 换 WiFi 只改 constants.js 的 IP，测试不绑定具体地址
  assert.ok(/^http:\/\/(\d{1,3}\.){3}\d{1,3}:8000$/.test(C.REST_BASE),
    '默认后端地址应为 http://<局域网IP>:8000');
  assert.ok(!C.REST_BASE.includes('your-domain.example.com'));
});
