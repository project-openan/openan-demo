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
import { spawn } from 'node:child_process'
import net from 'node:net'

const apiPort = Number(process.env.API_PORT || 8787)

function portIsOpen(port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: '127.0.0.1', port })
    socket.once('connect', () => {
      socket.destroy()
      resolve(true)
    })
    socket.once('error', () => {
      socket.destroy()
      resolve(false)
    })
  })
}

async function existingApiIsHealthy() {
  try {
    const response = await fetch(`http://127.0.0.1:${apiPort}/api/health`, {
      signal: AbortSignal.timeout(1000),
    })
    return response.ok
  } catch {
    return false
  }
}

const children = []
if (await portIsOpen(apiPort)) {
  if (await existingApiIsHealthy()) {
    console.log(`[ontology-api] reusing existing API on http://localhost:${apiPort}`)
  } else {
    throw new Error(`API 端口 ${apiPort} 已被其他服务占用，且不是本项目 API`)
  }
} else {
  children.push(spawn(process.execPath, ['server/index.js'], { stdio: 'inherit' }))
}
children.push(spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '--port', '5200'], { stdio: 'inherit' }))

function stop(signal = 'SIGTERM') {
  for (const child of children) if (!child.killed) child.kill(signal)
}
process.on('SIGINT', () => { stop('SIGINT'); process.exit(0) })
process.on('SIGTERM', () => { stop(); process.exit(0) })
for (const child of children) {
  child.on('exit', (code) => {
    if (code && code !== 0) { stop(); process.exitCode = code }
  })
}
