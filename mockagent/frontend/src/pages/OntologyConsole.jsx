import PostmanConsole from '../components/PostmanConsole.jsx'
import { ONTOLOGY_ENDPOINTS } from '../endpoints.js'
import Layout from '../Layout.jsx'

const FOLDERS = [
  { key: 'service', label: '服务状态', items: ['health'] },
  { key: 'reasoning', label: '本体推理', items: ['runs'] },
]

export default function OntologyConsolePage() {
  return (
    <Layout>
      <PostmanConsole
        feature="ontology"
        title="本体服务调测"
        subtitle="健康检查 / 本体推理（NDJSON 事件流）"
        targetKey="ontologyUrl"
        targetLabel="ontology"
        endpoints={ONTOLOGY_ENDPOINTS}
        folders={FOLDERS}
      />
    </Layout>
  )
}
