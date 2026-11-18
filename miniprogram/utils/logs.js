// 影刀真实日志字段：time / level（中文「信息」「错误」）/ text / logId。
// WXML 不能调用函数，统一在这里转成可直接绑定的展示字段。
function formatLogs(rows) {
  return (rows || []).map(function (row, index) {
    const level = row.level || '';
    return {
      logId: row.logId || index,
      time: row.time || '',
      level: level,
      content: row.text || row.content || '',
      isError: /错误|异常|error|fail/i.test(level)
    };
  });
}

// 后端在机器人离线/任务过期时会把影刀错误降级成 { logs: [], error }。
// 有日志就不提示；无日志才把原因转成一条可读提示，避免详情页空白无解释。
function logsNotice(rows, error) {
  if (rows && rows.length) return '';
  if (!error) return '';
  return '日志暂不可用：' + String(error).slice(0, 60);
}

module.exports = { formatLogs, logsNotice };
