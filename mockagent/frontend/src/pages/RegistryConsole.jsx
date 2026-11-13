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
import { REGISTRY_ENDPOINTS } from '../endpoints.js'
import Layout from '../Layout.jsx'

const FOLDERS = [
  { key: 'cards', label: 'Agent 卡片管理', items: ['list', 'get', 'register', 'update', 'delete'] },
  { key: 'smart', label: '智能查询', items: ['semantic'] },
  { key: 'publish', label: '发布管理', items: ['manage', 'publish'] },
  { key: 'system', label: '系统', items: ['keys'] },
]

export default function RegistryConsolePage() {
  return (
    <Layout>
      <PostmanConsole
        feature="registry"
        title="注册中心调测"
        subtitle="Agent 卡片注册 / 查询 / 语义匹配 / JWKS"
        targetKey="registryUrl"
        targetLabel="registry"
        endpoints={REGISTRY_ENDPOINTS}
        folders={FOLDERS}
        enableAgentCard
        footer={(
          <div className="pm-footer">
            <span>注册结果可在注册中心门户查看：</span>
            <a href="http://203.0.113.10:9003/registry" target="_blank" rel="noreferrer">
              http://203.0.113.10:9003/registry ↗
            </a>
          </div>
        )}
      />
    </Layout>
  )
}
