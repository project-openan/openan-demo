// SubStepPanels.jsx — 能开平台节点卡（替代注册中心设计节点）+ 子步骤执行期详情面板
// V3.7：组件源自 A2A-T移动样板间展屏设计-V3.1/react-panels（复制入 src/components/panels/）；
// 平台卡 144×142 中心与原注册中心节点中心重合（441,305），reg-* 检索线起点随之改锚卡右缘 514；
// 详情面板触发（回放态）：WAIMO mini0=投诉识别→意图识别 / mini2=调度处置→调度处置、
// ZX mini1=动态编排→动态编排、检索线激活→检索智能体（置于平台卡右侧）；
// V3.13：Task-T 面板与 Notification-T 面板（原均在连线盒水平居中、下缘 +12px）；
// V3.22：Task-T 窗口延展为 任务下发→编排完成 并左移避让 ZX 卡迷你芯片（见 taskTWindow）、
// 检索/Task-T/意图面板动态分步（面板内部时钟 useStageClock / 选中渐显）；
// 面板外层 satCssStyle 锚对应卡集群中心（收起/展开随卡刚体平移），内层 st-panel-in 入场动画
import React from 'react';
import { CARDS, LINES, satCssStyle } from '../roles';
import { CASES, TIME_SCALE } from '../cases';
import { taskTWindowOf, searchWindowOf, orchestrationWindowOf, notifWindowOf, dispatchWindowOf, intentWindowOf, authorizationWindowOf } from '../panel-timing';
import PlatformNodeCard from '../../components/panels/PlatformNodeCard.jsx';
import IntentRecognitionPanel from '../../components/panels/IntentRecognitionPanel.jsx';
import SearchAgentPanel from '../../components/panels/SearchAgentPanel.jsx';
import AuthorizationTPanel from '../../components/panels/AuthorizationTPanel.jsx';
import DispatchPanel from '../../components/panels/DispatchPanel.jsx';
import DynamicOrchestrationPanel from '../../components/panels/DynamicOrchestrationPanel.jsx';
import TaskTPanel from '../../components/panels/TaskTPanel.jsx';
import NotificationTPanel from '../../components/panels/NotificationTPanel.jsx';
import '../../components/panels/panels.css';

const center = (b) => ({ x: b.x + b.w / 2, y: b.y + b.h / 2 });

// 能开平台（快照/回放常驻）；V5.57（用户规格）：平台卡下边沿距注册中心子卡 0.75rem
//（子卡底 114 + 12 → 高 142→126）
const PLATFORM = { x: 369, y: 234, w: 144, h: 126 };

// WAIMO—专线 两卡中心中点（Task-T / Notification-T 面板锚点，随两侧卡片刚体平移）
const WZ_MID = (() => {
  const a = center(CARDS.WAIMO.box), b = center(CARDS.ZX.box);
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
})();

// 连线下方面板盒：连线盒水平居中、下缘 +12px
const belowLine = (key, w, h) => {
  const b = LINES[key].box;
  return { x: Math.round(b.x + b.w / 2 - w / 2), y: Math.round(b.y + b.h + 12), w, h };
};

// 子步骤详情面板（回放态，执行到对应子步骤/连线激活期时呈现）
// V3.15：检索面板拆分两处——WAIMO 检索（reg-waimo-search）在平台卡右侧、选中「专线投诉处理智能体」；
// 专线检索（reg-zx-search）在专线卡正下方、选中「粤东/粤西」（V4：两案例均双登场均选中两个）
// V4：意图识别/Task-T/调度处置/Notification-T 面板注入 caseId——文案随案例切换（工单1/工单2）
const PANEL_DEFS = [
  {
    // V3.21：意图识别面板分步动态（输入→Reasoning→Action→Observation→输出）——
    // 传入激活窗口与播放上下文（t/mode/speed），面板内部时钟按窗口进度推进；
    // V3.28：WAIMO 卡增高至 252（底缘 691），面板自 677 下移至 699 避让；
    // V5.57：WAIMO 卡高与专线一致（290，底缘 729），面板 699→729 避让；
    // V5.2（回退此前逻辑）：信息顺时针依次渐入、常驻累计，左侧输入三行整体出现（不分开显示），
    // 各段 12 业务秒；窗口 = mini0 全窗（12..72，全部展示完成后才进入定界定位）。
    // V5.2：定界定位无详情面板——内容在 WAIMO 卡底描述区 4 句依次出现（cases.js desc 事件）
    key: 'intent', Comp: IntentRecognitionPanel,
    props: (pub) => ({ ...intentWindowOf(CASES[pub.caseId]), t: pub.t, mode: pub.mode, speed: pub.speed, timeScale: TIME_SCALE, caseId: pub.caseId }),
    when: (w, pub) => { const { t0, t1 } = intentWindowOf(CASES[pub.caseId]); return pub.t >= t0 && pub.t < t1; },
    box: { x: 580, y: 729, w: 498, h: 232 }, anchor: () => center(CARDS.WAIMO.box),
  },
  {
    // V3.30：调度处置面板三段分步（①手机 → ②左侧消息气泡 → ③右侧回复气泡）；
    // V4：仅工单1 挂载（WAIMO 调度处置·现场上站修复；工单2 问题处置=粤西SPN 抢通，无此面板）；
    // V5.57：随 WAIMO 卡高 290（底缘 729）下移 699→729 避让
    key: 'dispatch', Comp: DispatchPanel,
    props: (pub) => ({ ...dispatchWindowOf(CASES[pub.caseId]), t: pub.t, mode: pub.mode, speed: pub.speed, timeScale: TIME_SCALE, caseId: pub.caseId }),
    when: (w, pub) => { const { t0, t1 } = dispatchWindowOf(CASES[pub.caseId]); return pub.t >= t0 && pub.t < t1; },
    box: { x: 733, y: 729, w: 192, h: 352 }, anchor: () => center(CARDS.WAIMO.box),
  },
  {
    // V3.27：动态编排面板三段分步（左侧元素 → 编排引擎 → 右侧元素）；窗口 = mini1 激活
    // → mini2（任务诊断）激活——分步在下一子步骤开始前完成（面板消失即下一子步骤开始）；
    // V5.56（用户规格）：图示距标题/左右/下边沿均 1rem——内容整体上移 20（图示顶 49=标题底
    // 33+16）、面板高 218→201（图示底 185+16）
    key: 'orchestration', Comp: DynamicOrchestrationPanel,
    props: (pub) => ({ ...orchestrationWindowOf(CASES[pub.caseId]), t: pub.t, mode: pub.mode, speed: pub.speed, timeScale: TIME_SCALE }),
    when: (w, pub) => { const { t0, t1 } = orchestrationWindowOf(CASES[pub.caseId]); return pub.t >= t0 && pub.t < t1; },
    box: { x: 1011, y: 701, w: 574, h: 201 }, anchor: () => center(CARDS.ZX.box),
  },
  {
    // V3.22：检索面板动态选中（相位驱动，窗口=连线激活期+4 业务秒）——前半未选，
    // 后半目标项高亮渐显；seek 挂载按相位直接落位
    key: 'search-waimo', Comp: SearchAgentPanel,
    props: (pub) => ({ ...searchWindowOf(CASES[pub.caseId], 'reg-waimo-search'), t: pub.t, mode: pub.mode, speed: pub.speed, timeScale: TIME_SCALE, selected: ['zx'] }),
    when: (w, pub) => { const { t0, t1 } = searchWindowOf(CASES[pub.caseId], 'reg-waimo-search'); return pub.t >= t0 && pub.t < t1; },
    box: { x: 521, y: 234, w: 236, h: 194 }, anchor: () => center(PLATFORM),
  },
  {
    // V3.19：专线检索面板置于检索结果文字（命中：粤东、粤西SPN…，胶囊右侧 1042..1235 × 280..296）
    // 下方（顶 306）；右缘收敛至 1132 避让专线卡左上角徽章/标题（卡左缘 1136）
    key: 'search-zx', Comp: SearchAgentPanel,
    props: (pub) => ({ ...searchWindowOf(CASES[pub.caseId], 'reg-zx-search'), t: pub.t, mode: pub.mode, speed: pub.speed, timeScale: TIME_SCALE, selected: ['yd', 'yx'] }),
    when: (w, pub) => { const { t0, t1 } = searchWindowOf(CASES[pub.caseId], 'reg-zx-search'); return pub.t >= t0 && pub.t < t1; },
    box: { x: 896, y: 306, w: 236, h: 194 },
    anchor: () => ({ x: (center(PLATFORM).x + center(CARDS.ZX.box).x) / 2, y: (center(PLATFORM).y + center(CARDS.ZX.box).y) / 2 }),
  },
  {
    // V3.24：Task-T 面板窗口 = 任务下发 → 专线首个内部子步骤开始（面板消失后子步骤才执行，
    // 见 taskTWindowOf），8 段分步动态 + 滚动跟随；位置自连线居中左移至右缘齐 ZX 卡左缘
    // （778..1136），不与专线卡迷你步骤/描述区域重叠；
    // V5.56（用户规格）：面板距连线 0.25rem（waimo-zx-task 线底 549.5+4 → top 562→554）、
    // 面板高 20.5rem（328）
    key: 'task-t', Comp: TaskTPanel,
    props: (pub) => ({ ...taskTWindowOf(CASES[pub.caseId]), t: pub.t, mode: pub.mode, speed: pub.speed, timeScale: TIME_SCALE, caseId: pub.caseId }),
    when: (w, pub) => { const { t0, t1 } = taskTWindowOf(CASES[pub.caseId]); return pub.t >= t0 && pub.t < t1; },
    box: { x: 778, y: 554, w: 358, h: 328 }, anchor: () => WZ_MID,
  },
  {
    // V3.27：Notification-T 面板三段分步（抢通前 → 箭头 → 抢通后）；窗口 = waimo-zx-notif
    // 连线激活 → WAIMO mini3（投诉闭环）激活——分步完成后投诉闭环才开始
    // V4：仅工单2 挂载（粤西抢通·隧道调优前后对比；工单1 无 Notification-T 消息）
    key: 'notif-t', Comp: NotificationTPanel,
    props: (pub) => ({ ...notifWindowOf(CASES[pub.caseId]), t: pub.t, mode: pub.mode, speed: pub.speed, timeScale: TIME_SCALE, caseId: pub.caseId }),
    when: (w, pub) => { const { t0, t1 } = notifWindowOf(CASES[pub.caseId]); return pub.t >= t0 && pub.t < t1; },
    box: belowLine('waimo-zx-notif', 352, 236), anchor: () => WZ_MID,
  },
  {
    // V5.13：Authorization-T 面板「动网操作预授权检查」（仅工单2）——V5.17（用户规格）：
    // 专线根因总结汇总回传完成后、粤西抢通执行开始前呈现（面板消失后才开始抢通执行），
    // 流程图 3 段：①抢通方案生成 → ②查询预授权策略 → ③剩余元素同时出现
    // （是/否+箭头连线+执行动网操作/人工授权），主干/「是」分支箭头流动虚线；
    // 定位于粤西卡左侧（右缘距卡 12px、上缘避让专线卡迷你步骤/描述区与协商回程线；
    // V5.11 面板去除「授权策略下发」后高 302→246，下缘不再触及日志表）；
    // 锚定粤西卡中心随集群平移
    key: 'authorization-t', Comp: AuthorizationTPanel,
    props: (pub) => ({ ...authorizationWindowOf(CASES[pub.caseId]), t: pub.t, mode: pub.mode, speed: pub.speed, timeScale: TIME_SCALE, caseId: pub.caseId }),
    when: (w, pub) => { const { t0, t1 } = authorizationWindowOf(CASES[pub.caseId]); return pub.t >= t0 && pub.t < t1; },
    box: { x: 1254, y: 678, w: 336, h: 246 }, anchor: () => center(CARDS.YX.box),
  },
];

export default function SubStepPanels({ world, pub }) {
  const active = world ? PANEL_DEFS.filter((p) => p.when(world, pub)) : [];
  return (
    <>
      {/* 能开平台节点卡（注册中心为其内嵌子卡）；V3.14：z-index 40——画布覆盖层内最高，
          V5.53：容器 .st-zoomwrap 提升至 z-index 40（transform 层叠上下文曾使面板整体
          低于工具条/日志表/把手等 .st-layer，被 A2A-T 日志表遮挡）——详情面板全页最高 */}
      <div style={{ position: 'absolute', left: PLATFORM.x, top: PLATFORM.y, width: PLATFORM.w, height: PLATFORM.h,
        zIndex: 40, ...satCssStyle(pub, PLATFORM, center(PLATFORM)) }}>
        <PlatformNodeCard />
      </div>
      {/* 子步骤详情面板（全页最高层级，不被遮挡）；props 可为对象或 (pub)=>对象 */}
      {active.map((p) => {
        const pr = typeof p.props === 'function' ? p.props(pub) : p.props
        return (
          <div key={p.key} style={{ position: 'absolute', left: p.box.x, top: p.box.y, width: p.box.w, height: p.box.h,
            zIndex: 40, ...satCssStyle(pub, p.box, p.anchor()) }}>
            <div className="st-panel-in" style={{ width: '100%', height: '100%' }}>
              <p.Comp {...pr} />
            </div>
          </div>
        )
      })}
    </>
  );
}
