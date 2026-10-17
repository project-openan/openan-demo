import React from 'react'
import useStageClock from './useStageClock.js'

/* SearchAgentPanel — 检索智能体面板（源自 react-panels）
   V3.15：selected 属性控制选中项（glass 高亮）——
   WAIMO 检索（reg-waimo-search）命中 专线投诉处理智能体 → ['zx']（默认，原版式）；
   专线检索（reg-zx-search）命中 粤东/粤西 → ['yd','yx']（案例二粤西不登场 → ['yd']）
   V3.22 动态选中（相位驱动，与意图/Task-T 面板同一分步时钟）：窗口前半（相位<50%）
   全未选（plain），后半目标项高亮渐显（--glass 过渡：边框/文字色 + 渐变垫层透明度，
   末态与静态版式一致）；seek 挂载按相位直接落位 */
const OPTIONS = [
  { key: 'yd', label: '粤东SPN网络内生智能', top: 8, pad: 19 },
  { key: 'yx', label: '粤西SPN网络内生智能', top: 40, pad: 19 },
  { key: 'zx', label: '专线投诉处理智能体', top: 72, pad: 20 },
]

export default function SearchAgentPanel({ selected = ['zx'], ...clock }) {
  const stage = useStageClock(clock, 2)
  return (
    <div className="glass-panel" style={{ width: 236, height: 194 }}>
      {/* 标题区（青色系）；V5.57（用户规格）：标题文字规格——Microsoft YaHei bold
          0.7rem/1.1rem、letter-spacing 0、左对齐（内联覆盖 .p-title-text 通用样式） */}
      <div className="p-title-bar" style={{ left: 16, top: 14, background: '#7DDFE7' }} />
      <div className="p-title-text p-title-text--gradient" style={{ left: 26, top: 11, fontFamily: 'Microsoft YaHei', fontWeight: 'bold', fontSize: '0.7rem', lineHeight: '1.1rem', letterSpacing: '0rem', textAlign: 'left' }}>检索智能体</div>
      <div className="p-subtitle" style={{ left: 16, top: 41 }}>根据名称、描述和技能检索AgentCard</div>

      {/* 单选按钮组 */}
      <div className="radio-group" style={{ left: 36, top: 69, width: 164, height: 108 }}>
        {OPTIONS.map((o) => {
          const sel = stage >= 2 && selected.includes(o.key)
          return (
            <div
              key={o.key}
              className={sel ? 'radio-option radio-option--glass' : 'radio-option radio-option--plain'}
              style={{ left: 8, top: o.top, width: 148, height: 28, paddingLeft: o.pad }}
            >
              {o.label}
            </div>
          )
        })}
      </div>
    </div>
  )
}
