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
export const AGENT_LAYERS = [
  { key: 'service', label: '服务层 Agent' },
  { key: 'network', label: '网络层 Agent' },
]

export const NETWORK_DOMAINS = [
  { key: 'wireless', label: '无线' },
  { key: 'datacom', label: '数通' },
  { key: 'optical', label: '光' },
  { key: 'cloudcore', label: '云核' },
  { key: 'fixedaccess', label: '固定接入' },
  { key: 'computing', label: '算网' },
]

const DOMAIN_LABELS = Object.fromEntries(NETWORK_DOMAINS.map((item) => [item.key, item.label]))

export function layerLabel(layer) {
  if (layer === 'service') return '服务层'
  if (layer === 'network') return '网络层'
  return ''
}

export function domainLabel(domain) {
  return DOMAIN_LABELS[domain] || ''
}

export function groupLabel(agent) {
  if (agent.layer === 'network') {
    const domain = domainLabel(agent.networkDomain)
    return domain ? `网络层 · ${domain}` : '网络层'
  }
  if (agent.layer === 'service') return '服务层'
  return ''
}

export function groupAgents(agents) {
  const buckets = {
    service: [],
    'network-wireless': [],
    'network-datacom': [],
    'network-optical': [],
    'network-cloudcore': [],
    'network-fixedaccess': [],
    'network-computing': [],
  }
  for (const agent of agents) {
    if (agent.layer === 'service') {
      buckets.service.push(agent)
    } else if (agent.layer === 'network' && buckets[`network-${agent.networkDomain}`]) {
      buckets[`network-${agent.networkDomain}`].push(agent)
    }
  }
  const labels = {
    service: '服务层 Agent',
    'network-wireless': '网络层 · 无线',
    'network-datacom': '网络层 · 数通',
    'network-optical': '网络层 · 光',
    'network-cloudcore': '网络层 · 云核',
    'network-fixedaccess': '网络层 · 固定接入',
    'network-computing': '网络层 · 算网',
  }
  return Object.entries(buckets)
    .filter(([, list]) => list.length > 0)
    .map(([key, list]) => ({ key, label: labels[key], agents: list }))
}
