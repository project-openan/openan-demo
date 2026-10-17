// IntentRecognitionPanel.jsx — 投诉识别：意图识别（ReAct 推理环）
// V3.21 动态分步呈现：面板随 WAIMO mini0 激活窗口挂载，内容按窗口进度渐入——
// 已出现的步骤常驻累计，窗口末态 = 设计全量版式；中央 LLM 图标与面板标题常驻，
// 外圈白色箭头持续绕行。
// V3.22：步进时钟抽为 useStageClock 共享；V3.23：步进节奏改权重制（INTENT_WEIGHTS，
// 与 panel-timing/单步节拍同源）。
// V5.2（用户规格，回退此前逻辑）：信息**顺时针依次出现**、常驻累计——
// ①输入（标题+箭头+三行投诉文本整体出现，左侧输入不做分开显示）
// → ②Reasoning（上）→ ③Action（右）→ ④Observation（下，绕光轮顺时针）
// → ⑤输出；各段 12 业务秒（1x 回放 3 观众秒），全部展示完成后才进入定界定位。
import React from 'react'
import useStageClock from './useStageClock.js'
import { INTENT_WEIGHTS } from '../../storyline/panel-timing.js'

// V4：输入/输出文案随案例切换（工单1 不可用 / 工单2 质差——原文档全文）
const CASE_INPUT = {
  c1: [
    '投诉现象：客户表示广州至深圳的专线没法使用，但不能确定是哪个地方的问题，要求师傅尽快检测处理。',
    '产品类型：传输专线',
    '接入方式：传输',
  ],
  c2: [
    '投诉现象：客户表示专线使用感知差，网络间歇性卡顿、丢包，业务时断时续，影响业务使用。',
    '产品类型：传输专线',
    '接入方式：传输',
  ],
}
const CASE_OUTPUT = { c1: '传输专线不可用投诉场景', c2: '传输专线质差投诉场景' }

export default function IntentRecognitionPanel(props) {
  const step = useStageClock(props, 5, INTENT_WEIGHTS)
  const on = (k) => (step >= k ? ' ir-on' : '')
  const items = CASE_INPUT[props.caseId === 'c2' ? 'c2' : 'c1']
  return (
    <div className="glass-panel" style={{ width: 498, height: 232 }}>
      <div className="p-title-bar" style={{ left: 16, top: 14 }} />
      <div className="p-title-text" style={{ left: 26, top: 11 }}>投诉识别：意图识别</div>

      {/* 中央 LLM 图标常驻 + 外圈白色箭头独立图层（顺时针绕行，见 panels.css .orb-arrows） */}
      <img
        className="p-abs"
        src="/assets/orb.svg"
        alt=""
        style={{ left: 186.69, top: 39.25, width: 171.48, height: 171.48 }}
      />
      <img
        className="p-abs orb-arrows"
        src="/assets/orb-arrows.svg"
        alt=""
        style={{ left: 186.69, top: 39.25, width: 171.48, height: 171.48 }}
      />
      <div className="orb-label" style={{ left: 232, top: 136 }}>LLM React</div>

      {/* ① 输入：标题+箭头+三行投诉文本整体渐入（左侧输入不分开显示） */}
      <div className={'p-io-title ir-reveal' + on(1)} style={{ left: 28, top: 96 }}>输入：用户投诉文本</div>
      <svg className={'p-abs ir-reveal' + on(1)} style={{ left: 28, top: 112 }} width="185" height="16" viewBox="0 0 185 16" fill="none">
        <path d="M0 8 H176" stroke="#715AFB" strokeWidth="2" strokeLinecap="round" />
        <path d="M170 3 L176 8 L170 13" stroke="#715AFB" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <ul className={'p-io-list ir-reveal' + on(1)} style={{ left: 28, top: 124, width: 172 }}>
        {items.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>

      {/* ② 推理（上）→ ③ 动作（右）→ ④ 观察（下）：绕光轮顺时针依次渐入
          （V5.32 用户规格：Reasoning/Action/Observation 改中文、标签旁说明文字删除） */}
      <div className={'p-pill ir-reveal' + on(2)} style={{ left: 168, top: 64, width: 73 }}>推理</div>
      <div className={'p-pill ir-reveal' + on(3)} style={{ left: 322, top: 100, width: 73 }}>动作</div>
      <div className={'p-pill ir-reveal' + on(4)} style={{ left: 190, top: 172, width: 80 }}>观察</div>

      {/* ⑤ 输出（末段） */}
      <div className={'p-io-title ir-reveal' + on(5)} style={{ left: 311, top: 165 }}>输出：投诉现象和投诉意图</div>
      <svg className={'p-abs ir-reveal' + on(5)} style={{ left: 271, top: 177 }} width="199" height="16" viewBox="0 0 199 16" fill="none">
        <path d="M0 8 H190" stroke="#09AA71" strokeWidth="2" strokeLinecap="round" />
        <path d="M184 3 L190 8 L184 13" stroke="#09AA71" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className={'p-io-sub ir-reveal' + on(5)} style={{ left: 311, top: 190 }}>{CASE_OUTPUT[props.caseId === 'c2' ? 'c2' : 'c1']}</div>
    </div>
  )
}
