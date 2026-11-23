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
