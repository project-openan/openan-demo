import { useEffect, useRef, useState } from 'react'

const NAME_RE = /^[a-zA-Z0-9_-]+(?:\s+[a-zA-Z0-9_-]+)*$/
const BINDINGS = ['HTTP+JSON', 'GRPC']
const MAX_EXTENSIONS = 10
const MAX_SKILLS = 100
const MAX_INTERFACES = 3

const REFERENCE_EXTENSIONS = [
  { uri: 'https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1', description: 'Task-T 结构化提示请求' },
  { uri: 'https://projects.tmforum.org/a2aproject/telecommunication/extensions/Notification-T/v1', description: 'Notification-T 结构化提示请求' },
  { uri: 'https://projects.tmforum.org/a2aproject/telecommunication/extensions/Authorization-T/v1', description: 'Authorization-T 结构化提示请求' },
  { uri: 'https://projects.tmforum.org/a2aproject/telecommunication/extensions/Negotiation-T/v1', description: 'Negotiation-T 协商消息' },
]

function splitCsv(text) {
  return (text || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function Field({ label, hint, full, children }) {
  return (
    <div className={`form-field${full ? ' full' : ''}`}>
      <label className="form-label">{label}</label>
      {children}
      {hint && <div className="form-hint">{hint}</div>}
    </div>
  )
}

export function emptyAgentCard() {
  return {
    name: '',
    version: '1.0.0',
    description: '',
    provider: { organization: '', url: '' },
    capabilities: { streaming: true, pushNotifications: false, extensions: REFERENCE_EXTENSIONS.map((ext) => ({ ...ext })) },
    skills: [],
    supportedInterfaces: [{ url: '', protocolBinding: 'HTTP+JSON', protocolVersion: '1.0.0' }],
    defaultInputModes: [],
    defaultOutputModes: [],
  }
}

function toForm(card) {
  const source = card || {}
  const provider = source.provider || {}
  const capabilities = source.capabilities || {}
  return {
    name: source.name || '',
    version: source.version || '',
    description: source.description || '',
    providerOrganization: provider.organization || '',
    providerUrl: provider.url || '',
    streaming: !!capabilities.streaming,
    pushNotifications: !!capabilities.pushNotifications,
    extensions: (capabilities.extensions || []).map((ext) => ({
      uri: ext.uri || '',
      description: ext.description || '',
    })),
    skills: (source.skills || []).map((skill) => ({
      id: skill.id || '',
      name: skill.name || '',
      description: skill.description || '',
      tags: (skill.tags || []).join(', '),
    })),
    interfaces: (source.supportedInterfaces || []).map((itf) => ({
      url: itf.url || '',
      protocolBinding: itf.protocolBinding || 'HTTP+JSON',
      protocolVersion: itf.protocolVersion || '',
    })),
    defaultInputModes: (source.defaultInputModes || []).join(', '),
    defaultOutputModes: (source.defaultOutputModes || []).join(', '),
  }
}

function toCard(form) {
  const card = {
    name: form.name.trim(),
    version: form.version.trim(),
    description: form.description.trim(),
    provider: { organization: form.providerOrganization.trim() },
    capabilities: {
      streaming: form.streaming,
      pushNotifications: form.pushNotifications,
      extensions: form.extensions
        .filter((ext) => ext.uri.trim())
        .map((ext) => ({ uri: ext.uri.trim(), description: ext.description.trim() })),
    },
    skills: form.skills.map((skill) => ({
      id: skill.id.trim(),
      name: skill.name.trim(),
      description: skill.description.trim(),
      tags: splitCsv(skill.tags),
    })),
    supportedInterfaces: form.interfaces.map((itf) => ({
      url: itf.url.trim(),
      protocolBinding: itf.protocolBinding,
      protocolVersion: itf.protocolVersion.trim(),
    })),
    defaultInputModes: splitCsv(form.defaultInputModes),
    defaultOutputModes: splitCsv(form.defaultOutputModes),
  }
  if (form.providerUrl.trim()) card.provider.url = form.providerUrl.trim()
  return card
}

export function validateAgentCard(card) {
  const errors = []
  const source = card || {}
  const provider = source.provider || {}
  const capabilities = source.capabilities || {}
  const skills = source.skills || []
  const interfaces = source.supportedInterfaces || []
  const extensions = capabilities.extensions || []
  if (!source.name) errors.push('name 必填')
  else if (source.name.length > 100) errors.push('name 长度不能超过 100 字符')
  else if (!NAME_RE.test(source.name)) errors.push('name 仅允许字母、数字、下划线、连字符，单词间可用空格')
  if (!source.description) errors.push('description 必填')
  else if (source.description.length > 1000) errors.push('description 长度不能超过 1000 字符')
  if (!source.version) errors.push('version 必填')
  else if (source.version.length > 50) errors.push('version 长度不能超过 50 字符')
  if (!provider.organization) errors.push('provider.organization 必填')
  if (skills.length === 0) errors.push('至少需要一个技能 (skills)')
  skills.forEach((skill, index) => {
    if (!skill.id) errors.push(`技能 #${index + 1}: id 必填`)
    if (!skill.name) errors.push(`技能 #${index + 1}: name 必填`)
    if (!skill.description) errors.push(`技能 #${index + 1}: description 必填`)
  })
  if (interfaces.length === 0) errors.push('至少需要一个接口 (supportedInterfaces)')
  else if (interfaces.length > MAX_INTERFACES) errors.push(`接口数量不能超过 ${MAX_INTERFACES}`)
  interfaces.forEach((itf, index) => {
    if (!itf.url) errors.push(`接口 #${index + 1}: url 必填`)
    if (!itf.protocolBinding) errors.push(`接口 #${index + 1}: protocolBinding 必填`)
  })
  if (extensions.length > MAX_EXTENSIONS) errors.push(`扩展数量不能超过 ${MAX_EXTENSIONS}`)
  extensions.forEach((ext, index) => {
    if (!ext.uri) errors.push(`扩展 #${index + 1}: uri 必填`)
  })
  return errors
}

export default function AgentCardForm({ value, onChange }) {
  const [form, setForm] = useState(() => toForm(value))
  const lastEmitted = useRef(null)

  useEffect(() => {
    if (value !== lastEmitted.current) {
      lastEmitted.current = value
      setForm(toForm(value))
    }
  }, [value])

  function patchForm(patch) {
    const next = { ...form, ...patch }
    setForm(next)
    const card = toCard(next)
    lastEmitted.current = card
    onChange(card)
  }

  function updateExtension(index, patch) {
    patchForm({ extensions: form.extensions.map((ext, i) => (i === index ? { ...ext, ...patch } : ext)) })
  }

  function updateSkill(index, patch) {
    patchForm({ skills: form.skills.map((skill, i) => (i === index ? { ...skill, ...patch } : skill)) })
  }

  function updateInterface(index, patch) {
    patchForm({ interfaces: form.interfaces.map((itf, i) => (i === index ? { ...itf, ...patch } : itf)) })
  }

  return (
    <div className="agentcard-form">
      <div className="form-section"><span>基本信息</span></div>
      <div className="form-grid">
        <Field label="名称 *" hint="仅字母/数字/-/_和单个空格，≤100 字符">
          <input value={form.name} onChange={(e) => patchForm({ name: e.target.value })} placeholder="例如 RAN Energy Saving Agent" />
        </Field>
        <Field label="版本 *" hint="≤50 字符">
          <input value={form.version} onChange={(e) => patchForm({ version: e.target.value })} placeholder="例如 1.0.0" />
        </Field>
        <Field full label="描述 *" hint="≤1000 字符，禁止控制字符">
          <textarea rows={3} value={form.description} onChange={(e) => patchForm({ description: e.target.value })} placeholder="例如 负责RAN能效优化的自主闭环运行，包括意图探索、意图实现、效果评估与报告。" />
        </Field>
      </div>
      <div className="form-section"><span>提供者</span></div>
      <div className="form-grid">
        <Field label="组织 *">
          <input value={form.providerOrganization} onChange={(e) => patchForm({ providerOrganization: e.target.value })} placeholder="例如 Huawei" />
        </Field>
        <Field label="提供者 URL">
          <input value={form.providerUrl} onChange={(e) => patchForm({ providerUrl: e.target.value })} placeholder="例如 https://www.huawei.com" />
        </Field>
      </div>
      <div className="form-section"><span>能力</span></div>
      <div className="form-checks">
        <label className="form-check">
          <input type="checkbox" checked={form.streaming} onChange={(e) => patchForm({ streaming: e.target.checked })} />
          <span>streaming</span>
        </label>
        <label className="form-check">
          <input type="checkbox" checked={form.pushNotifications} onChange={(e) => patchForm({ pushNotifications: e.target.checked })} />
          <span>pushNotifications</span>
        </label>
      </div>
      <div className="form-section">
        <span>扩展 extensions</span>
        <span className="form-counter">{form.extensions.length}/{MAX_EXTENSIONS}</span>
      </div>
      {form.extensions.map((ext, index) => (
        <div key={index} className="sub-card">
          <div className="sub-head">
            <span className="sub-index">#{index + 1}</span>
            <button className="btn ghost small sub-remove" title="删除" onClick={() => patchForm({ extensions: form.extensions.filter((_, i) => i !== index) })}>✕</button>
          </div>
          <div className="form-grid">
            <Field full label="扩展 URI *" hint="最多 10 条，每条需含 URI">
              <input className="mono-input" value={ext.uri} onChange={(e) => updateExtension(index, { uri: e.target.value })} placeholder="https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1" />
            </Field>
            <Field full label="扩展描述">
              <input value={ext.description} onChange={(e) => updateExtension(index, { description: e.target.value })} placeholder="例如 Task-T 结构化提示请求" />
            </Field>
          </div>
        </div>
      ))}
      {form.extensions.length === 0 && <div className="muted" style={{ marginBottom: 8 }}>暂无扩展</div>}
      <button className="btn ghost small" onClick={() => patchForm({ extensions: [...form.extensions, { uri: '', description: '' }] })} disabled={form.extensions.length >= MAX_EXTENSIONS}>添加扩展</button>
      <div className="form-section">
        <span>技能 skills</span>
        <span className="form-counter">{form.skills.length}/{MAX_SKILLS}</span>
      </div>
      {form.skills.map((skill, index) => (
        <div key={index} className="sub-card">
          <div className="sub-head">
            <span className="sub-index">#{index + 1}</span>
            <button className="btn ghost small sub-remove" title="删除技能" onClick={() => patchForm({ skills: form.skills.filter((_, i) => i !== index) })}>✕</button>
          </div>
          <div className="form-grid">
            <Field label="技能 ID *" hint="最多 100 条，每条 id/名称/描述必填">
              <input className="mono-input" value={skill.id} onChange={(e) => updateSkill(index, { id: e.target.value })} placeholder="例如 ran-es-intent-exploration" />
            </Field>
            <Field label="技能名称 *">
              <input value={skill.name} onChange={(e) => updateSkill(index, { name: e.target.value })} placeholder="例如 RAN ES Intent Exploration" />
            </Field>
            <Field full label="技能描述 *">
              <textarea rows={2} value={skill.description} onChange={(e) => updateSkill(index, { description: e.target.value })} placeholder="例如 评估并确定指定RAN ES意图目标的最佳可能性" />
            </Field>
            <Field full label="标签">
              <input value={skill.tags} onChange={(e) => updateSkill(index, { tags: e.target.value })} placeholder="例如 wireless, energy-saving, intent" />
            </Field>
          </div>
        </div>
      ))}
      {form.skills.length === 0 && <div className="muted" style={{ marginBottom: 8 }}>暂无技能，注册前至少需要一个技能</div>}
      <button className="btn ghost small" onClick={() => patchForm({ skills: [...form.skills, { id: '', name: '', description: '', tags: '' }] })} disabled={form.skills.length >= MAX_SKILLS}>添加技能</button>
      <div className="form-section">
        <span>接口</span>
        <span className="form-counter">{form.interfaces.length}/{MAX_INTERFACES}</span>
      </div>
      <div className="iface-table">
        <div className="iface-row iface-head">
          <span>URL</span>
          <span>协议绑定</span>
          <span>协议版本</span>
          <span />
        </div>
        {form.interfaces.map((itf, index) => (
          <div className="iface-row" key={index}>
            <input className="mono-input" value={itf.url} onChange={(e) => updateInterface(index, { url: e.target.value })} placeholder="例如 http://127.0.0.1:8080/" />
            <select value={itf.protocolBinding} onChange={(e) => updateInterface(index, { protocolBinding: e.target.value })}>
              {BINDINGS.map((binding) => (
                <option key={binding} value={binding}>{binding}</option>
              ))}
            </select>
            <input className="mono-input" value={itf.protocolVersion} onChange={(e) => updateInterface(index, { protocolVersion: e.target.value })} placeholder="例如 1.0.0" />
            <button type="button" className="icon-btn" title="删除此接口" disabled={form.interfaces.length <= 1} onClick={() => patchForm({ interfaces: form.interfaces.filter((_, i) => i !== index) })}>✕</button>
          </div>
        ))}
      </div>
      {form.interfaces.length === 0 && <div className="muted" style={{ marginBottom: 8 }}>暂无接口，注册前至少需要一个接口</div>}
      <button type="button" className="btn ghost small" onClick={() => patchForm({ interfaces: [...form.interfaces, { url: '', protocolBinding: 'HTTP+JSON', protocolVersion: '1.0.0' }] })} disabled={form.interfaces.length >= MAX_INTERFACES}>+ 添加接口</button>
      <div className="form-hint">1~3 条；每条 URL 必填，协议绑定与版本必填</div>
      <div className="form-section"><span>模式</span></div>
      <div className="form-grid">
        <Field label="输入模式" hint="逗号分隔，如 text, json">
          <input value={form.defaultInputModes} onChange={(e) => patchForm({ defaultInputModes: e.target.value })} placeholder="例如 text, json" />
        </Field>
        <Field label="输出模式" hint="逗号分隔，如 text, json">
          <input value={form.defaultOutputModes} onChange={(e) => patchForm({ defaultOutputModes: e.target.value })} placeholder="例如 text, json" />
        </Field>
      </div>
    </div>
  )
}
