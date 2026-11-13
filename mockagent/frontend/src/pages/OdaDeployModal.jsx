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
import { useEffect, useState } from 'react'
import { api } from '../api.js'

const EMPTY = {
  apiServer: '', token: '', namespace: 'components', insecureTLS: true,
  image: '', publicUrl: '', jwtSecret: '', adminPassword: '',
  release: 'openan-mockagent', componentId: 'TMFC900', apiVersion: 'v1beta3',
  storageSize: '2Gi', datasetSearch: true, stubFallback: true,
  selectedAgents: [], autoStart: false,
}

/** MockAgent 页「部署到 ODA Canvas」弹窗：表格勾选的实例为部署范围（内嵌默认 Agent 恒部署） */
export default function OdaDeployModal({ initialAgents = [], onClose }) {
  const [cfg, setCfg] = useState(EMPTY)
  const [hasToken, setHasToken] = useState(false)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState('')
  const [test, setTest] = useState(null)
  const [status, setStatus] = useState(null)
  const [log, setLog] = useState([])
  const [tab, setTab] = useState('deploy')   // deploy | status
  const [agents, setAgents] = useState([])   // 实例清单（展示勾选摘要用）
  const chosen = initialAgents.length ? initialAgents : (cfg.selectedAgents || [])

  useEffect(() => {
    api.get('/debug/api/v1/console/oda/config')
      .then((d) => { setCfg({ ...EMPTY, ...d.config, selectedAgents: initialAgents.length ? initialAgents : (d.config.selectedAgents || []) }); setHasToken(d.hasToken) })
      .catch((e) => setMsg(`加载配置失败：${e.message}`))
    api.get('/debug/api/v1/console/oda/agents')
      .then((d) => setAgents(d.agents || []))
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const set = (k) => (e) => setCfg((c) => ({ ...c, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))
  const savedToken = cfg.token === '' && hasToken
  const chosenMeta = chosen.map((id) => agents.find((a) => a.id === id)).filter(Boolean)

  async function saveAndDeploy() {
    setBusy('deploy'); setMsg('')
    try {
      // 部署范围 = 表格勾选清单：先落配置再部署（顺带保存表单里的地址/密钥改动）
      await api.put('/debug/api/v1/console/oda/config', { ...cfg, selectedAgents: chosen, token: savedToken ? '' : cfg.token })
      const d = await api.post('/debug/api/v1/console/oda/deploy')
      setLog(d.results.map((r) => ({ text: `${r.ok ? '✓' : '✗'} ${r.kind}/${r.name}  HTTP ${r.status}${r.detail ? '  ' + r.detail : ''}`, ok: r.ok })))
      setTab('status')
      refreshStatus(true)
    } catch (e) {
      setMsg(`一键部署失败：${e.message}`)
    } finally { setBusy('') }
  }

  async function save() {
    setBusy('save'); setMsg('')
    try {
      await api.put('/debug/api/v1/console/oda/config', { ...cfg, token: savedToken ? '' : cfg.token })
      const d = await api.get('/debug/api/v1/console/oda/config')
      setCfg({ ...EMPTY, ...d.config }); setHasToken(d.hasToken)
      setMsg('配置已保存')
    } catch (e) { setMsg(`保存失败：${e.message}`) } finally { setBusy('') }
  }

  async function run(action, label, fn) {
    setBusy(action); setMsg('')
    try { return await fn() }
    catch (e) { setMsg(`${label}失败：${e.message}`); return null }
    finally { setBusy('') }
  }

  async function testConn() {
    const d = await run('test', '测试连接', () => api.post('/debug/api/v1/console/oda/test-connection'))
    if (d) { setTest(d); setMsg('') }
  }

  async function undeploy() {
    const d = await run('undeploy', '卸载', () => api.post('/debug/api/v1/console/oda/undeploy'))
    if (d) {
      setLog(d.results.map((r) => ({ text: `${r.ok ? '✓' : '✗'} 删除 ${r.kind}/${r.name}  HTTP ${r.status}`, ok: r.ok })))
      refreshStatus(true)
    }
  }

  async function refreshStatus(silent = false) {
    const d = await run('status', silent ? '' : '刷新状态', () => api.get('/debug/api/v1/console/oda/status'))
    if (d) setStatus(d)
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 860, width: '94%' }}>
        <div className="modal-head">
          <h2 style={{ marginBottom: 0 }}>部署 MockAgent 到 ODA Canvas</h2>
          <button className="btn ghost small" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body" style={{ maxHeight: '72vh', overflow: 'auto' }}>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <button type="button" className={`btn small${tab === 'deploy' ? '' : ' ghost'}`} onClick={() => setTab('deploy')}>部署配置</button>
            <button type="button" className={`btn small${tab === 'status' ? '' : ' ghost'}`} onClick={() => { setTab('status'); refreshStatus() }}>部署状态</button>
          </div>

          {msg && <div className={msg.includes('失败') ? 'error-text' : 'muted'} style={{ marginBottom: 10 }}>{msg}</div>}

          {tab === 'deploy' && (
            <>
              <div style={{ border: '1px solid rgba(128,128,128,.25)', borderRadius: 8, padding: '10px 14px', marginBottom: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
                  <strong style={{ fontSize: 13 }}>部署范围（来自表格勾选）</strong>
                  <span className="badge blue">内嵌默认 Agent（必含）</span>
                  {chosenMeta.map((a) => (
                    <span key={a.id} className="badge indigo">{a.name} :{a.port}</span>
                  ))}
                  {chosen.length === 0 && <span className="muted" style={{ fontSize: 12 }}>仅内嵌默认 Agent（表格未勾选实例）</span>}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <span className="muted" style={{ fontSize: 12 }}>
                    未勾选的实例不会出现在 Deployment 端口、Service 与 Component exposedAPIs 中；如需调整，关闭弹窗后在表格中重新勾选。
                  </span>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, marginLeft: 'auto' }}>
                    <input type="checkbox" checked={cfg.autoStart} onChange={set('autoStart')} />
                    部署后 Pod 内自动启动勾选实例
                  </label>
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
                <label style={{ display: 'grid', gap: 4 }}>
                  API Server 地址
                  <input value={cfg.apiServer} onChange={set('apiServer')} placeholder="https://1.2.3.4:6443" />
                </label>
                <label style={{ display: 'grid', gap: 4 }}>
                  ServiceAccount Token {hasToken && <span className="badge blue" style={{ marginLeft: 4 }}>已保存</span>}
                  <input type="password" value={cfg.token} onChange={set('token')} placeholder={hasToken ? '已保存（留空保持不变）' : 'eyJhbGciOiJSUzI1NiIs…'} />
                </label>
                <label style={{ display: 'grid', gap: 4 }}>
                  命名空间
                  <input value={cfg.namespace} onChange={set('namespace')} />
                </label>
                <label style={{ display: 'grid', gap: 4 }}>
                  MockAgent 镜像
                  <input value={cfg.image} onChange={set('image')} placeholder="registry.example.com/openan/mockagent:1.0.0" />
                </label>
                <label style={{ display: 'grid', gap: 4 }}>
                  外部访问地址（可留空）
                  <input value={cfg.publicUrl} onChange={set('publicUrl')} placeholder="https://mockagent.example.com" />
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 18 }}>
                  <input type="checkbox" checked={cfg.insecureTLS} onChange={set('insecureTLS')} />
                  跳过 TLS 证书校验
                </label>
              </div>
              <details style={{ marginTop: 10 }}>
                <summary className="muted" style={{ cursor: 'pointer', fontSize: 13 }}>高级选项</summary>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, marginTop: 10 }}>
                  <label style={{ display: 'grid', gap: 4 }}>JWT 密钥<input type="password" value={cfg.jwtSecret} onChange={set('jwtSecret')} placeholder={cfg.jwtSecret ? '已保存' : '部署需填写至少 32 字节的随机密钥'} /></label>
                  <label style={{ display: 'grid', gap: 4 }}>控制台 admin 密码（可选）<input type="password" value={cfg.adminPassword} onChange={set('adminPassword')} placeholder="留空不启用" /></label>
                  <label style={{ display: 'grid', gap: 4 }}>存储容量<input value={cfg.storageSize} onChange={set('storageSize')} /></label>
                  <label style={{ display: 'grid', gap: 4 }}>组件编号<input value={cfg.componentId} onChange={set('componentId')} /></label>
                  <label style={{ display: 'grid', gap: 4 }}>组件规范版本
                    <select value={cfg.apiVersion} onChange={set('apiVersion')}>
                      <option value="v1beta3">v1beta3（Canvas ≥1.0，推荐）</option>
                      <option value="v1beta2">v1beta2（旧 Canvas）</option>
                    </select>
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 18 }}>
                    <input type="checkbox" checked={cfg.datasetSearch} onChange={set('datasetSearch')} /> 数据集检索回包
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <input type="checkbox" checked={cfg.stubFallback} onChange={set('stubFallback')} /> 变体池兜底
                  </label>
                </div>
              </details>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 14 }}>
                <button type="button" className="btn small" onClick={save} disabled={!!busy}>{busy === 'save' ? '保存中…' : '保存配置'}</button>
                <button type="button" className="btn ghost small" onClick={testConn} disabled={!!busy}>{busy === 'test' ? '测试中…' : '测试连接'}</button>
                <button type="button" className="btn" onClick={saveAndDeploy} disabled={!!busy} style={{ marginLeft: 'auto' }}>
                  {busy === 'deploy' ? '部署中…' : `🚀 一键部署（${chosen.length + 1} 个 Agent）`}
                </button>
              </div>
              {test && (
                <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
                  测试结果：K8s <code>{test.k8sVersion || '?'}</code> · Component CRD{' '}
                  {test.componentCrd ? <span className="badge blue">存在（{test.versions?.join(', ')}）</span> : <span style={{ color: '#dc2626' }}>未安装</span>} ·
                  命名空间 {test.namespaceReachable ? <span className="badge blue">可达</span> : <span style={{ color: '#dc2626' }}>{test.namespaceError || '不可达'}</span>}
                </div>
              )}
              <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
                部署对象：Secret、PVC、Deployment（内嵌默认 + 勾选 {chosen.length} 个实例端口 + 探针）、Service、Component（oda.tmforum.org，{chosen.length + 2} 个 exposedAPIs）——幂等可重复执行；镜像需已推送到集群可拉取仓库（构建见 deploy/oda-canvas）。
              </div>
            </>
          )}

          {tab === 'status' && (
            <div style={{ display: 'grid', gap: 10 }}>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                <strong>Component：</strong>
                <span className={`badge ${String(status?.component?.deploymentStatus) === 'complete' ? 'blue' : ''}`}>{status?.component?.deploymentStatus || '未知'}</span>
                <strong>Service：</strong>
                {status?.service?.exists ? <span className="badge blue">{status.service.clusterIP}</span> : <span className="muted">未创建</span>}
                <span className="badge indigo">
                  已部署实例：{status?.selectedAgents?.length ? status.selectedAgents.map((a) => a.name).join('、') : '仅内嵌默认 Agent'}
                </span>
                <span style={{ flex: 1 }} />
                <button type="button" className="btn ghost small" onClick={() => refreshStatus()} disabled={!!busy}>{busy === 'status' ? '刷新中…' : '刷新'}</button>
                <button type="button" className="btn danger small" onClick={undeploy} disabled={!!busy}>{busy === 'undeploy' ? '卸载中…' : '卸载'}</button>
              </div>
              {(status?.pods || []).length > 0 ? (
                <table>
                  <thead><tr><th>Pod</th><th>Phase</th><th>Ready</th><th>重启</th><th>镜像</th></tr></thead>
                  <tbody>
                    {status.pods.map((p) => (
                      <tr key={p.name}>
                        <td className="mono-text" style={{ fontSize: 12 }}>{p.name}</td>
                        <td>{p.phase}</td>
                        <td>{p.ready ? '✓' : '✗'}</td>
                        <td>{p.restarts}</td>
                        <td className="muted" style={{ fontSize: 12 }}>{p.image}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <span className="muted">未发现 MockAgent Pod（尚未部署或仍在调度）</span>}
              {log.length > 0 && (
                <pre style={{ margin: 0, padding: '10px 14px', background: 'rgba(128,128,128,.08)', borderRadius: 8, fontSize: 12, maxHeight: 180, overflow: 'auto' }}>
                  {log.map((l) => l.text).join('\n')}
                </pre>
              )}
              <div className="muted" style={{ fontSize: 12 }}>
                Component complete 后：kubectl -n {cfg.namespace} port-forward svc/openan-mockagent-core 9000:9000 9005:9005 9008:9008 9009:9009 9010:9010 → 控制台 /debug/ → 启动打桩实例
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
