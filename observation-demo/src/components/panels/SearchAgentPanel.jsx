import React from 'react'
import useStageClock from './useStageClock.js'
import { T, isEn } from '../../i18n'

/* SearchAgentPanel — 检索智能体面板
   V6.13（用户规格）：布局样式同步 react-panels 源——search-panel__* 流式版式：
   色条+渐变标题行（title-text--gradient 青色渐变）/ 副题 / 选项组（10.25×6.75rem
   组底铺色 + 9.25×1.75rem 选项纵向堆叠）；
   V6.15（用户规格）：面板刚出现时所有智能体均未选中（窗口前半全 plain），
   后半再出现选中效果（静态 glass 落位——V6.14 已删过渡/垫层动画，不再加回）；
   选中样式 = react-panels「专线投诉处置智能体」glass（蓝框+径向/线性渐变底+白字），
   未选中 = 粤东/粤西 plain 样式；
   V3.15 selected 属性保留（WAIMO 检索 → ['zx']、专线检索 → ['yd','yx']） */
const OPTIONS = [
  { key: 'yd', label: 'agent.yd' },
  { key: 'yx', label: 'agent.yx' },
  { key: 'zx', label: 'agent.zx' },
]

export default function SearchAgentPanel({ selected = ['zx'], ...clock }) {
  const stage = useStageClock(clock, 2)
  // V6.82（用户规格）：EN 副题折两行（.search-panel__subtitle i18n.css）——面板高 12.125→12.75rem
  return (
      <div className="glass-panel search-panel" style={{ width: '14.75rem', height: isEn() ? '12.75rem' : '12.125rem' }}>
      {/* 标题区（青色系） */}
      <div className="search-panel__head">
        <span className="search-panel__bar" />
        <span className="search-panel__title title-text--gradient">{T('se.title')}</span>
      </div>
      <div className="search-panel__subtitle">{T('se.subtitle')}</div>

      {/* 单选按钮组（react-panels 版式：组底铺色 + 选项纵向堆叠；
          前半全 plain → 后半选中项静态 glass，无过渡动画；
          V6.23（用户规格）：选项文字水平居中——去掉原左对齐不对称 padding） */}
      <div className="search-panel__group">
        {OPTIONS.map((o) => {
          const sel = stage >= 2 && selected.includes(o.key)
          return (
            <div
              key={o.key}
              className={'search-panel__option ' + (sel ? 'radio-option--glass' : 'radio-option--plain')}
              style={{ color: sel ? '#FFFFFF' : undefined }}
            >
              {T(o.label)}
            </div>
          )
        })}
      </div>
    </div>
  )
}
