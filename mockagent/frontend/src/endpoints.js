const A2A_SEND_EXAMPLE = {
  message: {
    messageId: '请替换为UUID',
    role: 'ROLE_USER',
    parts: [{ text: 'debug task' }],
    metadata: {
      templateUri: 'Task-T/network-layer/private-line-complaint/v1',
      'https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1': '<A2A-T 渲染后的 prompt 文本>',
    },
  },
}

export const REGISTRY_ENDPOINTS = [
  { key: 'list', label: '查询 Agent 卡片列表', method: 'GET', path: '/rest/v1/registry-center/agent-cards?includeStatus=true', note: '支持 ?name=&organization= 过滤；返回全部卡片（含待审批）。includeStatus=true 时每张卡附 publishStatus（编排等严格 proto 客户端请勿开启）', exampleBody: null },
  { key: 'get', label: '查询单个 Agent 卡片', method: 'GET', path: '/rest/v1/registry-center/agent-cards/OpenAN/Demo-Agent?includeStatus=true', note: '按组织+名称精确查询，不区分发布状态；includeStatus=true 时附 publishStatus', exampleBody: null },
  {
    key: 'register',
    label: '注册 Agent 卡片',
    method: 'POST',
    path: '/rest/v1/registry-center/agent-cards',
    bodyEditor: 'agentcard',
    note: '生产开启签名校验时需携带 signatures；开发实例可关闭校验',
    exampleBody: {
      agentCards: [{
        name: 'Demo Agent',
        description: '演示用 Agent 卡片',
        version: '1.0.0',
        provider: { organization: 'OpenAN', url: 'https://example.com' },
        skills: [{ id: 's1', name: '示例技能', description: '演示技能', tags: ['demo'] }],
        capabilities: { streaming: true, pushNotifications: false, extensions: [] },
        supportedInterfaces: [{ url: 'http://127.0.0.1:8080/', protocolBinding: 'HTTP+JSON', protocolVersion: '1.0.0' }],
        defaultInputModes: ['text/plain'],
        defaultOutputModes: ['application/json'],
      }],
    },
  },
  { key: 'update', label: '更新 Agent 卡片', method: 'PUT', path: '/rest/v1/registry-center/agent-cards/OpenAN/Demo-Agent', note: '路径为 {organization}/{name}，需与卡片内容一致；替换路径后发送', bodyEditor: 'agentcard' },
  { key: 'semantic', label: '语义查询 Agent', method: 'POST', path: '/rest/v1/registry-center/agent-cards/semantic-query', exampleBody: { task: '需要做全网节能优化' } },
  { key: 'delete', label: '注销 Agent 卡片', method: 'DELETE', path: '/rest/v1/registry-center/agent-cards/OpenAN/Demo-Agent', exampleBody: null },
  { key: 'manage', label: '管理列表（含发布状态）', method: 'GET', path: '/rest/v1/registry-center/agent-cards/manage', note: '返回全部卡片并附 publishStatus（与查询列表行为一致）', exampleBody: null },
  { key: 'publish', label: '发布审批（registered→published）', method: 'POST', path: '/rest/v1/registry-center/agent-cards/{organization}/{name}/publish', note: '替换路径中的 {organization}/{name}；body 必须含非空 remark 审批备注，成功后卡片才可被查询到', exampleBody: { remark: '联调通过，允许发布' } },
  { key: 'keys', label: '查询 JWKS 公钥', method: 'GET', path: '/rest/v1/registry-center/keys', exampleBody: null },
]

export const ORCHESTRATION_ENDPOINTS = [
  { key: 'workflows', label: '工作流列表', method: 'GET', path: '/rest/v1/orchestrate/workflows?limit=10', exampleBody: null },
  { key: 'cards', label: 'Agent 卡片列表（经注册中心）', method: 'GET', path: '/rest/v1/orchestrate/agent-cards', exampleBody: null },
  { key: 'intent', label: '意图生成 PSOP', method: 'POST', path: '/api/v1/orchestrate/intent', exampleBody: { intent: '帮我做全网节能优化', name: '节能评估' } },
  { key: 'search', label: '语义搜索工作流', method: 'POST', path: '/api/v1/orchestrate/search', exampleBody: { intent: '网络故障根因分析', top_n: 3 } },
  { key: 'execute', label: '执行工作流（SSE 事件流）', method: 'POST', path: '/api/v1/orchestrate/execute', note: '自动搜索或生成 PSOP 并执行，返回 SSE 事件流转写', exampleBody: { task: '帮我做网络故障根因分析' } },
  { key: 'executeById', label: '按 PSOP ID 执行（SSE）', method: 'GET', path: '/api/v1/orchestrate/execute/{psop_id}?user_intent=&lang=zh', note: '替换路径中的 {psop_id}', exampleBody: null },
  { key: 'dispatch', label: '按意图派发宿主 Agent（SSE）', method: 'GET', path: '/rest/v1/orchestrate/dispatch?intent=查询设备告警&agent_name=&lang=zh', exampleBody: null },
  { key: 'executions', label: '执行记录列表', method: 'GET', path: '/api/v1/executions', exampleBody: null },
  { key: 'records', label: '内部执行记录', method: 'GET', path: '/rest/v1/orchestrate/execution-records', exampleBody: null },
]

export const EXECUTION_ENDPOINTS = [
  { key: 'send', label: 'A2A 消息发送（非流式）', method: 'POST', path: '/message:send', note: '目标为宿主 Agent 的 A2A 端点（默认本系统 Mock Agent，可在设置→服务地址中改为其他宿主 Agent）；需携带 A2A-Version 头', defaultHeaders: { 'A2A-Version': '1.0' }, exampleBody: A2A_SEND_EXAMPLE },
  { key: 'stream', label: 'A2A 消息发送（SSE 流式）', method: 'POST', path: '/message:stream', defaultHeaders: { 'A2A-Version': '1.0' }, exampleBody: A2A_SEND_EXAMPLE },
  { key: 'tasks', label: '任务列表', method: 'GET', path: '/tasks', defaultHeaders: { 'A2A-Version': '1.0' }, exampleBody: null },
  { key: 'task', label: '任务详情', method: 'GET', path: '/tasks/{task_id}', defaultHeaders: { 'A2A-Version': '1.0' }, exampleBody: null },
  { key: 'cancel', label: '取消任务', method: 'POST', path: '/tasks/{task_id}:cancel', defaultHeaders: { 'A2A-Version': '1.0' }, exampleBody: null },
]

export const ONTOLOGY_ENDPOINTS = [
  { key: 'health', label: '健康检查', method: 'GET', path: '/api/health', exampleBody: null },
  { key: 'runs', label: '运行本体推理（NDJSON 事件流）', method: 'POST', path: '/api/runs', note: '返回 NDJSON 事件流转写（run.started/ontology.focus/agent.message/a2at.request/a2at.response/run.completed）', exampleBody: { input: '查询设备告警并订阅严重故障' } },
]
