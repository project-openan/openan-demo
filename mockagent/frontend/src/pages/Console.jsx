import { useCallback, useEffect, useMemo, useState } from 'react'
import PostmanConsole from '../components/PostmanConsole.jsx'
import DatasetRequestPicker from '../components/DatasetRequestPicker.jsx'
import { api } from '../api.js'
import Layout from '../Layout.jsx'
import { EXTENSION_URIS, TEMPLATE_URIS, buildExampleRequest, uuid } from '../templates.js'

function shortLabel(uri) {
  const [family, , name] = uri.split('/')
  return `${family} · ${name}`
}

const DEFAULT_TEMPLATE = TEMPLATE_URIS[0]

const ENDPOINTS = [
  {
    key: 'send',
    label: 'A2A 消息发送（message:send）',
    method: 'POST',
    path: '/message:send',
    note: 'A2A SendMessageRequest 经 A2A-T SDK 渲染后发送；SDK 自动携带 A2A-Version / A2A-Extensions 头，扩展由 body 内 metadata.templateUri 决定',
  },
  ...TEMPLATE_URIS.map((uri) => ({
    key: uri,
    label: shortLabel(uri),
    method: 'POST',
    path: '/message:send',
    note: 'A2A-T 模板示例：点击填充该模板的示例请求，body 内 metadata.templateUri 决定 SDK 渲染与扩展头',
  })),
]

const FOLDERS = [
  { key: 'a2a', label: 'A2A 接口', items: ['send'] },
  ...[...new Set(TEMPLATE_URIS.map((uri) => uri.split('/')[0]))].map((family) => ({
    key: family,
    label: `${family} 模板示例`,
    items: TEMPLATE_URIS.filter((uri) => uri.startsWith(`${family}/`)),
  })),
]

function A2aConsole() {
  const [instances, setInstances] = useState([])
  const [target, setTarget] = useState('')
  const [instanceError, setInstanceError] = useState('')
  const [traceExamples, setTraceExamples] = useState([])

  const loadInstances = useCallback(async () => {
    try {
      const data = await api.get('/debug/api/v1/mock-instances')
      setInstances(data.instances || [])
      setInstanceError('')
    } catch (err) {
      setInstanceError(err.message || '打桩实例列表加载失败')
    }
  }, [])

  useEffect(() => {
    loadInstances()
    const timer = setInterval(loadInstances, 5000)
    return () => clearInterval(timer)
  }, [loadInstances])

  useEffect(() => {
    api.get('/debug/api/v1/console/trace-prompts')
      .then((data) => setTraceExamples(data.examples || []))
      .catch(() => setTraceExamples([]))
  }, [])

  // 按当前模板解析实采示例（自动匹配该模板的实采条目），使示例请求与提取的请求报文 body 完全一致
  function resolveExample(templateUri) {
    return traceExamples.find((ex) => ex.templateUri === templateUri) || null
  }

  const selectedInstance = instances.find((item) => item.id === target) || null

  // —— 数据集请求生成：选中智能体后，从其关联数据集挑一条对，自动生成请求报文 ——
  const [assocList, setAssocList] = useState([])
  const [pickerOpen, setPickerOpen] = useState(false)
  const [injectSignal, setInjectSignal] = useState(null)
  useEffect(() => {
    api.get('/debug/api/v1/console/datasets/agent-associations')
      .then((d) => setAssocList(d.associations || []))
      .catch(() => setAssocList([]))
  }, [])
  const activeAssoc = useMemo(() => {
    if (!target) return null
    return assocList.find((a) => a.instanceId === target) || null
  }, [target, assocList])
  const pickerAgentRowId = activeAssoc ? activeAssoc.agentRowId : null
  const pickerTemplates = activeAssoc && activeAssoc.scoped
    ? activeAssoc.templates.map((t) => t.templateUri)
    : null
  function buildRequestFromPair(pair) {
    const extUri = EXTENSION_URIS[pair.protocol] || ''
    const metadata = { templateUri: pair.templateUri }
    if (extUri) metadata[extUri] = pair.requestPrompt
    return {
      message: {
        messageId: uuid(),
        role: 'ROLE_USER',
        parts: [{ text: pair.partsText || `执行${pair.scenario || ''}任务`, metadata: {} }],
        metadata,
      },
    }
  }
  function onPickDatasetPair(pair) {
    setPickerOpen(false)
    setInjectSignal({ token: Date.now(), body: buildRequestFromPair(pair) })
  }

  async function sendAdapter(payload) {
    const payload2 = { request: payload.body, note: payload.body?.message?.metadata?.templateUri || payload.path }
    if (target) payload2.instanceId = target
    const result = await api.post('/debug/api/v1/console/send', payload2)
    return { status: 200, kind: 'json', body: result }
  }

  function extractRequest(item) {
    const rb = item.requestBody || {}
    const note = rb.note
    // console/send 记录：requestBody = {note, request}
    if (rb.request !== undefined) {
      return {
        method: 'POST',
        path: '/message:send',
        body: rb.request,
        endpointKey: 'send',
        rowLabel: note || item.templateUri,
      }
    }
    // Mock Agent 入站记录（direction=inbound）：requestBody = {templateUri, promptText, negotiationContext, requestedExtensions}
    // 重建为可回发的标准报文体（与 SDK MetadataContent 契约一致）
    const templateUri = rb.templateUri || item.templateUri || ''
    const promptText = rb.promptText || ''
    const extUri = (Array.isArray(rb.requestedExtensions) && rb.requestedExtensions[0])
      || EXTENSION_URIS[templateUri.split('/')[0]]
      || ''
    const metadata = {}
    if (templateUri) metadata.templateUri = templateUri
    if (extUri && promptText) metadata[extUri] = promptText
    if (rb.negotiationContext) metadata.negotiationContext = rb.negotiationContext
    return {
      method: 'POST',
      path: '/message:send',
      body: {
        message: {
          messageId: uuid(),
          role: 'ROLE_USER',
          parts: [{ text: note || templateUri || 'inbound replay', metadata: {} }],
          metadata,
        },
      },
      endpointKey: 'send',
      rowLabel: `入站 · ${templateUri || note || item.templateUri}`,
    }
  }

  const targetLabel = selectedInstance
    ? `${selectedInstance.name} · :${selectedInstance.port}${selectedInstance.healthy ? '' : '（未运行）'}`
    : '内嵌 Mock Agent（默认）'

  const topbarExtra = (
    <>
      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>被测智能体：</span>
      <select
        className="agent-trigger"
        value={target}
        onChange={(e) => setTarget(e.target.value)}
        style={{ paddingRight: 24 }}
      >
        <option value="">内嵌 Mock Agent（默认 · /debug/a2a）</option>
        {instances.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name} · :{item.port}{item.healthy ? '（运行中）' : '（未运行）'}
          </option>
        ))}
      </select>
      {traceExamples.length > 0 && (
        <span className="muted" style={{ fontSize: 12, marginLeft: 10 }}>
          模板示例自动使用实采报文；或从数据集生成请求 →
        </span>
      )}
      {instanceError && <span className="error-text" style={{ fontSize: 12 }}>{instanceError}</span>}
      <button
        type="button"
        className="btn small"
        style={{ marginLeft: 10 }}
        onClick={() => setPickerOpen(true)}
        title="从（该智能体关联范围的）数据集中选择请求-响应对，自动生成请求报文"
      >
        数据集请求…
      </button>
      <DatasetRequestPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        agentRowId={pickerAgentRowId}
        templates={pickerTemplates}
        onPick={onPickDatasetPair}
      />
    </>
  )

  return (
    <PostmanConsole
      feature="a2at"
      title="A2A-T SDK 调测"
      subtitle="A2A 接口打桩自测（A2A-T prompt 经 SDK 渲染，可打内嵌 Agent 或打桩实例）"
      targetKey="mockAgent"
      targetLabel="mockAgent"
      targetOverride={targetLabel}
      endpoints={ENDPOINTS}
      folders={FOLDERS}
      buildExample={(endpoint) => {
        const templateUri = endpoint.key === 'send' ? DEFAULT_TEMPLATE : endpoint.key
        const ex = resolveExample(templateUri)
        return buildExampleRequest(templateUri, ex ? ex.promptText : '', ex ? ex.partsText : '')
      }}
      sendAdapter={sendAdapter}
      extractRequest={extractRequest}
      topbarExtra={topbarExtra}
      injectSignal={injectSignal}
    />
  )
}

export default function ConsolePage() {
  return (
    <Layout>
      <A2aConsole />
    </Layout>
  )
}
