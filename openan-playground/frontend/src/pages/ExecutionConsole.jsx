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
import { EXECUTION_ENDPOINTS } from '../endpoints.js'
import Layout from '../Layout.jsx'

export default function ExecutionConsolePage() {
  const { t } = useTranslation()
  const FOLDERS = [
    { key: 'message', label: t('execution.folders.message'), items: ['send', 'stream'] },
    { key: 'tasks', label: t('execution.folders.tasks'), items: ['tasks', 'task', 'cancel'] },
  ]

  return (
    <Layout>
      <PostmanConsole
        feature="execution"
        title={t('execution.title')}
        subtitle={t('execution.subtitle')}
        targetKey="executionHostUrl"
        targetLabel="execution"
        endpoints={EXECUTION_ENDPOINTS}
        folders={FOLDERS}
      />
    </Layout>
  )
}
