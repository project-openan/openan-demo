import React from 'react'
import TBubble from './TBubble.jsx'
import useStageClock from './useStageClock.js'
import { AUTHZ_WEIGHTS } from '../../storyline/panel-timing.js'
import { measureText, FONT } from '../../storyline/flow/geometry'
import { T } from '../../i18n'

/* AuthorizationTPanelV4 — Authorization-T 详细交互流程
   V6.31（用户规格）：自 react-panels 源复制（V4.0 动网操作预授权 · 容器 9234）——
    at4 流式版式（29.5×15.5rem）：实底气泡（td-bubble--solid）内三行动网操作要素 +
    有效期，右下回复气泡「授权操作执行结果：成功」；面板底 180deg 蓝晕渐变叠 #000952。
    旧版 AuthorizationTPanel（at-panel 预授权胶囊/流程图）保留不删（本组件未挂载，
    挂载时经 SubStepPanels PANEL_DEFS 接入）；
   V6.35（用户规格）：接入工单2 问题处置——窗口=传输→粤西 授权请求流..粤西→传输
    响应流结束（424..448，见 panel-timing authorizationWindowOf）；两条消息分别呈现：
    ①请求气泡（动网操作要素+有效期，传输→粤西）随面板出现；②响应气泡（授权操作
    执行结果：成功，粤西→传输）在响应段开始（窗口中点 436）渐显；
   V6.56（用户规格）：请求要素调整——删除「有效期」行，新增「授权人」（原真实账号已随脱敏移除）
    与「任务编号」（值取自 粤西↔传输 Authorization-T 消息的 taskId——响应报文
    artifactUpdate.taskId，见 case-data.js c2 t=121；请求报文无 taskId 字段）。
    净增一行，行距 0.5rem→0.25rem（panels.css .at4-row）以容纳于固定 15.5rem 面板高 */

// 任务编号：Authorization-T 响应（粤西→传输）报文 artifactUpdate.taskId（V6.56）。
// 报文正文已迁 i18n（键 msg.c2.121）——非严格 JSON，以正则提取首个 taskId
const AUTHZ_TASK_ID = (() => {
  const m = T('msg.c2.121').match(/"taskId"\s*:\s*"([^"]+)"/);
  return m ? m[1] : '';
})();

// 授权要素行——label/value 为 i18n 占位键（az.*）；授权人值为业务数据（陈志远，经 substitutions 英文化）
const ROWS = [
  { label: 'az.scenario', value: 'az.vScenario' },
  { label: 'az.type', value: 'az.vType' },
  { label: 'az.name', value: 'az.vName' },
  { label: 'az.person', value: '陈志远（传输室）' },
  { label: 'az.taskId', value: AUTHZ_TASK_ID },
]

export default function AuthorizationTPanelV4(props) {
  const stage = useStageClock(props, 2, AUTHZ_WEIGHTS)
  const on = (k) => (stage >= k ? ' ir-on' : '')
  return (
    <div className="glass-panel tdialog at4-panel" style={{ width: '29.5rem', height: '15.5rem' }}>
      <div className="tdlg-head">
        <span className="tdlg-bar" style={{ background: '#62b42e' }} />
        <span
          className="tdlg-title title-text--grad"
          style={{ backgroundImage: 'linear-gradient(90deg, #dff4cc, #62b42e)' }}
        >
          Authorization-T
        </span>
        {/* 次级标题白字（本工程口径——.tdlg-title 无色会继承暗灰看不清） */}
        <span className="tdlg-title" style={{ marginLeft: '0.25rem', color: '#fff' }}>
          {T('lbl.interactDetails')}
        </span>
      </div>

      {/* ① 传输→粤西 授权请求（面板出现即呈现） */}
      <TBubble
        width={439}
        tail="left"
        className={'td-bubble--solid ir-reveal' + on(1)}
        style={{ margin: '0.5rem 0 0 0', padding: '0.75rem 0.75rem 0.75rem 1.375rem' }}
      >
        <div className="at4-rows">
          {ROWS.map((r) => (
            <div className="at4-row" key={r.label}>
              <span className="at4-label">{T(r.label)}</span>
              <span className="at4-value">{T(r.value)}</span>
            </div>
          ))}
        </div>
      </TBubble>

      {/* ② 粤西→传输 授权响应（响应段开始渐显） */}
      {/* V6.83（用户规格）：EN 回复句超 175 定宽气泡（Authorization result: Success
          164px > 内容宽 145）——宽度按译后文字量取 max（zh ~132px 恒 175 逐像素不变；
          +30 = 左 padding 18 + 右 padding 12） */}
      <TBubble
        width={Math.max(175, measureText(T('sum.c2.121'), '400 12px ' + FONT) + 30)}
        tail="right"
        className={'td-bubble--solid ir-reveal' + on(2)}
        style={{ margin: '1rem 0 0 auto', padding: '0.75rem 0.75rem 0.75rem 1.125rem' }}
      >
        <span className="at4-reply">{T('sum.c2.121')}</span>
      </TBubble>
    </div>
  )
}
