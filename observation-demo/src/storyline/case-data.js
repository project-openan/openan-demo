// case-data.js — A2A-T 协作日志参考数据（与《故事线方案文档.md》§1.7/§2.7 同步维护）
// t 为历史排序源（仅保证数组顺序；回放事件时刻以 cases.js events 为准）；
// clock 为占位初始值（base+t），回放时钟由 cases.js CLOCKS 定稿值覆写
//（V5：时钟冻结为业务时间线定稿——工单1=02:18:05+173分、工单2=10:20:08+39分，
// 与回放编排解耦，见方案文档 0.2/0.6）。
// dir: request=请求 / response=响应
// V4 两工单重写：工单1（WO-20261024-7316，跨地市专线中断，含 Negotiation-T 协商、
// 不支持抢通——问题处置=WAIMO 调度处置）；工单2（WO-20261028-5829，跨地市SLA劣化，
// 无协商、仅抢通——问题处置=粤西SPN 隧道调优）。两案故障侧均为粤西（原文档标注矛盾勘误见方案文档 0.5）。
// message 为日志详情完整报文（POST 请求头 / SSE data: 原样呈现，白色等宽 pre-wrap），
// 消息体内时间/流水号已按故事线修正（工单1=2026-10-24 02:18:05；工单2=2026-10-28 10:20:08；
// 末条 Notification OSS流水号=WO-20261028-5829）
// V6.72（用户规格）：敏感信息脱敏——端口名内嵌的真实村名/客户名/街道名 逐段 *，
// 字数保持不变（不重排版）；同类脱敏见 AuthorizationTPanelV4（授权人）/NegotiationPanel 注释

export const CASE_EVENTS = {
  c1: {
    base: '02:18:05',
    events: [
      { t: 146, type: '检索', from: 'agent.waimo', to: 'agent.registry', summary: 'sum.c1.146' },
      { t: 155, type: 'Task-T', dir: 'request', from: 'agent.waimo', to: 'agent.zx', summary: 'sum.c1.155' },
      { t: 199, type: '检索', from: 'agent.zx', to: 'agent.registry', summary: 'sum.c1.199' },
      { t: 204, type: 'Task-T', dir: 'request', from: 'agent.zx', to: 'agent.yx', summary: 'sum.c1.204' },
      { t: 205, type: 'Task-T', dir: 'request', from: 'agent.zx', to: 'agent.yd', summary: 'sum.c1.205' },
      { t: 215, type: 'Negotiation-T', dir: 'request', from: 'agent.yx', to: 'agent.zx', summary: 'sum.c1.215' },
      { t: 240, type: 'Negotiation-T', dir: 'response', from: 'agent.zx', to: 'agent.yx', summary: 'sum.c1.240' },
      { t: 260, type: 'Task-T', dir: 'response', from: 'agent.yx', to: 'agent.zx', summary: 'sum.c1.260' },
      { t: 266, type: 'Task-T', dir: 'response', from: 'agent.yd', to: 'agent.zx', summary: 'sum.c1.266' },
      { t: 278, type: 'Task-T', dir: 'response', from: 'agent.zx', to: 'agent.waimo', summary: 'sum.c1.278' },
    ],
  },
  c2: {
    base: '10:20:08',
    events: [
      { t: 69, type: '检索', from: 'agent.waimo', to: 'agent.registry', summary: 'sum.c2.69' },
      { t: 74, type: 'Task-T', dir: 'request', from: 'agent.waimo', to: 'agent.zx', summary: 'sum.c2.74' },
      { t: 89, type: '检索', from: 'agent.zx', to: 'agent.registry', summary: 'sum.c2.89' },
      { t: 95, type: 'Task-T', dir: 'request', from: 'agent.zx', to: 'agent.yd', summary: 'sum.c2.95' },
      // V6.4（1020 文档 3.2.3 修订）：Task-T 任务对象 A端端口名未含子接口标识
      //（-ETH.409 删除）→ 粤西 发起 Negotiation-T 协商
      { t: 96, type: 'Task-T', dir: 'request', from: 'agent.zx', to: 'agent.yx', summary: 'sum.c2.96' },
      // 粤东（Z端端口唯一）的诊断结果响应；粤西 发起 Negotiation-T 协商补充子接口标识，
      // 工作台 补充 cvlan=409（V6.4，1020 文档 3.2.3 修订）——V6.11（用户规格）：粤东的
      // Task-T响应 等粤西协商结束后发送（回放 360..372），日志表按故事时序排列：
      // 协商请求 → 协商响应 → 粤东响应 → 粤西响应
      { t: 101, type: 'Negotiation-T', dir: 'request', from: 'agent.yx', to: 'agent.zx', summary: 'sum.c2.101' },
      { t: 102, type: 'Negotiation-T', dir: 'response', from: 'agent.zx', to: 'agent.yx', summary: 'sum.c2.102' },
      { t: 103, type: 'Task-T', dir: 'response', from: 'agent.yd', to: 'agent.zx', summary: 'sum.c2.103' },
      { t: 106, type: 'Task-T', dir: 'response', from: 'agent.yx', to: 'agent.zx', summary: 'sum.c2.106' },
      { t: 119, type: 'Task-T', dir: 'response', from: 'agent.zx', to: 'agent.waimo', summary: 'sum.c2.119' },
      // V6.4（1020 文档 3.2.3 修订）：抢通方案为「隧道调优」，涉及动网操作——先经
      // Authorization-T 完成动网操作授权（请求/响应），成功后粤西执行抢通
      { t: 120, type: 'Authorization-T', dir: 'request', from: 'agent.zx', to: 'agent.yx', summary: 'sum.c2.120' },
      { t: 121, type: 'Authorization-T', dir: 'response', from: 'agent.yx', to: 'agent.zx', summary: 'sum.c2.121' },
      { t: 130, type: 'Notification-T', from: 'agent.yx', to: 'agent.zx', summary: 'sum.c2.130' },
      { t: 141, type: 'Notification-T', from: 'agent.yx', to: 'agent.zx', summary: 'sum.c2.141' },
      { t: 160, type: 'Notification-T', from: 'agent.zx', to: 'agent.waimo', summary: 'sum.c2.160' },
    ],
  },
};

// 由参考数据生成日志行（badge/clock/from/to/summary/prompt 均为 i18n 键或格式串，
// 由渲染层 T() 按当前语言解析：badge/summary/路由=占位键；prompt=msg.<case>.<t> 报文键）
export function buildLogs(src, caseId) {
  const [h, m, s] = src.base.split(':').map(Number);
  const base = h * 3600 + m * 60 + s;
  return src.events.map((e) => {
    const tot = base + e.t;
    const p2 = (v) => String(Math.floor(v)).padStart(2, '0');
    const ms = String(Math.round((tot - Math.floor(tot)) * 1000)).padStart(3, '0');
    const badge = e.from === e.to
      ? 'badge.internal'
      : e.type === '检索'
        ? 'badge.search'
        : e.type === 'Notification-T'
          ? 'badge.notif'
          : ({ 'Task-T': 'badge.task', 'Negotiation-T': 'badge.neg', 'Authorization-T': 'badge.auth' }[e.type] || 'badge.task')
            + (e.dir === 'response' ? 'Resp' : 'Req');
    return {
      badge,
      clock: p2(Math.floor(tot / 3600)) + ':' + p2(Math.floor(tot / 60) % 60) + ':' + p2(Math.floor(tot) % 60) + '.' + ms,
      from: e.from,
      to: e.to,
      summary: e.summary,
      prompt: 'msg.' + caseId + '.' + e.t,
      step: e.step || null,
    };
  });
}

