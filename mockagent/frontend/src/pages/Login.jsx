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
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, setToken } from '../api.js'

function PulseIcon() {
  return (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
    </svg>
  )
}

export default function LoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  async function submit(event) {
    event.preventDefault()
    setError('')
    try {
      const result = await api.post('/debug/api/v1/auth/login', { username, password })
      setToken(result.token)
      navigate('/')
    } catch (err) {
      setError(err.message || '登录失败')
    }
  }

  return (
    <div className="login-page">
      <form className="login-box card" onSubmit={submit}>
        <span className="login-icon"><PulseIcon /></span>
        <div className="login-title">OpenAN-Debug 登录</div>
        <div className="login-subtitle">A2A-T 联调打桩调试台</div>
        <input placeholder="用户名" value={username} onChange={(e) => setUsername(e.target.value)} />
        <input placeholder="密码" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <div className="error-text">{error}</div>}
        <button type="submit">登录</button>
      </form>
    </div>
  )
}
