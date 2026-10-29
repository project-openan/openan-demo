import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api.js'
import Layout from '../Layout.jsx'

const HISTORY_KEY = 'openan-debug-cli-history'
const MAX_HISTORY = 100
const MAX_LINES = 800

// 命令词汇表：Tab 补全用（与 server/openan_debug/a2at_cli.py 保持一致）
const VOCAB = {
  card: ['get'],
  agent: ['list'],
  send: ['-a', '--agent', '--template', '-m', '--message', '--stream', '-s', '--async', '--wait', '--timeout', '--context', '--json'],
  task: ['get', 'list', 'cancel', '-a', '--agent', '--timeout', '--json'],
  help: [],
  version: [],
}
const ROOT_COMMANDS = ['card', 'agent', 'send', 'task', 'help', 'version']

let lineSeq = 0
function makeLine(type, text) {
  lineSeq += 1
  return { id: lineSeq, type, text }
}

export default function A2atCliPage() {
  const { t } = useTranslation()
  const [lines, setLines] = useState(() => [
    makeLine('sys', t('cli.welcome1')),
    makeLine('sys', t('cli.welcome2')),
    makeLine('sys', ''),
  ])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [history, setHistory] = useState(() => {
    try {
      const raw = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
      return Array.isArray(raw) ? raw.filter((x) => typeof x === 'string') : []
    } catch {
      return []
    }
  })
  const [historyIndex, setHistoryIndex] = useState(-1)
  const [tabState, setTabState] = useState({ prefix: '', options: null, index: 0 })

  const outputRef = useRef(null)
  const inputRef = useRef(null)
  const busyRef = useRef(false)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  useEffect(() => {
    const node = outputRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [lines, busy])

  const appendLines = useCallback((items) => {
    setLines((prev) => {
      const next = [...prev, ...items]
      return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next
    })
  }, [])

  const pushLines = useCallback((...items) => {
    appendLines(items.map(([type, text]) => makeLine(type, text)))
  }, [appendLines])

  const runCommand = useCallback(async (raw) => {
    const command = raw.trim()
    if (!command || busyRef.current) return
    pushLines(['cmd', `a2at> ${command}`])
    setHistory((prev) => {
      const next = [command, ...prev.filter((item) => item !== command)].slice(0, MAX_HISTORY)
      try {
        localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
      } catch {
        /* ignore quota */
      }
      return next
    })
    setHistoryIndex(-1)
    setInput('')
    setBusy(true)
    busyRef.current = true
    const startedAt = Date.now()
    try {
      const result = await api.post('/debug/api/v1/a2at-cli/exec', { command })
      if (Array.isArray(result.stdout) && result.stdout.length) {
        appendLines(result.stdout.map((text) => makeLine('out', text)))
      }
      if (Array.isArray(result.stderr) && result.stderr.length) {
        appendLines(result.stderr.map((text) => makeLine('err', text)))
      }
      if (result.json != null) {
        appendLines([makeLine('json', JSON.stringify(result.json, null, 2))])
      }
      const ms = result.durationMs != null ? ` · ${result.durationMs}ms` : ''
      pushLines(['meta', `${t('cli.exit', { code: result.exitCode ?? '-' })}${ms}`])
      pushLines(['sys', ''])
    } catch (error) {
      pushLines(['err', t('cli.loadFailed', { message: error.message || error })], ['sys', ''])
    } finally {
      setBusy(false)
      busyRef.current = false
      inputRef.current?.focus()
    }
  }, [appendLines, pushLines, t])

  function completeToken() {
    const match = input.match(/(\S*)$/)
    const token = match ? match[1] : ''
    const head = input.slice(0, input.length - token.length).trim().split(/\s+/).filter(Boolean)
    let options = []
    if (head.length === 0 || (head.length === 1 && head[0].toLowerCase() === 'a2at')) {
      const prefix = token.toLowerCase()
      options = ROOT_COMMANDS.filter((c) => c.startsWith(prefix))
    } else {
      const root = head[0].toLowerCase() === 'a2at' ? (head[1] || '').toLowerCase() : head[0].toLowerCase()
      const vocab = VOCAB[root]
      if (vocab) options = vocab.filter((flag) => flag.startsWith(token))
    }
    if (options.length === 0) return
    setTabState((prev) => {
      const samePrefix = prev.prefix === token
      const index = samePrefix ? (prev.index + 1) % options.length : 0
      setInput(input.slice(0, input.length - token.length) + options[index])
      return { prefix: token, index }
    })
  }

  function onInputChange(event) {
    setInput(event.target.value)
    setTabState({ prefix: '', options: null, index: 0 })
  }

  function onInputKeyDown(event) {
    if (event.key === 'Enter') {
      event.preventDefault()
      runCommand(input)
      return
    }
    if (event.key === 'Tab') {
      event.preventDefault()
      completeToken()
      return
    }
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault()
      if (history.length === 0) return
      let index = historyIndex
      if (event.key === 'ArrowUp') index = Math.min(index + 1, history.length - 1)
      else index = Math.max(index - 1, -1)
      setHistoryIndex(index)
      setInput(index >= 0 ? history[index] : '')
      return
    }
    if (event.key === 'l' && event.ctrlKey) {
      event.preventDefault()
      setLines([])
    }
  }

  const chips = useMemo(() => [
    'a2at help',
    'a2at version',
    'a2at card get',
    'a2at agent list',
    'a2at send -a default -m "查询专线状态"',
    'a2at send -a default --stream -m "订阅严重故障告警"',
    'a2at task list',
  ], [])

  function clearScreen() {
    setLines([])
    inputRef.current?.focus()
  }

  async function copyTranscript() {
    const text = lines.map((line) => (line.type === 'cmd' ? `a2at> ${line.text}` : line.text)).join('\n')
    try {
      await navigator.clipboard.writeText(text)
      pushLines(['sys', t('cli.copied')])
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <Layout>
      <div className="cli-page">
        <div className="pm-topbar">
          <div>
            <div className="pm-title">{t('cli.title')}</div>
            <div className="pm-sub">{t('cli.subtitle')}</div>
          </div>
          <div className="pm-topbar-side">
            <button type="button" className="btn ghost small" onClick={copyTranscript}>{t('cli.copy')}</button>
            <button type="button" className="btn ghost small" onClick={clearScreen}>{t('cli.clear')}</button>
          </div>
        </div>

        <div className="cli-chips">
          {chips.map((chip) => (
            <button
              key={chip}
              type="button"
              className="cli-chip"
              title={chip}
              onClick={() => runCommand(chip)}
              disabled={busy}
            >
              {chip}
            </button>
          ))}
        </div>

        <div className="cli-terminal" onClick={() => inputRef.current?.focus()}>
          <div className="cli-output" ref={outputRef}>
            {lines.map((line) => (
              <div key={line.id} className={`cli-line ${line.type}`}>{line.text || '\u00A0'}</div>
            ))}
            {busy && <div className="cli-line sys">{t('cli.running')}</div>}
          </div>
          <div className="cli-input-row">
            <span className="cli-prompt">a2at&gt;</span>
            <input
              ref={inputRef}
              className="cli-input"
              value={input}
              onChange={onInputChange}
              onKeyDown={onInputKeyDown}
              placeholder={t('cli.placeholder')}
              spellCheck={false}
              autoComplete="off"
              disabled={busy}
            />
          </div>
        </div>
        <div className="muted cli-hint">{t('cli.hint')}</div>
      </div>
    </Layout>
  )
}
