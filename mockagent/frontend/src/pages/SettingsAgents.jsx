import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { readJwtPayload } from '../jwt.js'
import Layout from '../Layout.jsx'
import JsonView from '../JsonView.jsx'
import OdaDeployModal from './OdaDeployModal.jsx'

function PairDetailBody({ pair }) {
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <div className="muted" style={{ fontSize: 12 }}>
        模板：<code>{pair.templateUri}</code> · pairId：{pair.pairId}
      </div>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <strong style={{ fontSize: 13 }}>请求</strong>
          <span style={{ flex: 1 }} />
          <button className="btn ghost small" onClick={() => navigator.clipboard?.writeText(pair.requestPrompt)}>复制</button>
        </div>
        <pre className="pair-body">{pair.requestPrompt}</pre>
      </div>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <strong style={{ fontSize: 13 }}>响应（配对）</strong>
        </div>
        <pre className="pair-body pair-body-response">{pair.responseText}</pre>
      </div>
      {pair.source && <div className="muted" style={{ fontSize: 12 }}>来源：{pair.source}</div>}
    </div>
  )
}

function AssocPairBrowser({ agentRowId, templates }) {
  const [ds, setDs] = useState('expanded')
  const [data, setData] = useState(null)
  const [page, setPage] = useState(1)
  const [tpl, setTpl] = useState('全部')
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const [openId, setOpenId] = useState(null)
  const [err, setErr] = useState('')
  const pageSize = 20

  useEffect(() => {
    if (!agentRowId) return
    const params = new URLSearchParams({ page: String(page), pageSize: String(pageSize), agentId: String(agentRowId) })
    if (tpl !== '全部') params.set('templateUri', tpl)
    if (query.trim()) params.set('q', query.trim())
    setData(null)
    api.get(`/debug/api/v1/console/datasets/${ds}/pairs?${params.toString()}`)
      .then(setData)
      .catch((e) => setErr(e.message || String(e)))
  }, [ds, page, tpl, query, agentRowId])

  useEffect(() => { setPage(1); setOpenId(null) }, [ds, tpl, query, agentRowId])

  if (!agentRowId) {
    return <div className="muted">该实例尚未启动（无 Agent 行），启动后可浏览其关联数据对。</div>
  }
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          数据集
          <select value={ds} onChange={(e) => setDs(e.target.value)}>
            <option value="expanded">扩写数据集</option>
            <option value="seed">种子数据集</option>
          </select>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 220 }}>
          模板
          <select value={tpl} onChange={(e) => setTpl(e.target.value)} style={{ flex: 1 }}>
            <option value="全部">全部</option>
            {(templates || []).map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          关键词
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="场景/端口/流水号…" />
          <button className="btn small" onClick={() => setQuery(q)}>搜索</button>
        </label>
        <span className="badge blue">{data ? `${data.total} 对` : '…'}</span>
      </div>
      {err && <div className="error-text">{err}</div>}
      <div style={{ display: 'grid', gap: 8 }}>
        {(data ? data.items : []).map((item) => (
          <div key={item.pairId} className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <button
              type="button"
              className="pair-card-header"
              onClick={() => setOpenId(openId === item.pairId ? null : item.pairId)}
              style={{ all: 'unset', display: 'block', width: '100%', cursor: 'pointer', boxSizing: 'border-box' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '10px 14px' }}>
                <span className="mono-text" style={{ fontSize: 12 }}>{item.pairId}</span>
                <span style={{ fontWeight: 600 }}>{item.scenario}</span>
                <span className="muted" style={{ fontSize: 12, flex: 1, minWidth: 120 }}>{item.requestPromptPreview}</span>
                <span className="nav-caret" style={{ transform: openId === item.pairId ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }}>▾</span>
              </div>
            </button>
            {openId === item.pairId && (
              <div style={{ padding: '0 14px 14px' }}>
                <PairDetailBody pair={item} />
              </div>
            )}
          </div>
        ))}
        {data && data.items.length === 0 && <div className="muted">无符合条件的数据对</div>}
      </div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button className="btn ghost small" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>上一页</button>
        <span className="muted" style={{ fontSize: 12 }}>第 {page} / {totalPages} 页</span>
        <button className="btn ghost small" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>下一页</button>
      </div>
    </div>
  )
}

export default function SettingsAgentsPage() {
  const [instances, setInstances] = useState([])
  const [definePath, setDefinePath] = useState('')
  const [instanceError, setInstanceError] = useState('')
  const [instBusy, setInstBusy] = useState('')
  const [instModal, setInstModal] = useState(null)
  const [selectedIds, setSelectedIds] = useState([])
  const [odaModal, setOdaModal] = useState(false)
  const [assocs, setAssocs] = useState([])
  const isAdmin = readJwtPayload().role === 'admin'

  const loadInstances = useCallback(async () => {
    try {
      const data = await api.get('/debug/api/v1/mock-instances')
      setInstances(data.instances || [])
      setDefinePath(data.definePath || '')
      setInstanceError('')
    } catch (err) {
      setInstanceError(err.message || '实例列表加载失败')
    }
  }, [])

  useEffect(() => {
    loadInstances()
    api.get('/debug/api/v1/console/datasets/agent-associations')
      .then((d) => setAssocs(d.associations || []))
      .catch(() => {})
    const timer = setInterval(loadInstances, 5000)
    return () => clearInterval(timer)
  }, [loadInstances])

  const assocByInstance = Object.fromEntries(assocs.map((a) => [a.instanceId, a]))

  // 表格批量选择（按实例 id；列表自动刷新后保持已勾选）
  const allRowIds = instances.map((i) => i.id)
  const allChecked = allRowIds.length > 0 && allRowIds.every((id) => selectedIds.includes(id))
  const toggleRow = (id, on) =>
    setSelectedIds((cur) => (on ? (cur.includes(id) ? cur : [...cur, id]) : cur.filter((x) => x !== id)))
  const toggleAll = (on) => setSelectedIds(on ? allRowIds : [])

  async function instanceAction(instance, action) {
    setInstanceError('')
    setInstBusy(instance.id + ':' + action)
    try {
      await api.post(`/debug/api/v1/mock-instances/${instance.id}/${action}`)
      await loadInstances()
    } catch (err) {
      setInstanceError(err.message || '操作失败')
    } finally {
      setInstBusy('')
    }
  }

  async function showInstanceLogs(instance) {
    setInstModal({ mode: 'logs', title: `实例日志 · ${instance.name}`, text: '加载中…' })
    try {
      const text = await api.getText(`/debug/api/v1/mock-instances/${instance.id}/logs?lines=200`)
      setInstModal({ mode: 'logs', title: `实例日志 · ${instance.name}`, text: text || '(暂无日志)' })
    } catch (err) {
      setInstModal({ mode: 'logs', title: `实例日志 · ${instance.name}`, text: `加载失败：${err.message}` })
    }
  }

  async function showInstanceCard(instance) {
    setInstModal({ mode: 'card', title: `AgentCard · ${instance.name}`, card: null, error: '' })
    try {
      const card = await api.get(`/debug/api/v1/mock-instances/${instance.id}/card`)
      setInstModal({ mode: 'card', title: `AgentCard · ${instance.name}`, card, error: '' })
    } catch (err) {
      setInstModal({ mode: 'card', title: `AgentCard · ${instance.name}`, card: null, error: err.message || '加载失败' })
    }
  }

  function showInstanceAssoc(instance, assoc) {
    setInstModal({ mode: 'assoc', title: `数据集关联 · ${instance.name}`, assoc })
  }

  function assocTotal(assoc) {
    return (assoc?.pairCounts?.seed || 0) + (assoc?.pairCounts?.expanded || 0)
  }

  return (
    <Layout>
      <h2>Mock Agent 管理</h2>
      <p className="muted" style={{ marginBottom: 12 }}>
        当前不支持在页面创建 Mock Agent：Agent 由 <code>agents/&lt;id&gt;/agent.json</code> 打桩实例自动注册（管理员可启停）；
        默认 Agent 固定使用 /debug/a2a 端点，打桩实例端点为 <code>http://{'{host}'}:{'{port}'}</code>，各自维护独立变体池
      </p>
      <div className="card">
        <h2>打桩实例（agents/ 目录，每个 Agent 一个目录）</h2>
        <p className="muted" style={{ marginBottom: 10 }}>
          实例按 <code>{definePath || 'agents/&lt;id&gt;/agent.json'}</code> 声明启动为独立进程（各自端口/工作目录/模型连接方案），
          变体池与历史联调记录与主服务共用；llm.enabled=false 时为纯打桩模式。
          {instanceError && <span className="error-text" style={{ marginLeft: 8 }}>{instanceError}</span>}
        </p>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', margin: '4px 0 10px' }}>
          <span className="badge blue">已勾选 {selectedIds.length} / {instances.length} 个实例</span>
          {isAdmin && (
            <button
              className="btn"
              disabled={selectedIds.length === 0}
              title={selectedIds.length === 0 ? '先在表格勾选要部署的 Agent' : ''}
              onClick={() => setOdaModal(true)}
            >
              🚀 部署到 ODA Canvas
            </button>
          )}
          {isAdmin && selectedIds.length === 0 && (
            <span className="muted" style={{ fontSize: 12 }}>在表格勾选要部署的 Agent 后，点此批量部署</span>
          )}
        </div>
        <table>
          <thead>
            <tr>
              <th style={{ width: 36 }}>
                <input
                  type="checkbox"
                  aria-label="全选"
                  checked={allChecked}
                  onChange={(e) => toggleAll(e.target.checked)}
                />
              </th>
              <th>实例 ID</th>
              <th>名称</th>
              <th>端点</th>
              <th>工作目录</th>
              <th>模型方案</th>
              <th>数据集关联</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {instances.map((instance) => (
              <tr key={instance.id}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`选择 ${instance.name}`}
                    checked={selectedIds.includes(instance.id)}
                    onChange={(e) => toggleRow(instance.id, e.target.checked)}
                  />
                </td>
                <td className="mono-text">{instance.id}</td>
                <td>{instance.name}<div className="muted" style={{ fontSize: 12 }}>{instance.description}</div></td>
                <td className="mono-text">{instance.endpoint}</td>
                <td className="mono-text" style={{ fontSize: 12 }}>{instance.workDir}</td>
                <td>
                  {instance.llm.enabled
                    ? <span><span className="badge indigo">LLM 生成模式</span><div className="muted" style={{ fontSize: 12 }}>{instance.llm.model}<br />{instance.llm.baseUrl}</div></span>
                    : <span className="badge neutral">数据集匹配模式（纯打桩）</span>}
                  {instance.workflow && instance.workflow.enabled && (
                    <div style={{ marginTop: 4 }}><span className="badge blue">工作流模式 · {instance.workflow.workflowId}</span></div>
                  )}
                </td>
                <td>
                  {(() => {
                    const a = assocByInstance[instance.id]
                    if (!a) return <span className="muted" style={{ fontSize: 12 }}>…</span>
                    const total = (a.pairCounts?.seed || 0) + (a.pairCounts?.expanded || 0)
                    return (
                      <span style={{ whiteSpace: 'nowrap' }}>
                        <span className="badge blue">种子 {a.pairCounts?.seed || 0}</span>
                        <span className="badge indigo" style={{ marginLeft: 4 }}>扩写 {a.pairCounts?.expanded || 0}</span>
                        <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                          {a.scoped ? `${a.templateCount} 个模板 · 共 ${total} 对` : '未限定范围'}
                        </div>
                        <button className="btn ghost small" style={{ marginTop: 2 }} onClick={() => showInstanceAssoc(instance, a)}>明细</button>
                      </span>
                    )
                  })()}
                </td>
                <td>
                  <span className={`badge ${instance.healthy ? 'success' : (instance.running ? 'danger' : 'neutral')}`}>
                    {instance.healthy ? '运行中' : (instance.running ? '异常/启动中' : '已停止')}
                  </span>
                  {instance.agentId && <span className="badge indigo" style={{ marginLeft: 6 }}>Agent#{instance.agentId}</span>}
                </td>
                <td>
                  {isAdmin && !instance.running && (
                    <button className="btn small" disabled={instBusy === instance.id + ':start'} onClick={() => instanceAction(instance, 'start')}>
                      {instBusy === instance.id + ':start' ? '启动中…' : '启动'}
                    </button>
                  )}
                  {isAdmin && instance.running && (
                    <button className="btn danger small" disabled={instBusy === instance.id + ':stop'} onClick={() => instanceAction(instance, 'stop')}>
                      {instBusy === instance.id + ':stop' ? '停止中…' : '停止'}
                    </button>
                  )}
                  <button className="btn ghost small" style={{ marginLeft: 6 }} onClick={() => showInstanceLogs(instance)}>日志</button>
                  <button className="btn ghost small" style={{ marginLeft: 6 }} onClick={() => showInstanceCard(instance)}>卡片</button>
                </td>
              </tr>
            ))}
            {instances.length === 0 && (
              <tr><td colSpan={9}><span className="muted">未定义打桩实例（agents/&lt;id&gt;/agent.json）或定义不可达</span></td></tr>
            )}
          </tbody>
        </table>
      </div>
      {odaModal && (
        <OdaDeployModal
          initialAgents={selectedIds}
          onClose={() => setOdaModal(false)}
        />
      )}
      {instModal && (
        <div className="modal-overlay" onClick={() => setInstModal(null)}>
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h2 style={{ marginBottom: 0 }}>{instModal.title}</h2>
              <button className="btn ghost small" onClick={() => setInstModal(null)}>✕</button>
            </div>
            <div className="modal-body">
              {instModal.mode === 'logs' && (
                <pre className="json" style={{ maxHeight: '55vh', whiteSpace: 'pre-wrap' }}>{instModal.text}</pre>
              )}
              {instModal.mode === 'card' && (
                <>
                  {instModal.error && <div className="error-text">{instModal.error}</div>}
                  {instModal.card && <JsonView value={instModal.card} className="json" style={{ maxHeight: '55vh' }} />}
                </>
              )}
              {instModal.mode === 'assoc' && instModal.assoc && (
                <div style={{ display: 'grid', gap: 10 }}>
                  <p className="muted" style={{ margin: 0 }}>
                    该 Agent 的数据集检索范围（MockAgent 按请求模板在本范围内检索最接近的请求-响应对；范围外的请求回落变体池基线桩）。
                  </p>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {!instModal.assoc.scoped && <div className="badge indigo">未限定范围：检索覆盖数据集全部模板</div>}
                    <span className="badge blue">种子合计 {instModal.assoc.pairCounts?.seed || 0} 对</span>
                    <span className="badge indigo">扩写合计 {instModal.assoc.pairCounts?.expanded || 0} 对</span>
                    {instModal.assoc.agentRowId && (
                      <span className="badge neutral">Agent#{instModal.assoc.agentRowId}{instModal.assoc.agentEnabled ? '' : '（Agent 行未启用）'}</span>
                    )}
                  </div>
                  <div>
                    <table>
                      <thead>
                        <tr>
                          <th>关联模板</th>
                          <th>种子数据集</th>
                          <th>扩写数据集</th>
                          <th>合计</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(instModal.assoc.templates || []).map((t) => (
                          <tr key={t.templateUri}>
                            <td className="mono-text" style={{ fontSize: 12 }}>{t.templateUri}</td>
                            <td>{t.seed} 对</td>
                            <td>{t.expanded} 对</td>
                            <td><strong>{t.seed + t.expanded} 对</strong></td>
                          </tr>
                        ))}
                        {(instModal.assoc.templates || []).length === 0 && (
                          <tr><td colSpan={4}><span className="muted">该实例未配置关联模板（datasetTemplates 为空）</span></td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                  <div>
                    <h3 style={{ margin: '4px 0 8px' }}>关联数据对浏览</h3>
                    <AssocPairBrowser agentRowId={instModal.assoc.agentRowId} templates={(instModal.assoc.templates || []).map((t) => t.templateUri)} />
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </Layout>
  )
}
