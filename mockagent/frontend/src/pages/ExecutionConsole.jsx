import PostmanConsole from '../components/PostmanConsole.jsx'
import { EXECUTION_ENDPOINTS } from '../endpoints.js'
import Layout from '../Layout.jsx'

const FOLDERS = [
  { key: 'message', label: 'A2A 消息', items: ['send', 'stream'] },
  { key: 'tasks', label: '任务管理', items: ['tasks', 'task', 'cancel'] },
]

export default function ExecutionConsolePage() {
  return (
    <Layout>
      <PostmanConsole
        feature="execution"
        title="执行中心调测"
        subtitle="宿主 Agent A2A 消息（含 SSE 流式） / 任务管理"
        targetKey="executionHostUrl"
        targetLabel="execution"
        endpoints={EXECUTION_ENDPOINTS}
        folders={FOLDERS}
      />
    </Layout>
  )
}
