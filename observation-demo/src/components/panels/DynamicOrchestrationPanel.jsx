import React from 'react'
import useStageClock from './useStageClock.js'
import { ORCH_WEIGHTS } from '../../storyline/panel-timing.js'

/* DynamicOrchestrationPanel — 动态编排详情面板（源自 react-panels）
   V3.26 动态分步（窗口：mini1 激活 → mini2 激活，见 panel-timing orchestrationWindowOf）：
   ①左侧元素（意图卡 + AgentCard 卡）→ ②编排引擎图标（发光箭头 + AI 图标）→
   ③右侧元素（智能体协作工作流）；各段整组渐入（visibility 隐藏期不参与命中/选中）；
   V5.56（用户规格）：图示距标题和左右下边沿均 1rem——内容整体上移 20（grp top -20：
   图示顶 49 = 标题底 33 + 16）、面板高 218→201（图示底 185 + 16 = 201；
   左右 16/558 原已满足） */
export default function DynamicOrchestrationPanel(props) {
  const stage = useStageClock(props, 3, ORCH_WEIGHTS)
  const on = (k) => (stage >= k ? ' ir-on' : '')
  const grp = (k) => ({ className: 'p-abs ir-reveal' + on(k), style: { left: 0, top: -20, width: 574, height: 218 } })
  return (
    <div className="glass-panel" style={{ width: 574, height: 201 }}>
      <div className="p-title-bar" style={{ left: 16, top: 14 }} />
      <div className="p-title-text" style={{ left: 26, top: 11 }}>动态编排</div>
      {/* V5.53（用户规格）：副标题「动态生成编排流程」删除 */}

      {/* ① 左侧：意图 + AgentCard */}
      <div {...grp(1)}>
        <div className="p-card" style={{ left: 16, top: 69, width: 256, height: 44 }} />
        <img
          className="p-abs"
          src="/assets/intent-title-bg.svg"
          alt=""
          style={{ left: 11, top: 74, width: 62, height: 43.04 }}
        />
        <div className="p-tag-text" style={{ left: 28, top: 82 }}>意图</div>
        <div className="p-body-text" style={{ left: 76, top: 81 }}>跨地市的SPN投诉任务诊断</div>

        <div className="p-card" style={{ left: 16, top: 125, width: 256, height: 80 }} />
        <img
          className="p-abs"
          src="/assets/agentcard-title-bg.svg"
          alt=""
          style={{ left: 11, top: 130, width: 98, height: 43.04 }}
        />
        <div className="p-tag-text" style={{ left: 28, top: 138 }}>AgentCard</div>
        <div className="radio-group" style={{ left: 112, top: 131, width: 143, height: 68 }}>
          <div className="radio-option radio-option--glass" style={{ left: 8, top: 4, width: 127, height: 28, justifyContent: 'center' }}>
            粤东SPN网络内生智能
          </div>
          <div className="radio-option radio-option--glass" style={{ left: 8, top: 36, width: 127, height: 28, justifyContent: 'center' }}>
            粤西SPN网络内生智能
          </div>
        </div>
        <img className="p-abs" src="/assets/plus.svg" alt="" style={{ left: 123, top: 113, width: 12, height: 12.01 }} />
      </div>

      {/* ② 编排引擎图标 */}
      <div {...grp(2)}>
        <img
          className="p-abs glow-arrow-img"
          src="/assets/glow-arrow.svg"
          alt=""
          style={{ left: 274, top: 103, width: 63.71, height: 32.3 }}
        />
        <img className="p-abs" src="/assets/ai-inference.svg" alt="" style={{ left: 290, top: 77, width: 32, height: 32 }} />
        <div className="p-engine-name" style={{ left: 286, top: 110 }}>编排引擎</div>
      </div>

      {/* ③ 右侧：智能体协作工作流 */}
      <div {...grp(3)}>
        <div className="p-card" style={{ left: 340, top: 69, width: 218, height: 136 }} />
        <img
          className="p-abs"
          src="/assets/workflow-title-bg.svg"
          alt=""
          style={{ left: 335, top: 74, width: 135, height: 43.04 }}
        />
        <div className="p-tag-text" style={{ left: 352, top: 82 }}>智能体协作工作流</div>

        <svg className="p-abs" style={{ left: 340, top: 69 }} width="218" height="136" viewBox="0 0 218 136" fill="none">
          <path d="M35.5 73 L35.5 64 Q35.5 58 41.5 58 L83 58" stroke="#09AA71" strokeWidth="1" strokeLinecap="round" />
          <path d="M78 53.5 L83 58 L78 62.5" stroke="#09AA71" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M130 58 L172.5 58 Q178.5 58 178.5 64 L178.5 73" stroke="#09AA71" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M174 68.5 L178.5 73 L183 68.5" stroke="#09AA71" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M35.5 97 L35.5 106 Q35.5 112 41.5 112 L83 112" stroke="#09AA71" strokeWidth="1" strokeLinecap="round" />
          <path d="M78 107.5 L83 112 L78 116.5" stroke="#09AA71" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M130 112 L172.5 112 Q178.5 112 178.5 106 L178.5 97" stroke="#09AA71" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M174 101.5 L178.5 97 L183 101.5" stroke="#09AA71" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
        </svg>

        <div className="p-node-btn" style={{ left: 423, top: 115 }}>节点2</div>
        <div className="p-node-btn" style={{ left: 352, top: 142 }}>节点1</div>
        <div className="p-node-btn" style={{ left: 495, top: 142 }}>节点1</div>
        <div className="p-node-btn" style={{ left: 423, top: 169 }}>节点3</div>

        <div className="p-mini-label" style={{ left: 389, top: 115, color: '#09AA71' }}>诊断</div>
        <div className="p-mini-label" style={{ left: 498, top: 115, color: '#5CA2E9' }}>结果汇总</div>
        <div className="p-mini-label" style={{ left: 390, top: 169, color: '#09AA71' }}>诊断</div>
      </div>
    </div>
  )
}
