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
import PostmanConsole from '../components/PostmanConsole.jsx'
import { ORCHESTRATION_ENDPOINTS } from '../endpoints.js'
import Layout from '../Layout.jsx'

const FOLDERS = [
  { key: 'browse', label: '工作流与卡片', items: ['workflows', 'cards'] },
  { key: 'intent', label: '意图与执行', items: ['intent', 'search', 'execute', 'executeById', 'dispatch'] },
  { key: 'records', label: '执行记录', items: ['executions', 'records'] },
]

export default function OrchestrationConsolePage() {
  return (
    <Layout>
      <PostmanConsole
        feature="orchestration"
        title="编排中心调测"
        subtitle="PSOP 生成 / 搜索 / 执行（SSE） / 执行记录"
        targetKey="orchestrationUrl"
        targetLabel="orchestration"
        endpoints={ORCHESTRATION_ENDPOINTS}
        folders={FOLDERS}
      />
    </Layout>
  )
}
