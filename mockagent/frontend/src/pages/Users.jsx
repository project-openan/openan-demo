import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import Layout from '../Layout.jsx'

export default function UsersPage() {
  const [users, setUsers] = useState([])
  const [draft, setDraft] = useState({ username: '', password: '', role: 'user' })
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setUsers(await api.get('/debug/api/v1/users'))
  }, [])

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [load])

  async function create(event) {
    event.preventDefault()
    setError('')
    try {
      await api.post('/debug/api/v1/users', draft)
      setDraft({ username: '', password: '', role: 'user' })
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  async function toggle(user) {
    await api.patch(`/debug/api/v1/users/${user.id}`, { enabled: !user.enabled })
    load()
  }

  return (
    <Layout>
      <h2>用户管理</h2>
      {error && <div className="error-text">{error}</div>}
      <div className="card">
        <h2>新建用户</h2>
        <form className="filters" onSubmit={create}>
          <input placeholder="用户名" value={draft.username} onChange={(e) => setDraft({ ...draft, username: e.target.value })} />
          <input placeholder="密码（>=8位）" type="password" value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} />
          <select value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })}>
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
          <button type="submit">创建</button>
        </form>
      </div>
      <div className="card">
        <table>
          <thead><tr><th>ID</th><th>用户名</th><th>角色</th><th>启用</th><th>操作</th></tr></thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id}>
                <td className="num">{user.id}</td>
                <td>{user.username}</td>
                <td><span className={`badge ${user.role === 'admin' ? 'indigo' : 'neutral'}`}>{user.role}</span></td>
                <td><span className={`badge ${user.enabled ? 'success' : 'danger'}`}>{user.enabled ? '是' : '否'}</span></td>
                <td><button className="ghost" onClick={() => toggle(user)}>{user.enabled ? '禁用' : '启用'}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Layout>
  )
}
