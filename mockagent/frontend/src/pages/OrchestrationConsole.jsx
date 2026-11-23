import PostmanConsole from '../components/PostmanConsole.jsx'
import { ORCHESTRATION_ENDPOINTS } from '../endpoints.js'
import Layout from '../Layout.jsx'

const FOLDERS = [
  { key: 'browse', label: '工作流与卡片', items: ['workflows', 'cards'] },
  { key: 'intent', label: '意图与执行', items: ['intent', 'search', 'execute', 'executeById', 'dispatch'] },
  { key: 'records', label: '执行记录', items: ['executions', 'records'] },
]

export default function OrchestrationConsolePage() {
  return (
    <Layout>
      <PostmanConsole
        feature="orchestration"
        title="编排中心调测"
        subtitle="PSOP 生成 / 搜索 / 执行（SSE） / 执行记录"
        targetKey="orchestrationUrl"
        targetLabel="orchestration"
        endpoints={ORCHESTRATION_ENDPOINTS}
        folders={FOLDERS}
      />
    </Layout>
  )
}
