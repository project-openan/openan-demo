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
// JSON 语法高亮共享组件
// 覆盖所有 JSON「查看」场景：调测台响应 Body / 原始响应、请求 body 高亮预览、
// Agent 卡片查看弹窗（SettingsAgents）、种子变体表格（Seeds）等，展示效果与响应面板一致。
export function highlightJson(text) {
  const escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return escaped.replace(
    /("(\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false)\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,
    (match) => {
      let cls = 'json-num'
      if (match.startsWith('"')) cls = match.trimEnd().endsWith(':') ? 'json-key' : 'json-str'
      else if (match === 'true' || match === 'false') cls = 'json-bool'
      else if (match === 'null') cls = 'json-null'
      return `<span class="${cls}">${match}</span>`
    },
  )
}

export default function JsonView({ value, className = 'pm-code', style }) {
  const text = typeof value === 'string' ? value : JSON.stringify(value ?? null, null, 2)
  return <pre className={className} style={style} dangerouslySetInnerHTML={{ __html: highlightJson(text) }} />
}
