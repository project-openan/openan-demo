import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { getToken, setToken } from './api.js'
import { readJwtPayload } from './jwt.js'
import { getTheme, toggleTheme } from './theme.js'

function PulseIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
    </svg>
  )
}

function SunIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  )
}

function LogoutIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="m16 17 5-5-5-5" />
      <path d="M21 12H9" />
    </svg>
  )
}

export default function Layout({ children }) {
  const payload = readJwtPayload()
  const [theme, setThemeState] = useState(getTheme())
  const [settingsOpen, setSettingsOpen] = useState(false)
  const location = useLocation()
  useEffect(() => {
    setSettingsOpen(false)
  }, [location.pathname])
  function flipTheme() {
    setThemeState(toggleTheme())
  }
  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-icon"><PulseIcon /></span>
          <span>
            <div className="brand-title">OpenAN-Debug</div>
            <div className="brand-subtitle">A2A-T 联调打桩调试台</div>
          </span>
        </div>
        <nav className="nav">
          <NavLink to="/registry">注册中心调测</NavLink>
          <NavLink to="/orchestration">编排中心调测</NavLink>
          <NavLink to="/execution">执行中心调测</NavLink>
          <NavLink to="/" end>A2A-T SDK 调测</NavLink>
          <NavLink to="/dataset">数据集</NavLink>
          <NavLink to="/ontology">本体调测</NavLink>
          <NavLink to="/settings/agents">MockAgent</NavLink>
          <div className={`nav-dropdown${settingsOpen ? ' open' : ''}`}>
            <button
              type="button"
              className="nav-dropdown-toggle"
              onClick={() => setSettingsOpen((open) => !open)}
            >
              设置 <span className="nav-caret">▾</span>
            </button>
            {settingsOpen && (
              <div className="nav-menu">
                <NavLink to="/seeds">种子/变体</NavLink>
                <NavLink to="/settings">服务地址</NavLink>
                {payload.role === 'admin' && <NavLink to="/users">用户管理</NavLink>}
              </div>
            )}
          </div>
        </nav>
        <div className="header-spacer" />
        <span className="user-badge">{payload.sub || '未登录'} · {payload.role || '-'}</span>
        <button className="icon-btn" onClick={flipTheme} title={theme === 'dark' ? '切换浅色主题' : '切换深色主题'}>
          {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
        </button>
        <a
          className="icon-btn"
          href="#logout"
          title="退出登录"
          onClick={(event) => {
            event.preventDefault()
            setToken('')
            window.location.href = '/debug/'
          }}
        >
          <LogoutIcon />
        </a>
      </header>
      <main className="content">{children}</main>
    </div>
  )
}
