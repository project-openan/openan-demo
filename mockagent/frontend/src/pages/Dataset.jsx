import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import Layout from '../Layout.jsx'

const PROTOCOL_COLORS = {
  'Task-T': '#2563eb',
  'Negotiation-T': '#9333ea',
  'Notification-T': '#059669',
  'Authorization-T': '#d97706',
}

function FullPair({ pair }) {
  return (
    <div style={{ padding: '0 16px 16px', display: 'grid', gap: 12 }}>
      <div className="muted" style={{ fontSize: 12 }}>
        模板：<code>{pair.templateUri}</code> · pairId：{pair.pairId}
      </div>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <strong>请求</strong>
          <span className="muted" style={{ fontSize: 12 }}>parts.text: {pair.partsText}</span>
          <span style={{ flex: 1 }} />
          <button
            type="button"
            className="btn ghost"
            style={{ padding: '2px 10px', fontSize: 12 }}
            onClick={() => navigator.clipboard?.writeText(pair.requestPrompt)}
          >
            复制
          </button>
        </div>
        <pre className="pair-body">{pair.requestPrompt}</pre>
      </div>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <strong>响应（配对，与请求同标识）</strong>
          <span className="muted" style={{ fontSize: 12 }}>artifact.name: {pair.responseArtifactName}</span>
        </div>
        <pre className="pair-body pair-body-response">{pair.responseText}</pre>
      </div>
      {pair.source && <div className="muted" style={{ fontSize: 12 }}>来源：{pair.source}</div>}
    </div>
  )
}

function PairHeader({ pair, open, onToggle, trailing }) {
  const protoColor = PROTOCOL_COLORS[pair.protocol] || '#6b7280'
  return (
    <button
      type="button"
      className="pair-card-header"
      onClick={onToggle}
      style={{ all: 'unset', display: 'block', width: '100%', cursor: 'pointer', boxSizing: 'border-box' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '12px 16px' }}>
        <span style={{ background: protoColor, color: '#fff', borderRadius: 6, padding: '2px 8px', fontSize: 12, fontWeight: 600, flexShrink: 0 }}>
          {pair.protocol}
        </span>
        <span style={{ fontWeight: 600 }}>#{pair.order} {pair.scenario}</span>
        <span style={{ flex: 1 }} />
        {trailing}
        <span className="muted" style={{ fontSize: 12 }}>{pair.direction}</span>
        <span className="nav-caret" style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }}>▾</span>
      </div>
    </button>
  )
}

function SeedPairCard({ pair, showWorkOrder = true }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <PairHeader
        pair={pair}
        open={open}
        onToggle={() => setOpen((v) => !v)}
        trailing={showWorkOrder ? <span className="muted" style={{ fontSize: 12 }}>{pair.workOrder}</span> : null}
      />
      {open && <FullPair pair={pair} />}
    </div>
  )
}

function ExpandedPairCard({ dsId, pair }) {
  const [open, setOpen] = useState(false)
  const [full, setFull] = useState(null)
  const [err, setErr] = useState('')
  async function toggle() {
    const next = !open
    setOpen(next)
    if (next && !full) {
      try {
        setFull(await api.get(`/debug/api/v1/console/datasets/${dsId}/pairs/${pair.pairId}`))
      } catch (e) {
        setErr(e.message || String(e))
      }
    }
  }
  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <PairHeader pair={pair} open={open} onToggle={toggle} trailing={null} />
      {open && (full ? <FullPair pair={full} /> : <div style={{ padding: '0 16px 16px' }} className="muted">{err ? `加载失败：${err}` : '加载中…'}</div>)}
    </div>
  )
}

function SeedTab({ scopeTemplates }) {
  const [dataset, setDataset] = useState(null)
  const [error, setError] = useState('')
  const [workOrder, setWorkOrder] = useState('全部')
  const [protocol, setProtocol] = useState('全部')
  useEffect(() => {
    api.get('/debug/api/v1/console/demo-dataset')
      .then(setDataset)
      .catch((e) => setError(e.message || String(e)))
  }, [])
  const workOrders = useMemo(() => (dataset ? ['全部', ...Array.from(new Set(dataset.pairs.map((p) => p.workOrder)))] : []), [dataset])
  const protocols = useMemo(() => (dataset ? ['全部', ...Array.from(new Set(dataset.pairs.map((p) => p.protocol)))] : []), [dataset])
  const pairs = useMemo(() => {
    if (!dataset) return []
    return dataset.pairs.filter((p) => {
      if (workOrder !== '全部' && p.workOrder !== workOrder) return false
      if (protocol !== '全部' && p.protocol !== protocol) return false
      if (scopeTemplates && !scopeTemplates.includes(p.templateUri)) return false
      return true
    })
  }, [dataset, workOrder, protocol, scopeTemplates])
  if (error) return <div className="card error-text">加载失败：{error}</div>
  if (!dataset) return <div className="muted">加载中…</div>
  return (
    <>
      <div className="card" style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          工单
          <select value={workOrder} onChange={(e) => setWorkOrder(e.target.value)}>
            {workOrders.map((w) => <option key={w} value={w}>{w}</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          协议
          <select value={protocol} onChange={(e) => setProtocol(e.target.value)}>
            {protocols.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        <span className="badge blue">共 {pairs.length} 对</span>
        <span className="muted" style={{ flex: 1, minWidth: 240 }}>{dataset.note}</span>
      </div>
      <div style={{ display: 'grid', gap: 10 }}>
        {pairs.map((p) => <SeedPairCard key={p.pairId} pair={p} showWorkOrder={!scopeTemplates} />)}
      </div>
    </>
  )
}

function ExpandedTab({ agentId }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [protocol, setProtocol] = useState('全部')
  const [templateUri, setTemplateUri] = useState('全部')
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')

  useEffect(() => {
    const params = new URLSearchParams({ page: String(page), pageSize: String(pageSize) })
    if (agentId) params.set('agentId', String(agentId))
    if (protocol !== '全部') params.set('protocol', protocol)
    if (templateUri !== '全部') params.set('templateUri', templateUri)
    if (query.trim()) params.set('q', query.trim())
    setData(null)
    api.get(`/debug/api/v1/console/datasets/expanded/pairs?${params.toString()}`)
      .then(setData)
      .catch((e) => setError(e.message || String(e)))
  }, [page, pageSize, protocol, templateUri, query, agentId])

  useEffect(() => { setPage(1) }, [agentId])

  if (error) return <div className="card error-text">加载失败：{error}</div>
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1
  const scoped = Boolean(agentId) && data && Array.isArray(data.agentScopeTemplates)
  return (
    <>
      <div className="card" style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          协议
          <select value={protocol} onChange={(e) => { setProtocol(e.target.value); setPage(1) }}>
            <option value="全部">全部</option>
            {(data ? data.protocols : []).map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 280 }}>
          模板
          <select value={templateUri} onChange={(e) => { setTemplateUri(e.target.value); setPage(1) }} style={{ flex: 1, minWidth: 200 }}>
            <option value="全部">全部</option>
            {(data ? data.templateUris : []).map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          关键词
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="场景/端口/流水号…" />
          <button type="button" className="btn" onClick={() => { setQuery(q); setPage(1) }}>搜索</button>
        </label>
        <span className="badge blue">{data ? `共 ${data.total} 对` : '…'}</span>
      </div>
      {scoped && (
        <div className="muted" style={{ fontSize: 12, margin: '6px 2px' }}>
          已按智能体关联范围过滤（{data.agentScopeTemplates.length} 个模板）
        </div>
      )}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', margin: '10px 2px' }}>
        <button type="button" className="btn ghost" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>上一页</button>
        <span className="muted">第 {page} / {totalPages} 页</span>
        <button type="button" className="btn ghost" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>下一页</button>
        <span className="muted" style={{ fontSize: 12 }}>
          每对请求-响应共享同一工单号/端口/流水号/时间，按预期输出合同对齐；MockAgent 按请求检索最接近的对返回。
        </span>
      </div>
      <div style={{ display: 'grid', gap: 10 }}>
        {(data ? data.items : []).map((p) => <ExpandedPairCard key={p.pairId} dsId="expanded" pair={p} />)}
      </div>
    </>
  )
}

export default function DatasetPage() {
  const [tab, setTab] = useState('seed')
  const [meta, setMeta] = useState(null)
  const [assocs, setAssocs] = useState(null)
  const [agentSel, setAgentSel] = useState('')
  const [showAssoc, setShowAssoc] = useState(false)
  useEffect(() => {
    api.get('/debug/api/v1/console/datasets').then(setMeta).catch(() => {})
    api.get('/debug/api/v1/console/datasets/agent-associations').then(setAssocs).catch(() => {})
  }, [])
  const byId = useMemo(() => {
    const m = {}
    for (const d of meta?.datasets || []) m[d.id] = d
    return m
  }, [meta])
  const assocList = assocs?.associations || []
  const selected = assocList.find((a) => `${a.instanceId || ''}:${a.agentRowId || 'default'}` === agentSel) || null
  const scopeTemplates = selected ? (selected.scoped ? selected.templates.map((t) => t.templateUri) : null) : null
  return (
    <Layout>
      <div className="page">
        <div className="page-header">
          <div>
            <h1>数据集</h1>
            <p className="muted">请求-响应成对数据集：种子数据集（Demo 实采）+ 扩写数据集（全模板覆盖 5000+ 对），并与 Mock Agent 按模板职责关联</p>
          </div>
        </div>
        <div className="card" style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <button type="button" className={`btn${tab === 'seed' ? '' : ' ghost'}`} onClick={() => setTab('seed')}>
            种子数据集{byId.seed ? `（${byId.seed.pairCount} 对）` : ''}
          </button>
          <button type="button" className={`btn${tab === 'expanded' ? '' : ' ghost'}`} onClick={() => setTab('expanded')}>
            扩写数据集{byId.expanded ? `（${byId.expanded.pairCount} 对）` : ''}
          </button>
          <span style={{ flex: 1 }} />
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            关联智能体
            <select value={agentSel} onChange={(e) => setAgentSel(e.target.value)} style={{ minWidth: 190 }}>
              <option value="">全部智能体</option>
              {assocList.map((a) => (
                <option key={`${a.instanceId || ''}:${a.agentRowId || 'default'}`} value={`${a.instanceId || ''}:${a.agentRowId || 'default'}`}>
                  {a.name}{a.port ? ` :${a.port}` : ''}{a.scoped ? `（${a.pairCounts.seed + a.pairCounts.expanded} 对）` : '（全部）'}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="btn ghost" onClick={() => setShowAssoc((v) => !v)}>
            {showAssoc ? '收起关联明细' : '关联明细'}
          </button>
        </div>
        {showAssoc && (
          <div className="card" style={{ display: 'grid', gap: 8 }}>
            {assocList.map((a) => (
              <div key={`${a.instanceId || ''}:${a.agentRowId || 'default'}`} style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap', borderBottom: '1px solid rgba(128,128,128,.15)', paddingBottom: 6 }}>
                <strong style={{ minWidth: 170 }}>{a.name}{a.port ? ` :${a.port}` : ''}</strong>
                <span className="badge blue">种子 {a.pairCounts.seed} 对</span>
                <span className="badge indigo">扩写 {a.pairCounts.expanded} 对</span>
                {a.agentRowId && <span className="muted" style={{ fontSize: 12 }}>Agent#{a.agentRowId}{a.agentEnabled ? '' : '（未启动）'}</span>}
                <span className="muted" style={{ fontSize: 12, flex: 1, minWidth: 260 }}>
                  {a.scoped ? a.templates.map((t) => t.templateUri).join('；') : '未限定范围：检索时覆盖数据集全部模板'}
                </span>
              </div>
            ))}
          </div>
        )}
        <span className="muted" style={{ fontSize: 12, margin: '6px 2px' }}>
          {tab === 'seed' ? byId.seed?.source || '' : byId.expanded?.source || ''}
        </span>
        {tab === 'seed' ? <SeedTab scopeTemplates={scopeTemplates} /> : <ExpandedTab agentId={selected?.agentRowId || null} />}
      </div>
    </Layout>
  )
}
