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
import { EXECUTION_ENDPOINTS } from '../endpoints.js'
import Layout from '../Layout.jsx'

const FOLDERS = [
  { key: 'message', label: 'A2A 消息', items: ['send', 'stream'] },
  { key: 'tasks', label: '任务管理', items: ['tasks', 'task', 'cancel'] },
]

export default function ExecutionConsolePage() {
  return (
    <Layout>
      <PostmanConsole
        feature="execution"
        title="执行中心调测"
        subtitle="宿主 Agent A2A 消息（含 SSE 流式） / 任务管理"
        targetKey="executionHostUrl"
        targetLabel="execution"
        endpoints={EXECUTION_ENDPOINTS}
        folders={FOLDERS}
      />
    </Layout>
  )
}
