// IntentRecognitionPanel.jsx — 投诉识别：意图识别（ReAct 推理环）
// V3.21 动态分步呈现：面板随 WAIMO mini0 激活窗口挂载，内容按窗口进度渐入——
// 已出现的步骤常驻累计，窗口末态 = 设计全量版式；中央 LLM 图标与面板标题常驻，
// 外圈白色箭头持续绕行。
// V5.2（用户规格，回退此前逻辑）：信息**顺时针依次出现**、常驻累计——
// ①输入（标题+箭头+三行投诉文本整体出现，左侧输入不做分开显示）
// → ②思考（上）→ ③行动（右）→ ④观察（下，绕光轮顺时针）
// → ⑤输出；各段 12 业务秒（1x 回放 3 观众秒），全部展示完成后才进入定界定位。
// V6.0（流式布局）：面板骨架改 fp-col（标题行流式）；正文 = 横向流式两栏
//（输入列 | 环形构图 | 输出列，列内容纵向流式、垂直居中）——中央 LLM 光轮与
// 三枚环节胶囊为 2D 环形构图（V5.2 顺时针版式），保持绝对定位于正文中心。
// V6.47（用户规格）：面板长度增加 0.5 倍（498→747）——光轮改面板水平居中
//（环心 = 中线 373.5），三胶囊随环整体右移 +101；左右文字区域随之放大
//（输入列 185→285、输出列 318→419，箭头分别延伸至光轮左缘 / 面板右内边沿）。
// V6.51（用户规格）：思考/行动 胶囊上方说明文字——随胶囊出现，
// 下一胶囊出现时消失；左缘与胶囊左缘对齐、下缘距胶囊 0.2rem、不超出面板可换行
//（.ir-note 样式同 io 列表文字）。
// V6.52（用户规格）：行动文字两段分展（第一段消失后第二段出现——步权重拆为六段，
// 见 panel-timing INTENT_WEIGHTS）；面板高度与元素垂直位置维持 V6.47 版
//（232、构图原位）——文字可超出面板标题（条）底部向上延伸（思考文字三行上探
// 标题条区，标题文字在左侧不遮挡）。
// V6.56（用户规格）：c1 同步补充——文案按案（c1 中断/某银行广深、c2 质差），
// 展示节奏两案一致。
// V6.70（用户规格）：面板加高 232→240——输出末行（产品编号行）距面板下边沿
// 0.5rem（8px）；底锚说明文字 bottom 随体高 +8（绝对位置不变：199−胶囊顶+3.2）、
// 输入列包裹层冻结原体高 191（垂直居中不随加高下移 4px）
import React from 'react'
import useStageClock from './useStageClock.js'
import { INTENT_WEIGHTS } from '../../storyline/panel-timing.js'
import { T, isEn } from '../../i18n'

// V4：输入/输出文案随案例切换（工单1 不可用 / 工单2 质差）——值为 i18n 占位键（ir.*）
// V6.32：导出 CASE_INPUT——工单展开详情面板（OrderPanel）的工单描述/归属地市/
// 归属区县 与本面板投诉现象/客户所在地 同源一致
export const CASE_INPUT = {
  c1: ['ir.inPhen.c1', 'ir.inLoc.c1'],
  c2: ['ir.inPhen.c2', 'ir.inLoc.c2'],
}
const CASE_OUTPUT = { c1: 'ir.out.c1', c2: 'ir.out.c2' }
// V6.67（用户规格）：输出增行「产品编号」——行动定位段获取的两案同号
const PRODUCT_NO = '30122075634'

// 思考/行动 胶囊上方说明文字（文案按案定稿，i18n 键 ir.reason.* / ir.action.*）
const CASE_REASON = {
  c1: 'ir.reason.c1',
  c2: 'ir.reason.c2',
}
const CASE_ACTION = {
  c1: ['ir.action.1', 'ir.action.c1p2'],
  c2: ['ir.action.1', 'ir.action.c2p2'],
}

export default function IntentRecognitionPanel(props) {
  const ck = props.caseId === 'c2' ? 'c2' : 'c1'
  // V6.52/V6.56：六段（行动文字两段分展，两案统一）——
  // 输入1 → 思考2 → 行动一3 → 行动二4 → 观察5 → 输出6
  const step = useStageClock(props, 6, INTENT_WEIGHTS)
  const on = (k) => (step >= k ? ' ir-on' : '')
  const items = CASE_INPUT[ck]
  return (
    <div className="glass-panel fp-col" style={{ width: 747, height: 240 }}>
      <div className="fp-head">
        <div className="p-title-bar" />
        <div className="p-title-text">{T('ir.title')}</div>
      </div>

      <div className="fp-body">
        {/* 中央 LLM 图标常驻 + 外圈白色箭头独立图层（顺时针绕行，见 panels.css .orb-arrows）；
            环形构图绝对定位（y − fp-head 高 41，纵位 = 设计原值）；V6.47：光轮水平居中——
            left = (747−171.48)/2 = 287.76，环心 373.5 = 面板中线；
            .orb-arrows 旋转动画接管 transform，left 用绝对值定位 */}
        <img
          className="p-abs"
          src="/assets/orb.svg"
          alt=""
          style={{ left: 287.76, top: -1.75, width: 171.48, height: 171.48 }}
        />
        <img
          className="p-abs orb-arrows"
          src="/assets/orb-arrows.svg"
          alt=""
          style={{ left: 287.76, top: -1.75, width: 171.48, height: 171.48 }}
        />
        {/* V6.48（用户反馈「LLM ReAct 与图片重叠」）：标签置于光轮中央核心图形
            （svg 内 32×32 图标，体坐标 y 59..91）下方；V6.49：继续上移 94.2→91 */}
        <div className="orb-label" style={{ left: 333.5, top: 91 }}>LLM ReAct</div>

        {/* ② 思考（上）→ ③ 行动（右）→ ④ 观察（下）：绕光轮顺时针依次渐入
            （V5.32 用户规格：Reasoning/Action/Observation 改中文、标签旁说明文字删除；
             V5.69 用户规格：推理→思考、动作→行动、LLM React→LLM ReAct；
             环上时钟位 = 环顶 +24.75 / +60.75 / +132.75；
              V6.1 用户规格：三胶囊渐入提速 2 倍——ir-reveal--fast；
              V6.47：胶囊随光轮整体右移 +101（环心 272.4→373.5）） */}
        <div className={'p-pill ir-reveal ir-reveal--fast' + on(2)} style={{ left: 269, top: 23, width: 73 }}>{T('ir.think')}</div>
        <div className={'p-pill ir-reveal ir-reveal--fast' + on(3)} style={{ left: 423, top: 59, width: 73 }}>{T('ir.act')}</div>
        <div className={'p-pill ir-reveal ir-reveal--fast' + on(5)} style={{ left: 291, top: 131, width: 80 }}>{T('ir.observe')}</div>

        {/* V6.51/V6.52/V6.56（用户规格，两案）：思考/行动 胶囊上方说明文字——左缘与
            胶囊左缘对齐（思考 269 / 行动 423），下缘距胶囊 0.2rem（V6.70 bottom 锚定 =
            199 − 胶囊顶 + 3.2，随体高 +8 绝对位置不变，折行向上自适应），宽 = 面板右
            内边沿 731 − 左缘（不超出面板、可换行；可上探超出面板标题（条）底部——
            fp-body 无裁剪，思考文字三行上探标题条区，标题文字在左侧 x<269 不遮挡）；
            窗口化显示：思考文字 段2（行动胶囊出现即隐）、行动第一段 段3（第二段出现
            即隐）、行动第二段 段4（观察胶囊出现即隐）；文案按案（CASE_REASON/CASE_ACTION）；
            V6.83（用户规格）：EN 不展示 Reason/Action 说明文字（英文长句上探折行
            版式失衡）——仅 zh 渲染，胶囊/时序不变 */}
        {!isEn() ? (
          <>
            <div className={'ir-note' + (step === 2 ? ' ir-on' : '')}
              style={{ left: 269, bottom: 179.2, width: 462 }}>
              {T(CASE_REASON[ck])}
            </div>
            <div className={'ir-note' + (step === 3 ? ' ir-on' : '')}
              style={{ left: 423, bottom: 143.2, width: 308 }}>
              {T(CASE_ACTION[ck][0])}
            </div>
            <div className={'ir-note' + (step === 4 ? ' ir-on' : '')}
              style={{ left: 423, bottom: 143.2, width: 308 }}>
              {T(CASE_ACTION[ck][1])}
            </div>
          </>
        ) : null}

        {/* 正文横向流式：输入列（左，垂直居中）；输出改绝对定位（V6.1 用户规格：
            距观察胶囊 2rem——左缘 = 胶囊右缘 + 48，纵向对齐胶囊行）；
            V6.47：输入列随面板加宽 185→285（箭头延伸至光轮左缘）；
            V6.70：包裹层冻结原体高 191（面板加高后垂直居中不随之下移） */}
        <div className="fp-row" style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 191, padding: '0 1rem' }}>
          {/* ① 输入：标题+箭头+三行投诉文本整体渐入（左侧输入不分开显示） */}
          <div className={'fp-col--c ir-reveal' + on(1)} style={{ width: 285, height: '100%' }}>
            {/* V6.49（用户规格）：输入/输出 4 字加粗加大一号（.p-io-key）；
                箭头下方文字距箭头 0.1rem（marginTop 4→1.6） */}
            <div className="p-io-title" style={{ position: 'static' }}><span className="p-io-key">{T('ir.inputKey')}</span>{isEn() ? ': ' : '：'}{T('ir.inputBody')}</div>
            <svg width="285" height="16" viewBox="0 0 285 16" fill="none" style={{ display: 'block', marginTop: 2 }}>
              <path d="M0 8 H276" stroke="#715AFB" strokeWidth="2" strokeLinecap="round" />
              <path d="M270 3 L276 8 L270 13" stroke="#715AFB" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <ul className="p-io-list" style={{ position: 'static', marginTop: 1.6, width: 272 }}>
              {items.map((t) => (
                <li key={t}>{T(t)}</li>
              ))}
            </ul>
          </div>
        </div>
        {/* ⑤ 输出（末段）：观察胶囊右侧（V6.1 用户规格：2rem 基础上再右移 1rem——
            左缘 = 胶囊右缘 + 48 = 371 + 48 = 419），纵向对齐胶囊行
            （title 顶 ≈ 胶囊行上沿；箭头自胶囊右缘起左探）；
            V6.47：输出列随面板加宽右移至 419，箭头延伸至面板右内边沿（svg 347） */}
        {/* V6.67（用户规格）：输出增行「产品编号」——输出文字改 io 列表
            两行（样式/行距同输入列）；列顶 119→117（两行贴面板底内沿 190.6 ≤ 191），
            title 顶仍约对齐观察胶囊行上沿 */}
        <div className={'fp-col--c ir-reveal' + on(6)} style={{ position: 'absolute', left: 419, top: 117, alignItems: 'flex-start' }}>
          <div className="p-io-title" style={{ position: 'static' }}><span className="p-io-key">{T('ir.outputKey')}</span>{isEn() ? ': ' : '：'}{T('ir.outputBody')}</div>
          <svg width="347" height="16" viewBox="0 0 347 16" fill="none" style={{ display: 'block', marginTop: 2, marginLeft: -31 }}>
            <path d="M0 8 H338" stroke="#09AA71" strokeWidth="2" strokeLinecap="round" />
            <path d="M332 3 L338 8 L332 13" stroke="#09AA71" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <ul className="p-io-list" style={{ position: 'static', marginTop: 1.6, width: 308 }}>
            <li>{T(CASE_OUTPUT[ck])}</li>
            <li>{T('ir.productPrefix')}{PRODUCT_NO}</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
