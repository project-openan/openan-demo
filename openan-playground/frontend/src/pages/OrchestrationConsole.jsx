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
import { useTranslation } from 'react-i18next'
import PostmanConsole from '../components/PostmanConsole.jsx'
import { ORCHESTRATION_ENDPOINTS } from '../endpoints.js'
import Layout from '../Layout.jsx'

export default function OrchestrationConsolePage() {
  const { t } = useTranslation()
  const FOLDERS = [
    { key: 'browse', label: t('orchestration.folders.browse'), items: ['workflows', 'cards'] },
    { key: 'intent', label: t('orchestration.folders.intent'), items: ['intent', 'search', 'execute', 'executeById', 'dispatch'] },
    { key: 'records', label: t('orchestration.folders.records'), items: ['executions', 'records'] },
  ]

  return (
    <Layout>
      <PostmanConsole
        feature="orchestration"
        title={t('orchestration.title')}
        subtitle={t('orchestration.subtitle')}
        targetKey="orchestrationUrl"
        targetLabel="orchestration"
        endpoints={ORCHESTRATION_ENDPOINTS}
        folders={FOLDERS}
      />
    </Layout>
  )
}
