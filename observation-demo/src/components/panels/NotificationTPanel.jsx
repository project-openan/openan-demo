import React from 'react'
import TBubble from './TBubble.jsx'
import useStageClock from './useStageClock.js'
import { NOTIF_WEIGHTS } from '../../storyline/panel-timing.js'
import { T, isEn } from '../../i18n'

/* NotificationTPanel — Notification-T 详细交互流程
   V6.13（用户规格）：布局样式同步 react-panels 源——nt-panel 流式版式：
    tdlg-head 标题行（次级标题白字）+ 气泡（margin 0.5rem 顶、V6.14 底 padding 1rem）+
   消息行 + 对比卡横排（8.5×7.5rem 卡 + 1rem 间距）+ 双箭头负边距居中桥接；
   文字内容与动画保留——V3.26 动态分步：①抢通前元素（消息行 + 抢通前对比卡）→
   ②箭头图标 → ③抢通后元素（渐入直接挂卡/箭头元素，inline-block 排布不变） */

// V6.70（用户规格）：删除「隧道状态」行——两卡各 2 行（时延/丢包率，i18n 键 nt.*）
const ROWS_BEFORE = [
  { label: 'nt.latency', value: '28ms', color: '#e7434a' },
  { label: 'nt.loss', value: '0.9%', color: '#e7434a' },
]

const ROWS_AFTER = [
  { label: 'nt.latency', value: '5ms', color: '#36c18d' },
  { label: 'nt.loss', value: '0.01%', color: '#36c18d' },
]

// 对比卡（react-panels 版式：标题在头部条内——V6.14 修复标题独立于头部条之外时
// 把行区挤出固定高 7.5rem 卡片造成的越界重叠；cls 透传分步渐入）
function CompareCard({ cls, cardClass, headClass, title, titleColor, rows }) {
  return (
    <div className={'notif-card ' + cardClass + (cls ? ' ' + cls : '')}>
      <div className={'notif-card__head ' + headClass}>
        <div className="notif-card__title" style={{ color: titleColor }}>
          {title}
        </div>
      </div>
      <div className="notif-rows">
        {rows.map((r) => (
          <div className="notif-row" key={r.label}>
            <span className="notif-label">{T(r.label)}</span>
            <span className="notif-value" style={{ color: r.color }}>{r.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function NotificationTPanel(props) {
  const stage = useStageClock(props, 3, NOTIF_WEIGHTS)
  const on = (k) => (stage >= k ? ' ir-on' : '')
  // V6.70（用户规格）：删「隧道状态」行——卡 3→2 行、高 7.5→5.75rem，
  // 面板 14.75→13rem；箭头纵向居中随调（44→30px ≈ 卡中）
  // V6.82（用户规格）：EN 底部消息折两行（.nt-msg i18n.css）——面板高 13→14rem 容一行增量
  return (
      <div className="glass-panel tdialog nt-panel" style={{ width: '22rem', height: isEn() ? '14rem' : '13rem' }}>
      <div className="tdlg-head">
        <span className="tdlg-bar" style={{ background: '#715afb' }} />
        <span
          className="tdlg-title title-text--grad"
          style={{ backgroundImage: 'linear-gradient(90deg, #d5d3fd, #715afb)' }}
        >
          Notification-T
        </span>
        {/* V6.14（用户规格）：次级标题白字（原先继承暗灰看不清） */}
        <span className="tdlg-title" style={{ marginLeft: '0.6875rem', color: '#fff' }}>
          {T('lbl.interactDetails')}
        </span>
      </div>

      {/* V6.14（用户规格）：气泡底 padding 1rem——距最底部内容 1rem */}
      <TBubble width={320} tail="right" style={{ margin: '0.5rem 0 0 0', padding: '0.75rem 0 1rem 0.6875rem' }}>
        <div className={'nt-msg ir-reveal' + on(1)}>{T('nt.msg')}</div>
        <div className="nt-cards" style={{ marginTop: '0.5rem' }}>
          {/* ① 抢通前（V4/V5.26：down/28ms/丢包0.9%）｜③ 抢通后（up/5ms/丢包0.01%） */}
          <CompareCard
            cls={'ir-reveal' + on(1)}
            cardClass="notif-card--red"
            headClass="notif-card__head--red"
            title={T('nt.before')}
            titleColor="#e7434a"
            rows={ROWS_BEFORE}
          />
          <CompareCard
            cls={'ir-reveal' + on(3)}
            cardClass="notif-card--green"
            headClass="notif-card__head--green"
            title={T('nt.after')}
            titleColor="#36c18d"
            rows={ROWS_AFTER}
          />
          {/* ② 双箭头（负边距居中桥接抢通前→抢通后；V6.70 纵向居中随卡高 5.75rem 调整） */}
          <img
            className={'nt-arrow ir-reveal' + on(2)}
            src="/assets/ic-double-arrow.svg"
            alt=""
            style={{ marginLeft: '-10.125rem', marginTop: '1.875rem', width: '2.25rem', height: '2.01875rem' }}
          />
        </div>
      </TBubble>
    </div>
  )
}
