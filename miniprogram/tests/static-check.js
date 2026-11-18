// 静态自检：无需微信开发者工具，抓「页面四件套缺失 / 标签不配对 / 事件方法未定义 / require 路径错」。
// 运行：node miniprogram/tests/static-check.js
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const failures = [];
const notes = [];

function fail(msg) { failures.push(msg); }
function read(rel) { return fs.readFileSync(path.join(root, rel), 'utf8'); }
function exists(rel) { return fs.existsSync(path.join(root, rel)); }

// 1. app.json 页面四件套 + JSON 可解析
const appJson = JSON.parse(read('app.json'));
appJson.pages.forEach(function (page) {
  ['.js', '.json', '.wxml', '.wxss'].forEach(function (ext) {
    const rel = page + ext;
    if (!exists(rel)) fail('缺少页面文件: ' + rel);
    if (ext === '.json') JSON.parse(read(rel));
  });
});
notes.push('app.json 页面四件套: ' + appJson.pages.length + ' 个页面');

// 2. WXML 标签配对 + 事件方法存在性
let bindCount = 0;
appJson.pages.forEach(function (page) {
  const wxml = read(page + '.wxml');
  const js = read(page + '.js');

  const stripped = wxml.replace(/\{\{[\s\S]*?\}\}/g, '');
  const stack = [];
  const tagRe = /<(\/?)([a-zA-Z][\w-]*)([^>]*?)>/g;
  let m;
  while ((m = tagRe.exec(stripped)) !== null) {
    const closing = m[1] === '/';
    const name = m[2];
    const selfClose = m[3].trim().endsWith('/');
    if (closing) {
      const top = stack.pop();
      if (top !== name) fail(page + '.wxml 标签不匹配: 期望 </' + top + '>，实际 </' + name + '>');
    } else if (!selfClose) {
      stack.push(name);
    }
  }
  if (stack.length) fail(page + '.wxml 有未闭合标签: ' + stack.join(','));

  const bindRe = /(?:bind|catch)[a-z]*="([A-Za-z_$][\w$]*)"/g;
  let b;
  while ((b = bindRe.exec(wxml)) !== null) {
    bindCount++;
    const method = b[1];
    const defined = new RegExp('(^|[^\\w])' + method + '\\s*\\(').test(js) ||
      new RegExp('(^|[^\\w])' + method + '\\s*:').test(js);
    if (!defined) fail(page + '.wxml 绑定了未定义的方法: ' + method);
  }
});
notes.push('WXML 事件绑定检查: ' + bindCount + ' 个');

// 3. WXSS 花括号配对
['app.wxss', 'styles/variables.wxss'].concat(appJson.pages.map(p => p + '.wxss')).forEach(function (rel) {
  const css = read(rel);
  const open = (css.match(/\{/g) || []).length;
  const close = (css.match(/\}/g) || []).length;
  if (open !== close) fail(rel + ' 花括号不配对: ' + open + ' vs ' + close);
});

// 4. require 相对路径可解析
function walk(dir, out) {
  fs.readdirSync(path.join(root, dir), { withFileTypes: true }).forEach(function (entry) {
    const rel = dir + '/' + entry.name;
    if (entry.isDirectory()) walk(rel, out);
    else if (entry.name.endsWith('.js')) out.push(rel);
  });
  return out;
}
const jsFiles = walk('.', []).filter(function (rel) { return !rel.startsWith('./tests'); });
let requireCount = 0;
jsFiles.forEach(function (rel) {
  const src = read(rel);
  const reqRe = /require\(['"](\.[^'"]+)['"]\)/g;
  let r;
  while ((r = reqRe.exec(src)) !== null) {
    requireCount++;
    const target = path.resolve(path.dirname(path.join(root, rel)), r[1]);
    if (!fs.existsSync(target) && !fs.existsSync(target + '.js')) {
      fail(rel + ' 引用了不存在的模块: ' + r[1]);
    }
  }
});
notes.push('模块 require 检查: ' + requireCount + ' 处');

// 5. 小程序端不得出现影刀密钥「值」明文。
//    字段名（设置页表单参数 accessKeyId / accessKeySecret）是允许且必需的，只拦硬编码的值。
const SECRET_VALUE_RE = /(?:accessKeyId|accessKeySecret|YINGDAO_ACCESS_KEY_SECRET)\s*[:=]\s*['"][A-Za-z0-9@_-]{20,}['"]/i;
const KNOWN_SECRET_FRAGMENTS = ['AKDEMO', 'SECdemo99'];
jsFiles.forEach(function (rel) {
  const src = read(rel);
  if (SECRET_VALUE_RE.test(src)) {
    fail(rel + ' 疑似硬编码影刀密钥值，密钥必须只存在于后端 .env');
  }
  KNOWN_SECRET_FRAGMENTS.forEach(function (frag) {
    if (src.indexOf(frag) >= 0) fail(rel + ' 出现真实凭证片段');
  });
});
notes.push('密钥明文检查: 通过（字段名允许，值禁止）');

// 6. 微信开发者工具项目配置：从项目根目录导入时也必须能找到 app.json
//    历史上出现过 code 10005「app.json 在项目根目录未找到」，根因是缺 miniprogramRoot。
const projectRoot = path.resolve(root, '..');
const pubCfgPath = path.join(projectRoot, 'project.config.json');
if (fs.existsSync(pubCfgPath)) {
  const pub = JSON.parse(fs.readFileSync(pubCfgPath, 'utf8'));
  if (!pub.miniprogramRoot) {
    fail('项目根 project.config.json 缺少 miniprogramRoot，会报 app.json 未找到 (code 10005)');
  } else if (!fs.existsSync(path.join(projectRoot, pub.miniprogramRoot, 'app.json'))) {
    fail('miniprogramRoot 指向的目录里没有 app.json: ' + pub.miniprogramRoot);
  }
  if (pub.setting && pub.setting.urlCheck !== false) {
    fail('project.config.json 的 urlCheck 应关闭，否则 HTTP 局域网地址被拦');
  }
  const privCfgPath = path.join(projectRoot, 'project.private.config.json');
  if (fs.existsSync(privCfgPath)) {
    const priv = JSON.parse(fs.readFileSync(privCfgPath, 'utf8'));
    if (priv.setting && priv.setting.urlCheck !== false) {
      fail('project.private.config.json 的 urlCheck 为 true，会覆盖公共配置导致请求被拦');
    }
  }
  notes.push('项目配置检查: miniprogramRoot / urlCheck 通过');
}

// 7. 新版看板结构：4 Tab / 三段筛选 / 9 个新端点接线
function assertMarkers(src, list, label) {
  list.forEach(function (marker) {
    if (src.indexOf(marker) < 0) fail(label + ' 缺少标记: ' + marker);
  });
}
assertMarkers(read('pages/dashboard/dashboard.wxml'), [
  'data-tab="board"', 'data-tab="alarm"', 'data-tab="apps"', 'data-tab="settings"',
  'data-segment="bots"', 'data-segment="running"', 'data-segment="done"',
  'drawer-mask', 'search-bar', 'form-input'
], 'dashboard.wxml');
assertMarkers(read('services/monitor.js'), [
  '/api/apps/search', '/api/apps/refresh', '/api/control/start',
  '/api/control/retry', '/logs', '/api/settings', '/api/settings/test',
  '/api/settings/credentials', 'X-Admin-Token'
], 'services/monitor.js');
assertMarkers(read('utils/segments.js'), ['filterRuns', 'segmentTitle'], 'utils/segments.js');
notes.push('新版看板结构检查: 4 Tab / 三段筛选 / 新端点接线 通过');

// 8. WXML 条件链：wx:elif / wx:else 必须紧跟条件块，中间夹注释会导致编译失败
const rawWxml = read('pages/dashboard/dashboard.wxml');
const cleanWxml = rawWxml.replace(/<!--[\s\S]*?-->/g, '');
const elifCount = (cleanWxml.match(/<block wx:elif=/g) || []).length;
const elifLinked = (cleanWxml.match(/<\/block>\s*<block wx:elif=/g) || []).length;
if (elifCount !== elifLinked) {
  fail('dashboard.wxml 有 wx:elif 未紧跟上一个条件块（检查中间注释）');
}
if (!/<\/block>\s*<block wx:else>/.test(cleanWxml)) {
  fail('dashboard.wxml 的 wx:else 未紧跟条件块（检查中间注释）');
}
if (!/<\/view>\s*<view wx:else class="card">/.test(cleanWxml)) {
  fail('dashboard.wxml 三段筛选的 wx:else 未紧跟 wx:if（检查中间注释）');
}
notes.push('WXML 条件链检查: wx:if / wx:elif / wx:else 连续 通过');

// 9. 登录与账号管理（2026-11-17）：入口页 / 会话头 / 管理员专属区块 / 仅当天
assertMarkers(read('pages/dashboard/dashboard.wxml'), [
  '账号管理 · 仅超级管理员', 'data-tab="settings"', 'onLogout',
  'onAddUser', 'onDeleteUser', 'onChangePassword', 'scopeLabel', '仅展示当天'
], 'dashboard.wxml 账号区块');
assertMarkers(read('services/monitor.js'), [
  '/api/auth/login', '/api/auth/me', '/api/auth/logout',
  '/api/auth/password', '/api/auth/users', 'Authorization'
], 'services/monitor.js 鉴权');
assertMarkers(read('utils/constants.js'), ['setAuth', 'clearAuth', 'getWsHeaders'], 'utils/constants.js');
assertMarkers(read('utils/today.js'), ['filterFormatted', 'scopeLabel'], 'utils/today.js');
assertMarkers(read('utils/format.js'), ['filterFormatted'], 'utils/format.js');
assertMarkers(read('pages/login/login.wxml'), ['onSubmit', 'onSaveBase'], 'pages/login/login.wxml');
if (appJson.pages[0] !== 'pages/login/login') {
  fail('app.json 首页必须是登录页，未登录用户不能先看到看板');
}
// 加高后的底部导航：容器与内容区留白必须同步，否则最后一张卡片被遮住
const dashWxss = read('pages/dashboard/dashboard.wxss');
if (!/padding:\s*24rpx 0 calc\(24rpx \+ env\(safe-area-inset-bottom\)\)/.test(dashWxss)) {
  fail('dashboard.wxss 底部 Tab 未按截图反馈加高（应 padding 24rpx）');
}
if (!/padding-bottom:\s*220rpx/.test(dashWxss)) {
  fail('dashboard.wxss 内容区底部留白未同步加高（应 220rpx）');
}
notes.push('登录 / 账号管理 / 仅当天 / 导航栏加高 结构检查: 通过');

notes.forEach(function (n) { console.log('  ok  ' + n); });
if (failures.length) {
  failures.forEach(function (f) { console.error('  FAIL  ' + f); });
  console.error('\n静态自检失败：' + failures.length + ' 项');
  process.exit(1);
}
console.log('\n静态自检全部通过');
