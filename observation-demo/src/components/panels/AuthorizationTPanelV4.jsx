// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0
//
//    Licensed under the Apache License, Version 2.0 (the "License"); you may
//    not use this file except in compliance with the License. You may obtain
//    a copy of the License at
//
//         http://www.apache.org/licenses/LICENSE-2.0
//
//    Unless required by applicable law or agreed to in writing, software
//    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
//    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
//    License for the specific language governing permissions and limitations
//    under the License.
import React from 'react'
import TBubble from './TBubble.jsx'
import useStageClock from './useStageClock.js'
import { AUTHZ_WEIGHTS } from '../../storyline/panel-timing.js'
import { CASE_EVENTS } from '../../storyline/case-data.js'

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
   V6.56（用户规格）：请求要素调整——删除「有效期」行，新增「授权人 TRNOC005632」
    与「任务编号」（值取自 粤西↔传输 Authorization-T 消息的 taskId——响应报文
    artifactUpdate.taskId，见 case-data.js c2 t=121；请求报文无 taskId 字段）。
    净增一行，行距 0.5rem→0.25rem（panels.css .at4-row）以容纳于固定 15.5rem 面板高 */

// 任务编号：Authorization-T 响应（粤西→传输）报文 artifactUpdate.taskId（V6.56）。
// 报文为展示文本——metadata 含裸换行非严格 JSON，不能整体 parse，以正则提取首个 taskId
const AUTHZ_TASK_ID = (() => {
  const ev = (CASE_EVENTS.c2.events || []).find((e) => e.type === 'Authorization-T' && e.dir === 'response');
  const m = ev && ev.message && ev.message.match(/"taskId"\s*:\s*"([^"]+)"/);
  return m ? m[1] : '';
})();

const ROWS = [
  { label: '动网操作的业务场景', value: '业务投诉诊断' },
  { label: '动网操作的处置类型', value: '业务抢通' },
  { label: '动网操作名称', value: '隧道调优' },
  { label: '授权人', value: 'TRNOC005632' },
  { label: '任务编号', value: AUTHZ_TASK_ID },
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
          详细交互流程
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
              <span className="at4-label">{r.label}</span>
              <span className="at4-value">{r.value}</span>
            </div>
          ))}
        </div>
      </TBubble>

      {/* ② 粤西→传输 授权响应（响应段开始渐显） */}
      <TBubble
        width={175}
        tail="right"
        className={'td-bubble--solid ir-reveal' + on(2)}
        style={{ margin: '1rem 0 0 auto', padding: '0.75rem 0.75rem 0.75rem 1.125rem' }}
      >
        <span className="at4-reply">授权操作执行结果：成功</span>
      </TBubble>
    </div>
  )
}
