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
import { REGISTRY_ENDPOINTS } from '../endpoints.js'
import Layout from '../Layout.jsx'

export default function RegistryConsolePage() {
  const { t } = useTranslation()
  const FOLDERS = [
    { key: 'cards', label: t('registry.folders.cards'), items: ['list', 'get', 'register', 'update', 'delete'] },
    { key: 'smart', label: t('registry.folders.smart'), items: ['semantic'] },
    { key: 'publish', label: t('registry.folders.publish'), items: ['manage', 'publish'] },
    { key: 'system', label: t('registry.folders.system'), items: ['keys'] },
  ]

  return (
    <Layout>
      <PostmanConsole
        feature="registry"
        title={t('registry.title')}
        subtitle={t('registry.subtitle')}
        targetKey="registryUrl"
        targetLabel="registry"
        endpoints={REGISTRY_ENDPOINTS}
        folders={FOLDERS}
        enableAgentCard
        footer={(
          <div className="pm-footer">
            <span>{t('registry.portalHint')}</span>
            <a href="http://203.0.113.10:9003/registry" target="_blank" rel="noreferrer">
              http://203.0.113.10:9003/registry ↗
            </a>
          </div>
        )}
      />
    </Layout>
  )
}
