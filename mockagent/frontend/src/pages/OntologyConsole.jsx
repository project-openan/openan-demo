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
import { ONTOLOGY_ENDPOINTS } from '../endpoints.js'
import Layout from '../Layout.jsx'

const FOLDERS = [
  { key: 'service', label: '服务状态', items: ['health'] },
  { key: 'reasoning', label: '本体推理', items: ['runs'] },
]

export default function OntologyConsolePage() {
  return (
    <Layout>
      <PostmanConsole
        feature="ontology"
        title="本体服务调测"
        subtitle="健康检查 / 本体推理（NDJSON 事件流）"
        targetKey="ontologyUrl"
        targetLabel="ontology"
        endpoints={ONTOLOGY_ENDPOINTS}
        folders={FOLDERS}
      />
    </Layout>
  )
}
