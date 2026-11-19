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
import http from 'node:http'
import { runOntologyApplication } from './orchestrator.js'

const port = Number(process.env.API_PORT || 8787)

function json(response, status, payload) {
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'access-control-allow-origin': '*',
    'access-control-allow-headers': 'content-type',
    'access-control-allow-methods': 'GET,POST,OPTIONS',
  })
  response.end(status === 204 ? undefined : JSON.stringify(payload))
}

async function bodyJSON(request) {
  let raw = ''
  for await (const chunk of request) {
    raw += chunk
    if (raw.length > 1_000_000) throw new Error('请求体过大')
  }
  return raw ? JSON.parse(raw) : {}
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, 'http://' + (request.headers.host || 'localhost'))
  if (request.method === 'OPTIONS') return json(response, 204, {})

  try {
    if (request.method === 'GET' && url.pathname === '/api/health') {
      return json(response, 200, { ok: true, service: 'ontology-application-api' })
    }

    if (request.method === 'POST' && url.pathname === '/api/runs') {
      const payload = await bodyJSON(request)
      if (!String(payload.input || '').trim()) return json(response, 400, { error: '用户输入不能为空' })
      response.writeHead(200, {
        'content-type': 'application/x-ndjson; charset=utf-8',
        'cache-control': 'no-cache, no-transform',
        connection: 'keep-alive',
        'access-control-allow-origin': '*',
      })
      const emit = (event) => response.write(JSON.stringify(event) + '\n')
      try {
        await runOntologyApplication({ input: String(payload.input).trim(), emit })
      } catch (error) {
        emit({ type: 'run.failed', error: error.message || '执行失败' })
      }
      return response.end()
    }
    return json(response, 404, { error: '接口不存在' })
  } catch (error) {
    return json(response, 400, { error: error.message || '请求失败' })
  }
})

server.listen(port, '0.0.0.0', () => {
  console.log('[ontology-api] listening on http://localhost:' + port)
})
