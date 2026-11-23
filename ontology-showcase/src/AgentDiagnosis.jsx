import { useCallback, useEffect, useRef, useState } from 'react'
import ReasoningTree from './ReasoningTree'

function connectFaultOperationHistory(steps) {
  return steps.map((focus, index) => {
    const isAwareness = index === 0
    const isDecision = index === steps.length - 1
    const operationNodes = isAwareness
      ? ['TaskFaultAwareness']
      : isDecision
        ? ['TaskFaultAwareness', 'TaskProblemAnalysis', 'TaskSolutionDecision']
        : ['TaskFaultAwareness', 'TaskProblemAnalysis']
    const operationLinks = isAwareness
      ? []
      : isDecision
        ? ['故障流进入定界定位', '定界定位支撑方案决策']
        : ['故障流进入定界定位']
    return {
      ...focus,
      nodes: [...operationNodes, ...(focus.nodes || [])],
      links: [...operationLinks, ...(focus.links || [])],
    }
  })
}

function connectFaultOperationConclusion(focus) {
  return {
    ...focus,
    nodes: ['TaskFaultAwareness', 'TaskProblemAnalysis', 'TaskSolutionDecision', ...(focus.nodes || [])],
    links: ['故障流进入定界定位', '定界定位支撑方案决策', ...(focus.links || [])],
  }
}

function focusHistoryForRecord(record) {
  const solutionLayerFullNodes = ['CatDevice', 'CatConnection', 'CatService', 'CatClock', 'CatEnvironment', 'CatProtocol', 'CatCrossDomain']
  if (record.category === 'billing') {
    const billingLinks = ['跨专业信息关联业务']
    return [
      { actor: '账单核对', label: '同一账期出现两笔金额相同费用', nodes: solutionLayerFullNodes, links: [] },
      { actor: '订购核对', label: '从订购关系与计费周期排除跨账期补收', nodes: ['CatService', 'CatCrossDomain'], links: billingLinks },
      { actor: '优惠核对', label: '确认优惠规则未执行导致重复金额', nodes: ['CatService', 'CatCrossDomain'], links: billingLinks },
      { actor: '处理结论', label: '形成完整依据，后续生成计费冲正单', nodes: ['CatService', 'CatCrossDomain'], links: billingLinks, zoomScale: 0.92 },
    ]
  }
  if (record.category === 'optical') {
    const usedLinks = ['连接质量影响业务']
    return connectFaultOperationHistory([
      { actor: '范围梳理', label: 'PON口丢包超阈，相关故障类型同步展开', nodes: solutionLayerFullNodes, links: [] },
      { actor: '类型初判', label: '丢包现象关联到连接、设备及协议状态', nodes: ['CatDevice', 'CatConnection', 'CatService', 'CatProtocol'], links: ['设备状态影响连接', '协议状态影响连接', '连接质量影响业务'] },
      { actor: '运行核对', label: '端口误码与丢包时段一致，保留连接类路径', nodes: ['CatConnection', 'CatService'], links: usedLinks },
      { actor: '信息缺口', label: '边界端口光功率尚未返回，向OMC发起查询', nodes: ['CatConnection', 'CatService', 'LinkFault'], links: [...usedLinks, '连接类→链路故障'] },
      { actor: '状态补全', label: 'OMC返回光模块收发光功率与告警状态', nodes: ['CatConnection', 'CatService', 'LinkFault', 'OpticalModule'], links: [...usedLinks, '连接类→链路故障', '链路→光模块根因'] },
      { actor: '诊断结论', label: '光模块接收光功率异常，定位为光模块故障', nodes: ['CatConnection', 'CatService', 'LinkFault', 'OpticalModule'], links: [...usedLinks, '连接类→链路故障', '链路→光模块根因'], zoomScale: 0.92 },
    ])
  }
  if (record.category === 'device') {
    const usedLinks = ['设备状态影响连接', '连接质量影响业务']
    return connectFaultOperationHistory([
      { actor: '范围梳理', label: '网元离线，相关故障类型同步展开', nodes: solutionLayerFullNodes, links: [] },
      { actor: '类型初判', label: '运行现象关联到设备、连接及外部条件', nodes: ['CatDevice', 'CatConnection', 'CatEnvironment', 'CatProtocol', 'CatCrossDomain'], links: ['环境变化影响设备运行', '设备状态影响连接', '协议状态影响连接', '外部条件影响运行环境', '跨专业状态影响连接'] },
      { actor: '运行核对', label: '离线时间与设备状态一致，继续核对连接影响', nodes: ['CatDevice', 'CatConnection', 'CatService'], links: usedLinks },
      { actor: '信息缺口', label: '设备侧状态尚未返回，向OMC发起查询', nodes: ['CatDevice', 'CatConnection', 'CatService', 'DeviceOffline'], links: [...usedLinks, '设备类→设备离线'] },
      { actor: '状态补全', label: 'OMC返回网元状态，关联单板与供电情况', nodes: ['CatDevice', 'CatConnection', 'CatService', 'DeviceOffline', 'BoardFault', 'PowerFault'], links: [...usedLinks, '设备类→设备离线', '离线→单板根因', '离线→供电根因'] },
      { actor: '诊断结论', label: '确认主控板未复位，定位为单板故障', nodes: ['CatDevice', 'CatConnection', 'CatService', 'DeviceOffline', 'BoardFault'], links: [...usedLinks, '设备类→设备离线', '离线→单板根因'], zoomScale: 0.92 },
    ])
  }
  const usedLinks = ['跨专业状态影响连接', '连接质量影响业务']
  return connectFaultOperationHistory([
    { actor: '范围梳理', label: '专线可用率下降，相关故障类型同步展开', nodes: solutionLayerFullNodes, links: [] },
    { actor: '类型初判', label: '业务变化关联到连接、设备及跨专业状态', nodes: ['CatDevice', 'CatConnection', 'CatService', 'CatProtocol', 'CatCrossDomain'], links: ['设备状态影响连接', '协议状态影响连接', '连接质量影响业务', '跨专业状态影响连接', '跨专业信息关联业务'] },
    { actor: '运行核对', label: '承载告警与业务变化一致，保留连接影响路径', nodes: ['CatCrossDomain', 'CatConnection', 'CatService'], links: usedLinks },
    { actor: '信息缺口', label: '边界承载状态尚未返回，向OMC发起查询', nodes: ['CatCrossDomain', 'CatConnection', 'CatService', 'TunnelFault'], links: [...usedLinks, '业务类→隧道故障'] },
    { actor: '状态补全', label: 'OMC返回承载状态，关联尾纤与光模块', nodes: ['CatCrossDomain', 'CatConnection', 'CatService', 'TunnelFault', 'FiberFault', 'OpticalModule'], links: [...usedLinks, '业务类→隧道故障', '隧道→光纤根因', '隧道→光模块根因'] },
    { actor: '诊断结论', label: '尾纤光功率异常与业务劣化吻合，定位为尾纤故障', nodes: ['CatCrossDomain', 'CatConnection', 'CatService', 'TunnelFault', 'FiberFault'], links: [...usedLinks, '业务类→隧道故障', '隧道→光纤根因'], zoomScale: 0.92 },
  ])
}
const seedInput = 'SQI探针检测到广州天河政企专线 GD-DL-2048 可用率下降，连续3个周期丢包率超过5%。'
const seedInputEN = 'An SQI probe detected declining availability on Guangzhou Tianhe enterprise dedicated line GD-DL-2048, with packet loss above 5% for three consecutive periods.'
const quickQuestions = [
  { label: '专线可用率下降', labelEN: 'Dedicated-line availability degradation', value: seedInput, valueEN: 'The availability of Guangzhou Tianhe enterprise dedicated line GD-DL-2048 has declined, with packet loss above 5% for three consecutive periods.' },
  { label: 'PON 口丢包超阈', labelEN: 'PON port packet loss above threshold', value: '广州番禺 OLT-PY-02 的 PON 0/1 连续10分钟丢包率超过3%，请分析受影响业务及关联资源。', valueEN: 'Packet loss on PON 0/1 of Guangzhou Panyu OLT-PY-02 exceeded 3% for 10 minutes. Analyze the affected services and related resources.' },
  { label: '5G 用户体验劣化', labelEN: '5G user experience degradation', value: '广州白云 5G 小区 GD-BY-5G-018 用户下行速率持续下降，请关联业务、资源与性能观测进行分析。', valueEN: 'User downlink throughput in Guangzhou Baiyun 5G cell GD-BY-5G-018 continues to decline. Analyze the related services, resources, and performance observations.' },
  { label: '网元设备离线', labelEN: 'Network element offline', value: 'PE-GZ-03 设备离线，请关联网元状态、资源告警和可能的物理故障。', valueEN: 'PE-GZ-03 is offline. Correlate network-element status, resource alarms, and possible physical faults.' },
]
const historySeed = [
  { id: 'RUN-0801-09', time: '09:42', title: '广州天河政企专线可用率下降', titleEN: 'Guangzhou Tianhe dedicated-line availability degradation', meta: '已定位 · 尾纤故障', metaEN: 'Identified · Fiber jumper fault', category: 'business', taskType: 'OTN 光专线投诉诊断', resourceId: 'f47ac10b-58cc-4372-a567-0e02b2c3d479', occurredAt: '2024-01-16T08:21:46Z', eventId: 'fault-id-1-017-20230511-09013', scene: '电路质差', query: seedInput, queryEN: seedInputEN },
  { id: 'RUN-0801-06', time: '06:52', title: '广州番禺 PON口丢包超阈', titleEN: 'Guangzhou Panyu PON-port packet-loss threshold breach', meta: '已定位 · 光模块故障', metaEN: 'Identified · Optical-module fault', category: 'optical', taskType: 'PON链路故障诊断', resourceId: 'OLT-PY-02/PON0/1', occurredAt: '2026-08-01T06:35:00Z', eventId: 'fault-pon-0801-0652', scene: 'PON口丢包', query: '广州番禺 OLT-PY-02 的 PON 0/1 连续10分钟丢包率超过3%，请分析受影响业务及关联资源。', queryEN: 'Packet loss on PON 0/1 of Guangzhou Panyu OLT-PY-02 exceeded 3% for 10 minutes. Analyze the affected services and related resources.' },
  { id: 'RUN-0731-16', time: '16:20', title: 'PE-GZ-03 设备离线', titleEN: 'PE-GZ-03 network element offline', meta: '已定位 · 单板故障', metaEN: 'Identified · Board fault', category: 'device', taskType: '网元设备状态诊断', resourceId: 'PE-GZ-03', occurredAt: '2026-07-31T16:03:00Z', eventId: 'fault-id-pe-0731-1620', scene: '网元离线', query: 'PE-GZ-03 设备离线，请关联网元状态、资源告警和可能的物理故障。', queryEN: 'PE-GZ-03 is offline. Correlate network-element status, resource alarms, and possible physical faults.' },
]
const defaultFocus = {
  actor: '系统',
  label: '等待用户输入 · 预置业务保障本体切片',
  nodes: ['SLAContract', 'ODABusiness', 'CatService'],
  links: ['商业→治理依赖', '治理→业务方案'],
}
const openingMessages = []

const avatarByType = { system: '•', reasoning: '•', decision: '•', closure: '•', oss: '•', a2a: '↔', omc: '↔', response: '↔', action: '•', error: '!' }

const uiCopy = {
  '中': {
    executionHistory: '执行记录', expandHistory: '展开执行记录', collapseHistory: '折叠执行记录', historyFilter: '按任务 / 时间检索', recentRuns: '最近执行', input: '输入', userInput: '用户输入', running: '执行中', start: '开始执行', commonQuestions: '常见问题', ontologyView: '本体推理视图', ontologySubtitle: '相关概念与关系展示', downloadOntology: 'T-Box 下载', waitingForReasoning: '等待本体推理介入', waitingForInput: '等待输入', reasoningWaiting: '当前先梳理候选路径，本体关系将在校验阶段介入。', inputWaiting: '提交诊断任务后，将加载相关本体概念与关系视图。', withoutOntology: '协同过程（without ontology）', withOntology: '协同过程（with ontology）', collaborationSubtitle: '执行记录与交互消息', waitingForUser: '待用户输入', startAfterInput: '输入诊断任务后开始。', analyzing: '分析中…', a2aMessage: 'A2A-T消息', executionRecord: '执行记录', fillInput: '请先填写用户输入', executionFailed: '后台执行失败', streamingUnsupported: '浏览器不支持流式响应', streamInterrupted: '后台事件流意外中断', executionService: '执行服务', runningStatus: '运行中', completedStatus: '已完成', stoppedStatus: '已中止',
  },
  EN: {
    executionHistory: 'Execution history', expandHistory: 'Expand execution history', collapseHistory: 'Collapse execution history', historyFilter: 'Search by task / time', recentRuns: 'Recent runs', input: 'Input', userInput: 'User input', running: 'Running', start: 'Run', commonQuestions: 'Common questions', ontologyView: 'Ontology reasoning view', ontologySubtitle: 'Related concepts and relationships', downloadOntology: 'T-Box download', waitingForReasoning: 'Waiting for ontology reasoning', waitingForInput: 'Waiting for input', reasoningWaiting: 'Candidate paths are being analyzed. Ontology relationships will be applied during validation.', inputWaiting: 'Submit a diagnostic task to load the relevant concepts and relationships.', withoutOntology: 'Collaboration process (without ontology)', withOntology: 'Collaboration process (with ontology)', collaborationSubtitle: 'Execution records and interactive messages', waitingForUser: 'Waiting for user input', startAfterInput: 'Enter a diagnostic task to begin.', analyzing: 'Analyzing…', a2aMessage: 'A2A-T message', executionRecord: 'Execution record', fillInput: 'Please enter a request first.', executionFailed: 'Execution service failed', streamingUnsupported: 'Streaming responses are not supported by this browser', streamInterrupted: 'The event stream ended unexpectedly', executionService: 'Execution service', runningStatus: 'Running', completedStatus: 'Completed', stoppedStatus: 'Stopped',
  },
}

const tokenUsageCopy = {
  '中': {
    title: 'Token 构成', total: '合计', viewDetails: '查看详情', collapse: '收起',
    assisted: ['精简后上下文', '本体推理', '模型填参', '回显分析'],
    baseline: ['模型推理', '模型填参', '回显'],
  },
  EN: {
    title: 'Token breakdown', total: 'Total', viewDetails: 'View details', collapse: 'Collapse',
    assisted: ['Pruned context', 'Ontology reasoning', 'Model parameter filling', 'Response analysis'],
    baseline: ['Model reasoning', 'Parameter filling', 'Response'],
  },
}

const tokenUsageProfiles = {
  business: {
    baseline: { total: 31786, steps: [17482, 8660, 5644] },
    assisted: { total: 22250, steps: [9662, 0, 7400, 5188] },
  },
  optical: {
    baseline: { total: 31095, steps: [17102, 8380, 5613] },
    assisted: { total: 21767, steps: [9453, 0, 7250, 5064] },
  },
  device: {
    baseline: { total: 29973, steps: [16485, 7995, 5493] },
    assisted: { total: 20981, steps: [9112, 0, 7000, 4869] },
  },
  billing: {
    baseline: { total: 30156, steps: [16586, 8000, 5570] },
    assisted: { total: 21109, steps: [9167, 0, 7000, 4942] },
  },
}

const observationProfiles = {
  business: {
    baseline: { durationMs: 92300, firstResponseMs: 2100, contextTokens: 14200 },
    assisted: { durationMs: 48600, firstResponseMs: 1500, contextTokens: 9300 },
  },
  optical: {
    baseline: { durationMs: 81600, firstResponseMs: 1900, contextTokens: 13600 },
    assisted: { durationMs: 42100, firstResponseMs: 1300, contextTokens: 8800 },
  },
  device: {
    baseline: { durationMs: 77400, firstResponseMs: 1800, contextTokens: 12800 },
    assisted: { durationMs: 39700, firstResponseMs: 1200, contextTokens: 8200 },
  },
  billing: {
    baseline: { durationMs: 54400, firstResponseMs: 1600, contextTokens: 9600 },
    assisted: { durationMs: 32800, firstResponseMs: 1100, contextTokens: 6100 },
  },
}

const observabilityCopy = {
  '中': {
    kicker: '运行观测', title: '运行详情', fallbackTitle: '网络诊断运行', close: '关闭', runId: '运行 ID', status: '状态', completed: '已完成', processSwitcher: '运行过程', processOne: '过程一', processTwo: '过程二',
    totalTokens: 'Token 总量', tokenRate: '全局 Token 生成速率', interaction: '交互信息', context: '上下文使用', tokens: 'tokens', messages: '消息', messageCount: '条消息', a2aRounds: 'A2A-T 轮', toolCalls: '条消息', input: '输入', output: '输出', firstResponse: '首 Token', duration: '执行耗时', contextRead: '上下文读取', contextCleanup: '上下文整理', cleanupCount: '次',
    agentPerformance: 'Agent 与模型性能', toolAnalysis: 'A2A-T 消息', errorDiagnosis: '错误诊断', callChain: '调用链', rawLog: '原始日志',
    callChainHint: '按时间顺序记录本次运行中的关键步骤', executionRecord: '执行记录', call: 'A2A-T 调用', success: '成功', records: '条记录', tokenBreakdown: 'Token 构成', noToolCalls: '本次运行未记录 A2A-T 消息', noErrors: '本次运行未发现错误', errorEvents: '错误事件', errorHint: '运行过程完整结束，未记录错误事件', rawHint: '查看本次运行的完整事件记录', emptyChain: '当前运行暂无调用记录', emptyRaw: '暂无原始日志', eventsRecorded: '条事件',
  },
  EN: {
    kicker: 'RUN OBSERVABILITY', title: 'Run details', fallbackTitle: 'Network diagnosis run', close: 'Close', runId: 'Run ID', status: 'Status', completed: 'Completed', processSwitcher: 'Run process', processOne: 'Process 1', processTwo: 'Process 2',
    totalTokens: 'Total tokens', tokenRate: 'Global token rate', interaction: 'Interactions', context: 'Context usage', tokens: 'tokens', messages: 'messages', messageCount: 'messages', a2aRounds: 'A2A-T rounds', toolCalls: 'messages', input: 'Input', output: 'Output', firstResponse: 'First token', duration: 'Duration', contextRead: 'Context read', contextCleanup: 'Context cleanup', cleanupCount: 'times',
    agentPerformance: 'Agent & model performance', toolAnalysis: 'A2A-T messages', errorDiagnosis: 'Error diagnosis', callChain: 'Call chain', rawLog: 'Raw log',
    callChainHint: 'Key steps recorded in chronological order', executionRecord: 'Execution record', call: 'A2A-T call', success: 'Success', records: 'records', tokenBreakdown: 'Token breakdown', noToolCalls: 'No A2A-T messages were recorded in this run', noErrors: 'No errors found in this run', errorEvents: 'error events', errorHint: 'The run completed without recorded error events', rawHint: 'Inspect the complete event record for this run', emptyChain: 'No call records for this run', emptyRaw: 'No raw log', eventsRecorded: 'events',
  },
}

function inferTokenUsageCategory(input = '') {
  const normalized = input.toLowerCase()
  if (/账单|计费|收费|billing|charge/.test(normalized)) return 'billing'
  if (/pon|olt|光模块|optical/.test(normalized)) return 'optical'
  if (/离线|网元|单板|offline|board/.test(normalized)) return 'device'
  return 'business'
}

const englishData = {
  agents: {
    '账单明细核对': 'Bill detail review', '费用金额核对': 'Charge amount review', '计费周期核对': 'Billing-cycle review', '订购关系核对': 'Subscription review', '费用构成核对': 'Charge composition review', '优惠记录核对': 'Discount record review', '历史账单核对': 'Billing history review', '账单情况核对': 'Billing overview review', '优惠规则核对': 'Discount rule review', '处理结论': 'Conclusion', '事件分析': 'Event analysis', '业务分析': 'Service analysis', '承载分析': 'Transport analysis', '告警分析': 'Alarm analysis', '历史分析': 'History analysis', '范围复核': 'Scope review', '诊断结论': 'Diagnosis conclusion', '故障范围梳理': 'Fault scope analysis', '故障类型初判': 'Initial fault classification', '运行情况核对': 'Operational-state review', '故障类型确认': 'Fault classification confirmation', '信息缺口确认': 'Information-gap confirmation', '故障识别（Awareness）': 'Fault identification (Awareness)', '问题定界（Analysis）': 'Problem demarcation (Analysis)', '影响性分析（Analysis）': 'Impact analysis (Analysis)', '问题定位（Analysis）': 'Problem localization (Analysis)', '定位信息缺口（Analysis）': 'Localization information gap (Analysis)', '方案生成并决策（Decision）': 'Solution generation and decision (Decision)', '设备核对': 'Device review', '告警核对': 'Alarm review', '历史核对': 'History review',
  },
  messages: {
    '读取本期账单明细、订购记录和历史账单。': 'Read current bill details, subscription records, and billing history.',
    '发现两笔金额相同的费用，需要继续确认是否属于不同计费项目。': 'Two charges have the same amount. Verify whether they belong to different billing items.',
    '两笔费用对应同一计费周期，不属于跨账期补收。': 'Both charges belong to the same billing cycle; this is not a cross-cycle adjustment.',
    '客户名下只有一条有效订购，账期内也没有业务变更，新增业务和跨账期补收可以排除。': 'The customer has one active subscription and no service changes during the billing cycle. New services and cross-cycle adjustments are excluded.',
    '安装费、月租费和调整项均未产生第二笔应收费用。': 'Installation, monthly rental, and adjustment items did not create a second receivable charge.',
    '本账期应执行的优惠规则没有生效，重复金额与应享优惠金额一致。': 'The discount rule for this billing cycle was not applied; the duplicate amount equals the eligible discount.',
    '前几个账期费用正常，未发现同类重复收费记录。': 'Previous billing cycles were normal, with no similar duplicate-charge records.',
    '账单、订购和优惠记录已经形成完整依据，可直接确认计费原因，无需请求 OMC；后续生成计费冲正单。': 'Bill, subscription, and discount records provide sufficient evidence to confirm the cause without querying OMC. Create a billing reversal order next.',
    '同一账期出现两笔金额相同的费用，先从订购关系、计费周期和优惠执行情况入手核对。': 'Two identical charges appeared in one billing cycle. Start by checking subscription, billing cycle, and discount execution.',
    '优惠规则未执行，重复金额又与应享优惠金额一致，问题落在计费规则执行环节。': 'The discount rule was not applied and the duplicate amount matches the eligible discount, locating the issue in billing-rule execution.',
    '读取设备离线事件、网元告警和最近一次状态记录。': 'Read the device-offline event, network-element alarms, and latest status record.',
    '网元无法连通，暂时不能确认是管理通道、单板还是供电问题。': 'The network element is unreachable; management channel, board, and power issues remain possible.',
    '请求核查网元在线状态和当前告警。': 'Request the network element’s online state and current alarms.',
    '网元仍处于离线状态，返回多条设备告警。': 'The network element remains offline and multiple device alarms were returned.',
    '告警同时涉及主控板和电源模块，故障位置还不能确定。': 'Alarms involve both the control board and power module; the fault location is not yet confirmed.',
    '请求补充主控板和电源模块状态。': 'Request additional control-board and power-module status.',
    '电源模块工作正常，主控板状态异常。': 'The power module is normal; the control-board state is abnormal.',
    '历史记录中出现过短时管理通道中断，仍需排除重复故障。': 'Historical records show a brief management-channel interruption; recurring faults still need to be excluded.',
    '请求确认主控板复位记录和故障原因。': 'Request the control-board reset record and fault cause.',
    '主控板未成功复位，确认本次离线由单板故障引起。': 'The control board did not reset successfully. This outage is confirmed as a board fault.',
    '最终确认原因为单板故障。': 'The final confirmed cause is a board fault.',
    '读取故障事件、性能观测和历史记录。': 'Read fault events, performance observations, and history.',
    '业务影响范围与告警对象不一致，问题范围还不能确定。': 'The service impact scope does not match alarmed objects, so the fault scope is still undetermined.',
    'PON口丢包持续超阈，受影响业务范围还不能确定。': 'PON-port packet loss remains above the threshold; the affected service scope is still undetermined.',
    '读取故障事件、性能观测和历史记录。候选范围未收敛。': 'Read fault events, performance observations, and history. The candidate scope is not yet converged.',
    '业务影响范围与告警对象不一致。': 'The service impact scope does not match the alarmed objects.',
    '请求核查候选链路运行状态。': 'Request verification of candidate-link operational states.',
    '返回链路状态，存在两个异常候选。': 'Link states returned; two abnormal candidates remain.',
    '逐段核对承载路径，部分状态与劣化时间窗一致。': 'Validate the transport path hop by hop; several states align with the degradation window.',
    '设备告警和端口计数器存在多个关联对象。': 'Device alarms and port counters involve multiple related objects.',
    '请求补充端口和光模块状态。': 'Request additional port and optical-module states.',
    '返回端口和光模块状态，光模块异常待复核。': 'Port and optical-module states returned; the optical-module anomaly requires review.',
    '同类事件修复记录与当前资源拓扑不一致。': 'Similar incident repair records do not match the current resource topology.',
    '短时波动已排除，保留链路和尾纤两个候选。': 'Transient fluctuation is excluded; link and fiber-jumper remain as candidates.',
    '请求核查尾纤光功率和故障原因。': 'Request fiber-jumper optical power and fault-cause verification.',
    '返回尾纤光功率异常，故障原因已确认。': 'Abnormal fiber-jumper optical power returned; the fault cause is confirmed.',
    '短时波动已排除，保留端口和光模块两个可能原因。': 'Transient fluctuations are excluded; the port and optical module remain as possible causes.',
    '请求核查光模块收发光功率和故障原因。': 'Request optical-module transmit/receive power and fault-cause verification.',
    '返回光模块接收光功率异常，故障原因已确认。': 'Abnormal optical-module receive power returned; the fault cause is confirmed.',
    '逐段核对承载路径，部分状态与业务劣化时段一致。': 'Validate the transport path hop by hop; several states align with the service-degradation period.',
    '端口误码时段与丢包时段一致，继续核对光层状态。': 'The port-error period aligns with packet loss; continue checking optical-layer state.',
    '端口状态正常，光模块接收光功率持续偏低。': 'The port is operational, while optical-module receive power remains low.',
    '设备告警和端口计数器涉及多个关联对象。': 'Device alarms and port counters involve multiple related objects.',
    '短时波动已排除，保留链路和尾纤两个可能原因。': 'Transient fluctuations are excluded; link and fiber-jumper remain as possible causes.',
    '已结合 OMC 返回的信息确认故障原因，诊断完成。': 'The fault cause is confirmed with OMC data; diagnosis is complete.',
    '输入显示网元离线，在 IP网 / 故障管理下识别为已发生故障，并沿“故障识别 → 问题定界定位”关系进入分析，先核对可能导致离线的故障类型。': 'The input indicates a network element is offline. It is identified as an active fault under IP network / Fault management, then follows Fault identification → Problem demarcation and localization to analyze possible outage causes.',
    '网元无法连通并伴随设备告警，设备、连接、环境、协议和跨专业方向需要优先排查。': 'The network element is unreachable with device alarms. Prioritize device, connection, environment, protocol, and cross-domain checks.',
    '离线时刻与设备和连接告警一致，范围进一步集中到设备、连接和业务方向。': 'The outage time aligns with device and connection alarms, narrowing the scope to device, connection, and service paths.',
    '设备告警出现时间与网元离线时间吻合，问题归到设备类故障。': 'Device-alarm timing matches the outage; the issue is classified as a device fault.',
    '故障类型已经明确，但网元运行状态保存在厂商域，现有信息不足以继续定位，需要查询 OMC。': 'The fault type is clear, but vendor-domain operational state is required to continue diagnosis. Query OMC.',
    'OMC 返回主控板异常、供电正常，设备离线最终定位为单板故障。': 'OMC reports an abnormal control board and normal power supply. The outage is diagnosed as a board fault.',
    'OMC 返回主控板异常、供电正常，设备离线最终定位为单板故障；依据定位结果生成现场更换主控板方案，并完成实施影响评估。': 'OMC reports an abnormal control board and normal power supply, locating the outage to a board fault. Based on the localization result, a control-board replacement plan is generated and its implementation impact is evaluated.',
    '专线可用率连续下降并伴随持续丢包，在 IP网 / 故障管理下识别为已发生故障，并沿“故障识别 → 问题定界定位”关系进入分析，先核对可能影响专线质量的故障类型。': 'Dedicated-line availability is declining with persistent packet loss. It is identified as an active fault under IP network / Fault management, then follows Fault identification → Problem demarcation and localization to analyze possible causes.',
    '业务可用率与丢包在同一时段劣化，设备、连接、业务、协议和跨专业方向需要优先排查。': 'Service availability and packet loss degrade in the same period. Prioritize device, connection, service, protocol, and cross-domain checks.',
    '承载告警与劣化时段吻合，同时未发现设备离线、时钟或环境告警，范围进一步集中到业务、连接和跨专业方向。': 'Transport alarms align with degradation; no device-offline, clock, or environment alarms were found, narrowing the scope to service, connection, and cross-domain paths.',
    'SLA 劣化时段与承载异常时间一致，问题归到业务类故障。': 'The SLA degradation period aligns with the transport anomaly, classifying the issue as a service fault.',
    '故障类型已经明确，但边界承载对象状态保存在厂商域，现有信息不足以继续定位，需要查询 OMC。': 'The fault type is clear, but vendor-domain boundary transport state is required to continue diagnosis. Query OMC.',
    'OMC 返回的尾纤异常与业务劣化时段吻合，光模块状态正常，最终定位为尾纤故障。': 'The OMC-reported fiber-jumper anomaly aligns with service degradation and the optical module is normal. The fault is diagnosed as a fiber-jumper fault.',
    'OMC 返回的尾纤异常与业务劣化时段吻合，光模块状态正常，最终定位为尾纤故障；依据定位结果生成更换尾纤方案，并完成实施影响评估。': 'The OMC-reported fiber-jumper anomaly aligns with service degradation and the optical module is normal, locating the fault to the fiber jumper. A fiber-jumper replacement plan is generated and its implementation impact is evaluated.',
    'PON口丢包持续超阈，在 IP网 / 故障管理下识别为已发生故障，并沿“故障识别 → 问题定界定位”关系进入分析，先核对连接与光层故障类型。': 'PON-port packet loss remains above the threshold. It is identified as an active fault under IP network / Fault management, then follows Fault identification → Problem demarcation and localization to analyze connection and optical-layer causes.',
    '端口误码与丢包发生在同一时段，连接、设备、业务和协议方向需要优先排查。': 'Port errors and packet loss occur in the same period. Prioritize connection, device, service, and protocol checks.',
    '端口运行状态正常但接收光功率持续偏低，范围集中到连接和业务方向。': 'The port is operational, but receive power remains low, narrowing the scope to connection and affected-service paths.',
    '端口误码与丢包发生在同一时段，连接、设备和协议方向需要优先排查。': 'Port errors and packet loss occur in the same period. Prioritize connection, device, and protocol checks.',
    '端口运行状态正常但接收光功率持续偏低，范围集中到链路和光模块。': 'The port is operational, but receive power remains low, narrowing the scope to the link and optical module.',
    '丢包时段与接收光功率异常吻合，问题归到连接类故障。': 'The packet-loss period aligns with abnormal receive power, classifying the issue as a connection fault.',
    '故障类型已经明确，但光模块收发光功率保存在厂商域，现有信息不足以继续定位，需要查询 OMC。': 'The fault type is clear, but optical-module transmit/receive power is held in the vendor domain. Query OMC to continue diagnosis.',
    'OMC 返回光模块接收光功率异常、端口状态正常，最终定位为光模块故障。': 'OMC reports abnormal optical-module receive power and a normal port state. The fault is diagnosed as an optical-module fault.',
    'OMC 返回光模块接收光功率异常、端口状态正常，最终定位为光模块故障；依据定位结果生成更换光模块方案，并完成实施影响评估。': 'OMC reports abnormal optical-module receive power and a normal port state, locating the fault to the optical module. An optical-module replacement plan is generated and its implementation impact is evaluated.',
  },
}

const faultCauseEN = { '尾纤故障': 'fiber-jumper fault', '单板故障': 'board fault', '光模块故障': 'optical-module fault' }
function localizeFaultCause(value) { return faultCauseEN[value] ?? value }

function localizeExecutionText(text) {
  const translated = englishData.messages[text]
  if (translated) return translated
  if (text.startsWith('对象=')) {
    const fields = Object.fromEntries([...text.matchAll(/([A-Za-z]+)=([^；。]+)/g)].map(([, key, value]) => [key, value]))
    if (fields.operState) return `Object ${text.match(/对象=([^；]+)/)?.[1] ?? 'network element'} returned: operational state ${fields.operState}; fault cause ${localizeFaultCause(fields.faultCause ?? 'unknown')}; confidence ${fields.confidence ?? 'unknown'}.`
    const requested = text.match(/字段=([^。]+)/)?.[1]?.replaceAll('、', ', ') ?? 'requested fields'
    return `Requesting ${requested} for object ${text.match(/对象=([^；]+)/)?.[1] ?? 'network element'}.`
  }
  if (text.startsWith('请求补充')) return 'Request additional operational state and fault-cause information for the boundary object.'
  if (text.startsWith('状态=异常；故障原因=')) return `Returned status: abnormal; fault cause: ${localizeFaultCause(text.match(/故障原因=([^。]+)/)?.[1] ?? 'confirmed')}.`
  if (text.startsWith('最终确认原因为')) return `The final confirmed cause is ${localizeFaultCause(text.match(/最终确认原因为(.+)。/)?.[1] ?? 'confirmed')}.`
  if (text.startsWith('OMC 返回主控板异常')) return 'OMC reports an abnormal control board and normal power supply. The outage is diagnosed as a board fault. Arrange on-site handling, monitor service SQI, and close the work order after recovery.'
  if (text.startsWith('OMC 返回光模块接收光功率异常')) return 'OMC reports abnormal optical-module receive power and a normal port state. The fault is diagnosed as an optical-module fault. Arrange optical-module replacement, monitor service SQI, and close the work order after recovery.'
  if (text.startsWith('OMC 返回的尾纤异常')) return 'The OMC-reported fiber-jumper anomaly aligns with the service-degradation period and the optical module is normal. The fault is diagnosed as a fiber-jumper fault. Arrange on-site handling, monitor service SQI, and close the work order after recovery.'
  return text
}

function localizeMessage(message, language) {
  if (language !== 'EN') return message
  return {
    ...message,
    agent: englishData.agents[message.agent] ?? message.agent,
    text: message.textEN ?? localizeExecutionText(message.text),
    a2aTaskMarkdown: message.a2aTaskMarkdown ? '## Task Type\nVendor status check\n\n## Task Description\nRequest the vendor-domain status required for this diagnostic step.\n\n## Expected Output\nOperational state, fault cause, and confidence.' : undefined,
  }
}
function timeLabel(value) {
  if (!value) return new Date().toLocaleTimeString('zh-CN', { hour12: false })
  return new Date(value).toLocaleTimeString('zh-CN', { hour12: false })
}

function messageType(agent, stage, role) {
  if (role === 'response' || role === 'a2a-response') return 'response'
  if (agent === 'A2A-T' || role === 'a2a-request') return 'a2a'
  return 'system'
}
function cleanMessageAgent(value = '') {
  return value.replace(/\s*[（(](?:Awareness|Analysis|Decision|Execution)[）)]/gi, '').trim()
}
function mockA2ATaskMarkdown(taskType, taskTarget, taskObject, expectedFields) {
  return [
    '## 任务类型(Task Type)', taskType,
    '## 任务描述(Task Description)', 'OSS 请求 OMC 核查指定网络对象状态。',
    '## 任务目标(Task Target)', taskTarget,
    '## 任务对象(Task Object)', taskObject,
    '## 任务上下文(Task Context)', '1. 依据当前问题现象限定查询范围。', '2. 仅查询本次分析所需状态。',
    '## 预期输出(Expected Output)', ...expectedFields.map((field, index) => (index + 1) + '. 返回' + field + '。'),
  ].join('\n')
}
function assignHistoricalTimes(messages, startedTime) {
  const [hour, minute] = startedTime.split(':').map(Number)
  const startedMinutes = hour * 60 + minute
  const indexes = {}
  return messages.map((message) => {
    const phase = message.phase || 'baseline'
    const index = indexes[phase] || 0
    indexes[phase] = index + 1
    const value = (startedMinutes + index) % 1440
    return { ...message, time: `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}` }
  })
}
function mockMessagesForRecord(record) {
  if (record.category === 'billing') {
    const baseline = [
      { id: record.id + '-baseline-1', agent: '账单明细核对', type: 'system', time: record.time, text: '读取本期账单明细、订购记录和历史账单。' },
      { id: record.id + '-baseline-2', agent: '费用金额核对', type: 'system', time: record.time, text: '发现两笔金额相同的费用，需要继续确认是否属于不同计费项目。' },
      { id: record.id + '-baseline-3', agent: '计费周期核对', type: 'system', time: record.time, text: '两笔费用对应同一计费周期，不属于跨账期补收。' },
      { id: record.id + '-baseline-4', agent: '订购关系核对', type: 'system', time: record.time, text: '客户名下只有一条有效订购，账期内也没有业务变更，新增业务和跨账期补收可以排除。' },
      { id: record.id + '-baseline-5', agent: '费用构成核对', type: 'system', time: record.time, text: '安装费、月租费和调整项均未产生第二笔应收费用。' },
      { id: record.id + '-baseline-6', agent: '优惠记录核对', type: 'system', time: record.time, text: '本账期应执行的优惠规则没有生效，重复金额与应享优惠金额一致。' },
      { id: record.id + '-baseline-7', agent: '历史账单核对', type: 'system', time: record.time, text: '前几个账期费用正常，未发现同类重复收费记录。' },
      { id: record.id + '-baseline-8', agent: '处理结论', type: 'system', time: record.time, text: '账单、订购和优惠记录已经形成完整依据，可直接确认计费原因，无需请求 OMC；后续生成计费冲正单。' },
    ].map((message) => ({ ...message, phase: 'baseline' }))
    const assisted = [
      { id: record.id + '-1', agent: '账单情况核对', type: 'system', time: record.time, text: '同一账期出现两笔金额相同的费用，先从订购关系、计费周期和优惠执行情况入手核对。' },
      { id: record.id + '-2', agent: '订购关系核对', type: 'system', time: record.time, text: '客户名下只有一条有效订购，账期内也没有业务变更，新增业务和跨账期补收可以排除。' },
      { id: record.id + '-3', agent: '优惠规则核对', type: 'system', time: record.time, text: '优惠规则未执行，重复金额又与应享优惠金额一致，问题落在计费规则执行环节。' },
      { id: record.id + '-4', agent: '处理结论', type: 'system', time: record.time, text: '账单、订购和优惠记录已经形成完整依据，可直接确认计费原因，无需请求 OMC；后续生成计费冲正单。' },
    ].map((message) => ({ ...message, phase: 'assisted' }))
    return assignHistoricalTimes([...baseline, ...assisted], record.time).map((message) => ({ ...message, textEN: localizeExecutionText(message.text) }))
  }

  const isDevice = record.category === 'device'
  const isOptical = record.category === 'optical'
  const requestObject = isDevice ? '边界网元' : (isOptical ? '边界端口' : '边界链路')
  const baselineMessages = (isDevice ? [
    { id: record.id + '-baseline-1', agent: '事件分析', type: 'system', time: record.time, text: '读取设备离线事件、网元告警和最近一次状态记录。' },
    { id: record.id + '-baseline-2', agent: '设备核对', type: 'system', time: record.time, text: '网元无法连通，暂时不能确认是管理通道、单板还是供电问题。' },
    { id: record.id + '-baseline-3', agent: 'A2A-T', type: 'a2a', time: record.time, text: '请求核查网元在线状态和当前告警。', a2aTaskMarkdown: mockA2ATaskMarkdown('网元状态核查', '确认离线网元的在线状态和当前告警', record.resourceId, ['在线状态', '当前告警']) },
    { id: record.id + '-baseline-4', agent: 'A2A-T', type: 'response', time: record.time, text: '网元仍处于离线状态，返回多条设备告警。' },
    { id: record.id + '-baseline-5', agent: '告警核对', type: 'system', time: record.time, text: '告警同时涉及主控板和电源模块，故障位置还不能确定。' },
    { id: record.id + '-baseline-6', agent: 'A2A-T', type: 'a2a', time: record.time, text: '请求补充主控板和电源模块状态。', a2aTaskMarkdown: mockA2ATaskMarkdown('部件状态核查', '补充主控板和电源模块状态', record.resourceId, ['主控板状态', '电源模块状态']) },
    { id: record.id + '-baseline-7', agent: 'A2A-T', type: 'response', time: record.time, text: '电源模块工作正常，主控板状态异常。' },
    { id: record.id + '-baseline-8', agent: '历史核对', type: 'system', time: record.time, text: '历史记录中出现过短时管理通道中断，仍需排除重复故障。' },
    { id: record.id + '-baseline-9', agent: 'A2A-T', type: 'a2a', time: record.time, text: '请求确认主控板复位记录和故障原因。', a2aTaskMarkdown: mockA2ATaskMarkdown('主控板故障核查', '确认主控板复位记录和本次故障原因', record.resourceId, ['复位记录', '故障原因']) },
    { id: record.id + '-baseline-10', agent: 'A2A-T', type: 'response', time: record.time, text: '主控板未成功复位，确认本次离线由单板故障引起。' },
    { id: record.id + '-baseline-11', agent: '诊断结论', type: 'system', time: record.time, text: '最终确认原因为单板故障。' },
  ] : isOptical ? [
    { id: record.id + '-baseline-1', agent: '事件分析', type: 'system', time: record.time, text: '读取故障事件、性能观测和历史记录。' },
    { id: record.id + '-baseline-2', agent: '业务分析', type: 'system', time: record.time, text: 'PON口丢包持续超阈，受影响业务范围还不能确定。' },
    { id: record.id + '-baseline-3', agent: 'A2A-T', type: 'a2a', time: record.time, text: '请求核查候选链路运行状态。', a2aTaskMarkdown: mockA2ATaskMarkdown('PON链路状态核查', '核查PON端口与候选链路的运行状态', record.resourceId, ['端口状态', '链路状态']) },
    { id: record.id + '-baseline-4', agent: 'A2A-T', type: 'response', time: record.time, text: '返回链路状态，存在两个异常候选。' },
    { id: record.id + '-baseline-5', agent: '承载分析', type: 'system', time: record.time, text: '端口误码时段与丢包时段一致，继续核对光层状态。' },
    { id: record.id + '-baseline-6', agent: '告警分析', type: 'system', time: record.time, text: '端口状态正常，光模块接收光功率持续偏低。' },
    { id: record.id + '-baseline-7', agent: '历史分析', type: 'system', time: record.time, text: '同类事件修复记录与当前资源拓扑不一致。' },
    { id: record.id + '-baseline-8', agent: '范围复核', type: 'system', time: record.time, text: '短时波动已排除，保留端口和光模块两个可能原因。' },
    { id: record.id + '-baseline-9', agent: 'A2A-T', type: 'a2a', time: record.time, text: '请求核查光模块收发光功率和故障原因。', a2aTaskMarkdown: mockA2ATaskMarkdown('光模块状态核查', '核查光模块收发光功率并确认故障原因', record.resourceId, ['发送光功率', '接收光功率', '故障原因']) },
    { id: record.id + '-baseline-10', agent: 'A2A-T', type: 'response', time: record.time, text: '返回光模块接收光功率异常，故障原因已确认。' },
    { id: record.id + '-baseline-11', agent: '诊断结论', type: 'system', time: record.time, text: '最终确认原因为光模块故障。' },
  ] : [
    { id: record.id + '-baseline-1', agent: '事件分析', type: 'system', time: record.time, text: '读取故障事件、性能观测和历史记录。' },
    { id: record.id + '-baseline-2', agent: '业务分析', type: 'system', time: record.time, text: '业务影响范围与告警对象不一致，问题范围还不能确定。' },
    { id: record.id + '-baseline-3', agent: 'A2A-T', type: 'a2a', time: record.time, text: '请求核查候选链路运行状态。', a2aTaskMarkdown: mockA2ATaskMarkdown('候选链路状态核查', '核查候选链路的运行状态与异常范围', '候选链路集合', ['运行状态', '异常对象']) },
    { id: record.id + '-baseline-4', agent: 'A2A-T', type: 'response', time: record.time, text: '返回链路状态，存在两个异常候选。' },
    { id: record.id + '-baseline-5', agent: '承载分析', type: 'system', time: record.time, text: '逐段核对承载路径，部分状态与业务劣化时段一致。' },
    { id: record.id + '-baseline-6', agent: '告警分析', type: 'system', time: record.time, text: '设备告警和端口计数器涉及多个关联对象。' },
    { id: record.id + '-baseline-7', agent: 'A2A-T', type: 'a2a', time: record.time, text: '请求补充端口和光模块状态。', a2aTaskMarkdown: mockA2ATaskMarkdown('端口与光模块状态核查', '补充候选端口及光模块状态', '候选端口与光模块', ['端口状态', '光模块状态']) },
    { id: record.id + '-baseline-8', agent: 'A2A-T', type: 'response', time: record.time, text: '返回端口和光模块状态，光模块异常待复核。' },
    { id: record.id + '-baseline-9', agent: '历史分析', type: 'system', time: record.time, text: '同类事件修复记录与当前资源拓扑不一致。' },
    { id: record.id + '-baseline-10', agent: '范围复核', type: 'system', time: record.time, text: '短时波动已排除，保留链路和尾纤两个可能原因。' },
    { id: record.id + '-baseline-11', agent: 'A2A-T', type: 'a2a', time: record.time, text: '请求核查尾纤光功率和故障原因。', a2aTaskMarkdown: mockA2ATaskMarkdown('尾纤状态核查', '核查尾纤光功率并确认故障原因', '候选尾纤', ['光功率', '故障原因']) },
    { id: record.id + '-baseline-12', agent: 'A2A-T', type: 'response', time: record.time, text: '返回尾纤光功率异常，故障原因已确认。' },
    { id: record.id + '-baseline-13', agent: '诊断结论', type: 'system', time: record.time, text: '最终确认原因为' + record.meta.replace('已定位 · ', '').replace('已完成 · ', '') + '。' },
  ]).map((message) => ({ ...message, phase: 'baseline' }))
  const recordInference = isDevice ? {
    full: '输入显示网元离线，在 IP网 / 故障管理下识别为已发生故障，并沿“故障识别 → 问题定界定位”关系进入分析，先核对可能导致离线的故障类型。',
    rule: '网元无法连通并伴随设备告警，设备、连接、环境、协议和跨专业方向需要优先排查。',
    evidence: '离线时刻与设备和连接告警一致，范围进一步集中到设备、连接和业务方向。',
    final: '设备告警出现时间与网元离线时间吻合，问题归到设备类故障。',
    gate: '故障类型已经明确，但网元运行状态保存在厂商域，现有信息不足以继续定位，需要查询 OMC。',
    closure: 'OMC 返回主控板异常、供电正常，设备离线最终定位为单板故障；依据定位结果生成现场更换主控板方案，并完成实施影响评估。',
  } : isOptical ? {
    full: 'PON口丢包持续超阈，在 IP网 / 故障管理下识别为已发生故障，并沿“故障识别 → 问题定界定位”关系进入分析，先核对连接与光层故障类型。',
    rule: '端口误码与丢包发生在同一时段，连接、设备、业务和协议方向需要优先排查。',
    evidence: '端口运行状态正常但接收光功率持续偏低，范围集中到连接和业务方向。',
    final: '丢包时段与接收光功率异常吻合，问题归到连接类故障。',
    gate: '故障类型已经明确，但光模块收发光功率保存在厂商域，现有信息不足以继续定位，需要查询 OMC。',
    closure: 'OMC 返回光模块接收光功率异常、端口状态正常，最终定位为光模块故障；依据定位结果生成更换光模块方案，并完成实施影响评估。',
  } : {
    full: '专线可用率连续下降并伴随持续丢包，在 IP网 / 故障管理下识别为已发生故障，并沿“故障识别 → 问题定界定位”关系进入分析，先核对可能影响专线质量的故障类型。',
    rule: '业务可用率与丢包在同一时段劣化，设备、连接、业务、协议和跨专业方向需要优先排查。',
    evidence: '承载告警与劣化时段吻合，同时未发现设备离线、时钟或环境告警，范围进一步集中到业务、连接和跨专业方向。',
    final: 'SLA 劣化时段与承载异常时间一致，问题归到业务类故障。',
    gate: '故障类型已经明确，但边界承载对象状态保存在厂商域，现有信息不足以继续定位，需要查询 OMC。',
    closure: 'OMC 返回的尾纤异常与业务劣化时段吻合，光模块状态正常，最终定位为尾纤故障；依据定位结果生成更换尾纤方案，并完成实施影响评估。',
  }
  const assistedMessages = [
    { id: record.id + '-1', agent: '故障识别（Awareness）', type: 'system', time: record.time, text: recordInference.full },
    { id: record.id + '-2', agent: '问题定界（Analysis）', type: 'system', time: record.time, text: recordInference.rule },
    { id: record.id + '-3', agent: '影响性分析（Analysis）', type: 'system', time: record.time, text: recordInference.evidence },
    { id: record.id + '-4', agent: '问题定位（Analysis）', type: 'system', time: record.time, text: recordInference.final },
    { id: record.id + '-5', agent: '定位信息缺口（Analysis）', type: 'system', time: record.time, text: recordInference.gate },
    { id: record.id + '-6', agent: 'A2A-T', type: 'a2a', time: record.time, text: '请求补充' + requestObject + '的运行状态和故障原因。', a2aTaskMarkdown: mockA2ATaskMarkdown(isDevice ? '网元状态补充' : (isOptical ? '光模块状态补充' : '边界链路状态补充'), '补充后续诊断所需的对象状态', record.resourceId, ['运行状态', '故障原因', '置信度']) },
    { id: record.id + '-7', agent: 'A2A-T', type: 'response', time: record.time, text: '状态=异常；故障原因=' + record.meta.replace('已定位 · ', '').replace('已完成 · ', '') + '。' },
    { id: record.id + '-8', agent: '方案生成并决策（Decision）', type: 'system', time: record.time, text: recordInference.closure },
  ].map((message) => ({ ...message, phase: 'assisted' }))
  return assignHistoricalTimes([...baselineMessages, ...assistedMessages], record.time).map((message) => ({ ...message, textEN: localizeExecutionText(message.text) }))
}
function focusForRecord(record) {
  const thirdLayerNodes = ['CatDevice', 'CatConnection', 'CatService', 'CatClock', 'CatEnvironment', 'CatProtocol', 'CatCrossDomain']
  const thirdLayerLinks = [
    '环境变化影响设备运行',
    '设备状态影响连接',
    '协议状态影响连接',
    '时钟状态影响业务',
    '连接质量影响业务',
    '外部条件影响运行环境',
    '跨专业状态影响连接',
    '跨专业信息关联业务',
  ]

  if (record.category === 'billing') {
    return {
      actor: '处理结论',
      label: '现有信息足以在当前层完成判断',
      nodes: ['CatService', 'CatCrossDomain'],
      links: ['跨专业信息关联业务'],
      contextNodes: thirdLayerNodes,
      contextLinks: thirdLayerLinks,
      zoomScale: 0.92,
    }
  }

  if (record.category === 'optical') {
    return connectFaultOperationConclusion({
      actor: '诊断结论',
      label: '光模块接收光功率异常与PON口丢包吻合',
      nodes: ['CatConnection', 'CatService', 'LinkFault', 'OpticalModule'],
      links: ['连接质量影响业务', '连接类→链路故障', '链路→光模块根因'],
      contextNodes: [...thirdLayerNodes, 'LinkFault', 'OpticalModule'],
      contextLinks: [...thirdLayerLinks, '连接类→链路故障', '链路→光模块根因'],
      zoomScale: 0.92,
    })
  }

  if (record.category === 'device') {
    return connectFaultOperationConclusion({
      actor: '诊断结论',
      label: '设备至业务的影响路径与单板异常对应',
      nodes: ['CatDevice', 'CatConnection', 'CatService', 'DeviceOffline', 'BoardFault'],
      links: ['设备状态影响连接', '连接质量影响业务', '设备类→设备离线', '离线→单板根因'],
      contextNodes: [...thirdLayerNodes, 'DeviceOffline', 'BoardFault', 'PowerFault'],
      contextLinks: [...thirdLayerLinks, '设备类→设备离线', '离线→单板根因', '离线→供电根因'],
      zoomScale: 0.92,
    })
  }

  return connectFaultOperationConclusion({
    actor: '诊断结论',
    label: '跨专业至业务的影响路径与尾纤异常对应',
    nodes: ['CatCrossDomain', 'CatConnection', 'CatService', 'TunnelFault', 'FiberFault'],
    links: ['跨专业状态影响连接', '连接质量影响业务', '业务类→隧道故障', '隧道→光纤根因'],
    contextNodes: [...thirdLayerNodes, 'TunnelFault', 'FiberFault', 'OpticalModule'],
    contextLinks: [...thirdLayerLinks, '业务类→隧道故障', '隧道→光纤根因', '隧道→光模块根因'],
    zoomScale: 0.92,
  })
}
function Message({ message, onTypingComplete, copy, language }) {
  const localizedMessage = localizeMessage(message, message.displayLanguage ?? language)
  message = localizedMessage
  const [visibleText, setVisibleText] = useState('')
  const [visibleTaskMarkdown, setVisibleTaskMarkdown] = useState('')
  const [typing, setTyping] = useState(Boolean(message.animate))
  const isA2AT = message.type === 'a2a' || message.type === 'response'
  const route = message.type === 'response' ? 'OMC → OSS' : 'OSS → OMC'
  const displayAgent = cleanMessageAgent(message.agent)

  useEffect(() => {
    if (!message.animate) {
      setVisibleText(message.text)
      setVisibleTaskMarkdown(message.a2aTaskMarkdown || '')
      setTyping(false)
      return undefined
    }

    let textIndex = 0
    let taskIndex = 0
    let timer
    const taskMarkdown = message.a2aTaskMarkdown || ''
    setVisibleText('')
    setVisibleTaskMarkdown('')
    setTyping(true)

    const finishTyping = () => {
      setTyping(false)
      onTypingComplete?.()
    }
    const typeTaskMarkdown = () => {
      if (taskIndex >= taskMarkdown.length) {
        finishTyping()
        return
      }
      const chunkSize = Math.min(12, 7 + (taskIndex % 5))
      const nextIndex = Math.min(taskMarkdown.length, taskIndex + chunkSize)
      const chunk = taskMarkdown.slice(taskIndex, nextIndex)
      taskIndex = nextIndex
      setVisibleTaskMarkdown(taskMarkdown.slice(0, taskIndex))
      const lastCharacter = chunk.at(-1)
      const pause = /[。！？；：.!?;]/.test(lastCharacter || '') ? 220 : /[，、,]/.test(lastCharacter || '') ? 110 : 36 + (taskIndex % 3) * 14
      timer = window.setTimeout(typeTaskMarkdown, pause)
    }
    const typeNextChunk = () => {
      if (textIndex >= message.text.length) {
        if (taskMarkdown) {
          timer = window.setTimeout(typeTaskMarkdown, 160)
        } else {
          finishTyping()
        }
        return
      }
      const chunkSize = textIndex === 0 ? 2 : Math.min(5, 2 + (textIndex % 4 === 0 ? 1 : 0) + (textIndex % 7 === 0 ? 1 : 0))
      const nextIndex = Math.min(message.text.length, textIndex + chunkSize)
      const chunk = message.text.slice(textIndex, nextIndex)
      textIndex = nextIndex
      setVisibleText(message.text.slice(0, textIndex))
      const lastCharacter = chunk.at(-1)
      const punctuationPause = /[。！？；：.!?;]/.test(lastCharacter || '') ? 300 : /[，、,]/.test(lastCharacter || '') ? 150 : 42 + (textIndex % 3) * 16
      timer = window.setTimeout(typeNextChunk, punctuationPause)
    }

    timer = window.setTimeout(typeNextChunk, 120)
    return () => window.clearTimeout(timer)
  }, [message.a2aTaskMarkdown, message.animate, message.id, message.text, onTypingComplete])

  return (
    <article className={'agent-message message-' + message.type + ' message-kind-' + (isA2AT ? 'a2at' : 'process')}>
      <div className="message-head">
        <span className="agent-avatar">{avatarByType[message.type] || '•'}</span>
        {isA2AT ? <strong className="message-route">{route}</strong> : <strong>{displayAgent}</strong>}
        <span className="message-kind">{isA2AT ? copy.a2aMessage : copy.executionRecord}</span>
        <time>{message.time}</time>
      </div>
      <p>{visibleText}{(!message.a2aTaskMarkdown || !visibleTaskMarkdown) && <i className={'message-caret ' + (typing ? '' : 'done')} aria-hidden="true"></i>}</p>
      {message.a2aTaskMarkdown && <pre className="message-a2a-markdown">{visibleTaskMarkdown}{Boolean(visibleTaskMarkdown) && <i className={'message-caret ' + (typing ? '' : 'done')} aria-hidden="true"></i>}</pre>}
    </article>
  )
}

function formatObservationDuration(milliseconds, language) {
  const seconds = Math.max(1, Math.round(milliseconds / 1000))
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  if (language === 'EN') return minutes ? `${minutes}m ${remainder}s` : `${remainder}s`
  return minutes ? `${minutes}分${remainder}秒` : `${remainder}秒`
}

function formatObservationLatency(milliseconds, language) {
  const value = (milliseconds / 1000).toFixed(1)
  return language === 'EN' ? `${value}s` : `${value}秒`
}

function buildObservabilityEvents({ runId, variant, messages, focusHistory }) {
  const events = [{ type: 'run.started', runId: runId || 'RUN-OBSERVABILITY' }]
  messages.forEach((message, index) => {
    const stage = message.stage || index + 1
    const focus = variant === 'assisted' ? focusHistory[index] : null
    if (focus) events.push({ type: 'ontology.focus', stage, focus })
    events.push({
      type: 'agent.message',
      stage,
      phase: variant,
      message: { agent: message.agent, role: message.type, text: message.text },
    })
    if (message.type === 'a2a') events.push({ type: 'a2at.request', stage })
    if (message.type === 'response') events.push({ type: 'a2at.response', stage })
  })
  events.push({ type: 'run.completed', runId: runId || 'RUN-OBSERVABILITY' })
  return events
}

function presentObservabilityEvent(event) {
  const visibleEvent = { ...event }
  delete visibleEvent.mode
  delete visibleEvent.simulated
  return visibleEvent
}

function TokenUsageSummary({ variant, profile, language, onClick, onPointerDown, onPointerUp, onPointerCancel, open, drawerId }) {
  const copy = tokenUsageCopy[language] ?? tokenUsageCopy['中']
  const stageLabels = copy[variant]

  return (
    <button type="button" className={'token-usage-summary token-usage-' + variant + (language === 'EN' ? ' token-language-en' : '') + (open ? ' open' : '')} aria-label={`${copy.title} · ${open ? copy.collapse : copy.viewDetails}`} aria-haspopup="dialog" aria-expanded={open} aria-controls={drawerId} onClick={onClick} onPointerDown={onPointerDown} onPointerUp={onPointerUp} onPointerCancel={onPointerCancel}>
      <div className="token-summary-heading">
        <span>{copy.title}</span>
        <b>{copy.total} {profile.total.toLocaleString()} <em>tokens</em></b>
        <span className="token-summary-action" title={open ? copy.collapse : copy.viewDetails} aria-hidden="true">{open ? '▼' : '▲'}</span>
      </div>
      <div className="token-stage-bar" aria-hidden="true">
        {profile.steps.map((value, index) => <i key={stageLabels[index]} className={value === 0 ? 'zero' : ''} style={{ flexGrow: value }}></i>)}
      </div>
      <div className="token-stage-list">
        {profile.steps.map((value, index) => (
          <span key={stageLabels[index]} className={value === 0 ? 'zero' : ''}><i aria-hidden="true"></i>{stageLabels[index]}<b>{value.toLocaleString()}</b></span>
        ))}
      </div>
    </button>
  )
}

function ObservabilityTokenBreakdown({ profile, stageLabels }) {
  const maxValue = Math.max(...profile.steps, 1)
  return (
    <div className="observability-run-token-list">
      {profile.steps.map((value, index) => (
        <div className="observability-run-token-row" key={`${stageLabels[index]}-${index}`}>
          <span>{stageLabels[index]}</span>
          <div><i style={{ width: `${value ? Math.max(4, value / maxValue * 100) : 0}%` }}></i></div>
          <b>{value.toLocaleString()}</b>
        </div>
      ))}
    </div>
  )
}

function ObservabilityChainRow({ message, index, copy, language }) {
  const localized = localizeMessage(message, language)
  const isCall = message.type === 'a2a' || message.type === 'response'
  const label = isCall ? (message.type === 'response' ? 'OMC → OSS' : 'OSS → OMC') : cleanMessageAgent(localized.agent)
  const kind = isCall ? copy.call : copy.executionRecord
  return (
    <article className={'observability-run-chain-row ' + (isCall ? 'call' : '')}>
      <span className="observability-run-chain-index">{String(index + 1).padStart(2, '0')}</span>
      <div className="observability-run-chain-copy">
        <div className="observability-run-chain-head"><strong>{label}</strong><span>{kind}</span><time>{message.time}</time></div>
        <p>{localized.text}</p>
      </div>
      <b className="observability-run-chain-status">{copy.success}</b>
    </article>
  )
}

function ObservabilityProcessDetail({ process, status, copy, language, activeTab, onTabChange, runId, focusHistory, eventLog, showHeader = true }) {
  const { id, label, profile, performance, messages, stageLabels } = process
  const toolMessages = messages.filter((message) => message.type === 'a2a' || message.type === 'response')
  const rawEvents = eventLog.length
    ? eventLog
    : buildObservabilityEvents({ runId, variant: id, messages, focusHistory })
  const visibleRawEvents = rawEvents.map(presentObservabilityEvent)
  const tabs = [
    { id: 'agent', label: copy.agentPerformance },
    { id: 'tools', label: copy.toolAnalysis },
    { id: 'chain', label: copy.callChain },
    { id: 'raw', label: copy.rawLog },
  ]

  return (
    <article className="observability-run-detail-card" aria-labelledby={showHeader ? `observability-${id}-detail-title` : undefined} aria-label={showHeader ? undefined : label}>
      {showHeader && <header className="observability-run-detail-header">
        <div className="observability-run-detail-name">
          <i aria-hidden="true">{id === 'baseline' ? '01' : '02'}</i>
          <div><h3 id={`observability-${id}-detail-title`}>{label}</h3><p>{copy.callChainHint}</p></div>
        </div>
        <span className="observability-run-detail-status">{status || copy.completed}</span>
      </header>}

      <nav className="observability-run-detail-tabs" role="tablist" aria-label={`${label} · ${copy.kicker}`}>
        {tabs.map((tab) => <button type="button" role="tab" aria-selected={activeTab === tab.id} aria-controls={`observability-${id}-${tab.id}-panel`} className={activeTab === tab.id ? 'active' : ''} onClick={() => onTabChange(tab.id)} key={tab.id}>{tab.label}</button>)}
      </nav>

      <div className="observability-run-detail-content">
        {activeTab === 'chain' && <section className="observability-run-tab-panel" id={`observability-${id}-chain-panel`} role="tabpanel">
          <div className="observability-run-panel-head"><div><h4>{copy.callChain}</h4><p>{copy.callChainHint}</p></div><span>{messages.length} {copy.records}</span></div>
          <div className="observability-run-chain-list" key={`${id}-chain`}>
            {!messages.length && <p className="observability-empty">{copy.emptyChain}</p>}
            {messages.map((message, index) => <ObservabilityChainRow key={message.id || `${id}-${message.time}-${index}`} message={message} index={index} copy={copy} language={language} />)}
          </div>
        </section>}

        {activeTab === 'agent' && <section className="observability-run-tab-panel" id={`observability-${id}-agent-panel`} role="tabpanel">
          <div className="observability-run-panel-head"><div><h4>{copy.agentPerformance}</h4><p>{copy.tokenBreakdown}</p></div></div>
          <div className="observability-run-performance-grid"><article><span>{copy.firstResponse}</span><strong>{formatObservationLatency(performance.firstResponseMs, language)}</strong></article><article><span>{copy.duration}</span><strong>{formatObservationDuration(performance.durationMs, language)}</strong></article></div>
          <div className="observability-run-breakdown"><div className="observability-run-breakdown-head"><strong>{copy.tokenBreakdown}</strong><span>{profile.total.toLocaleString()} {copy.tokens}</span></div><ObservabilityTokenBreakdown profile={profile} stageLabels={stageLabels} /></div>
        </section>}

        {activeTab === 'tools' && <section className="observability-run-tab-panel" id={`observability-${id}-tools-panel`} role="tabpanel">
          <div className="observability-run-panel-head"><div><h4>{copy.toolAnalysis}</h4><p>{copy.callChainHint}</p></div><span>{toolMessages.length} {copy.toolCalls}</span></div>
          <div className="observability-run-chain-list observability-run-tool-list" key={`${id}-tools`}>
            {!toolMessages.length && <div className="observability-run-empty"><strong>{copy.noToolCalls}</strong></div>}
            {toolMessages.map((message, index) => <ObservabilityChainRow key={message.id || `${id}-tool-${message.time}-${index}`} message={message} index={index} copy={copy} language={language} />)}
          </div>
        </section>}


        {activeTab === 'raw' && <section className="observability-run-tab-panel" id={`observability-${id}-raw-panel`} role="tabpanel"><div className="observability-run-panel-head"><div><h4>{copy.rawLog}</h4><p>{copy.rawHint}</p></div><span>{visibleRawEvents.length} {copy.eventsRecorded}</span></div>{visibleRawEvents.length ? <pre className="observability-run-raw-log">{JSON.stringify(visibleRawEvents.slice(-80), null, 2)}</pre> : <p className="observability-empty">{copy.emptyRaw}</p>}</section>}
      </div>
    </article>
  )
}

function ObservabilityDrawer({ variant, open, runId, status, profile, performance, messages, focusHistory, eventLog, language }) {
  const copy = observabilityCopy[language] ?? observabilityCopy['中']
  const label = variant === 'assisted' ? copy.processTwo : copy.processOne
  const stageLabels = tokenUsageCopy[language]?.[variant] ?? tokenUsageCopy['中'][variant]
  const process = { id: variant, label, profile, performance, messages, stageLabels }
  const [activeTab, setActiveTab] = useState('chain')

  return (
    <section id={`observability-drawer-${variant}`} className={'observability-drawer' + (open ? ' open' : '')} role="dialog" aria-modal="false" aria-hidden={!open} aria-label={`${copy.kicker} · ${label}`}>
      <div id={`observability-drawer-${variant}-content`} className="observability-drawer-content">
        <ObservabilityProcessDetail process={process} status={status} copy={copy} language={language} activeTab={activeTab} onTabChange={setActiveTab} runId={runId} focusHistory={focusHistory} eventLog={eventLog} showHeader={false} />
      </div>
    </section>
  )
}

export default function AgentDiagnosis({ notify, theme, language = '中' }) {
  const copy = uiCopy[language] ?? uiCopy['中']
  const [collapsed, setCollapsed] = useState(false)
  const [input, setInput] = useState(language === 'EN' ? seedInputEN : seedInput)
  const [messages, setMessages] = useState(openingMessages)
  const [baselinePendingMessages, setBaselinePendingMessages] = useState([])
  const [assistedPendingMessages, setAssistedPendingMessages] = useState([])
  const [isBaselineTyping, setIsBaselineTyping] = useState(false)
  const [isAssistedTyping, setIsAssistedTyping] = useState(false)
  const [baselineRunning, setBaselineRunning] = useState(false)
  const [, setStage] = useState(0)
  const [running, setRunning] = useState(false)
  const [focus, setFocus] = useState(defaultFocus)
  const [focusHistory, setFocusHistory] = useState([])
  const [ontologyActive, setOntologyActive] = useState(false)
  const [runId, setRunId] = useState('')
  const [selectedRecordId, setSelectedRecordId] = useState('')
  const [result, setResult] = useState(null)
  const [eventLog, setEventLog] = useState([])
  const [observabilityDrawers, setObservabilityDrawers] = useState({ baseline: false, assisted: false })
  const controllerRef = useRef(null)
  const baselineConversationRef = useRef(null)
  const assistedConversationRef = useRef(null)
  const ontologyFrame = useRef(null)
  const focusByStageRef = useRef({})

  useEffect(() => {
    setInput((current) => {
      const matchedQuestion = quickQuestions.find((item) => current === item.value || current === item.valueEN)
      if (current === seedInput || current === seedInputEN) return language === 'EN' ? seedInputEN : seedInput
      if (matchedQuestion) return language === 'EN' ? (matchedQuestion.valueEN ?? matchedQuestion.value) : matchedQuestion.value
      return current
    })
  }, [language])

  useEffect(() => {
    const selectedHistoryRecord = historySeed.find((record) => record.id === selectedRecordId)
    if (!selectedHistoryRecord || running) return
    setInput(language === 'EN' ? (selectedHistoryRecord.queryEN ?? selectedHistoryRecord.query) : selectedHistoryRecord.query)
  }, [language, running, selectedRecordId])

  const syncOntologyFocus = useCallback(() => {
    const lowerLayerLinks = new Set(['设备类→设备离线', '业务类→隧道故障', '连接类→链路故障', '离线→单板根因', '离线→供电根因', '链路→光模块根因', '隧道→光纤根因', '隧道→光模块根因'])
    const lowerLayerOpened = (focus.links || []).some((link) => lowerLayerLinks.has(link))
    const operationTaskNodes = new Set(['TaskPolicyIntent', 'TaskFaultAwareness', 'TaskRiskAnalysis', 'TaskProblemAnalysis', 'TaskSolutionDecision', 'TaskRepairExecution'])
    const thirdLayerNodes = (nodes = []) => nodes.filter((node) => node.startsWith('Cat') || operationTaskNodes.has(node))
    const thirdLayerLinks = new Set(['故障流进入定界定位', '定界定位支撑方案决策', '设备状态影响连接', '连接质量影响业务', '环境变化影响设备运行', '协议状态影响连接', '外部条件影响运行环境', '跨专业状态影响连接', '跨专业信息关联业务'])
    const isBillingFocus = ['账单情况核对', '订购关系核对', '优惠规则核对', '处理结论'].includes(focus.actor)
    const ontologyPathNodes = isBillingFocus ? [] : ['DomainIPNetwork', 'ServiceFaultManagement']
    const ontologyPathLinks = isBillingFocus ? [] : ['IP网包含故障管理']
    const operationTaskContextNodes = isBillingFocus ? [] : [...operationTaskNodes]
    const operationTaskContextLinks = isBillingFocus ? [] : ['故障管理包含策略生成', '故障管理包含故障识别', '故障管理包含隐患预测', '故障管理包含定界定位', '故障管理包含方案决策', '故障管理包含修复验证', '策略驱动故障识别', '故障流进入定界定位', '隐患流进入定界定位', '定界定位支撑方案决策', '方案决策驱动修复验证', '修复验证反馈策略']
    const focusedNodes = lowerLayerOpened ? focus.nodes : thirdLayerNodes(focus.nodes)
    const focusedLinks = lowerLayerOpened ? focus.links : (focus.links || []).filter((link) => thirdLayerLinks.has(link))
    const sourceContextNodes = focus.contextNodes?.length ? focus.contextNodes : focus.nodes
    const sourceContextLinks = focus.contextLinks?.length ? focus.contextLinks : focus.links
    const contextualNodes = lowerLayerOpened ? sourceContextNodes : thirdLayerNodes(sourceContextNodes)
    const contextualLinks = lowerLayerOpened ? sourceContextLinks : (sourceContextLinks || []).filter((link) => thirdLayerLinks.has(link))
    const operationContainmentLinks = {
      TaskPolicyIntent: '故障管理包含策略生成', TaskFaultAwareness: '故障管理包含故障识别', TaskRiskAnalysis: '故障管理包含隐患预测',
      TaskProblemAnalysis: '故障管理包含定界定位', TaskSolutionDecision: '故障管理包含方案决策', TaskRepairExecution: '故障管理包含修复验证',
    }
    const categoryPathLinks = {
      CatDevice: '定界定位包含设备类', CatConnection: '定界定位包含连接类', CatService: '定界定位包含业务类', CatClock: '定界定位包含时钟类',
      CatEnvironment: '定界定位包含环境类', CatProtocol: '定界定位包含协议类', CatCrossDomain: '定界定位包含跨专业类',
    }
    const categoryLinksFor = (values = []) => [...new Set(values.map((node) => categoryPathLinks[node]).filter(Boolean))]
    const taskLinksFor = (values = []) => [...new Set(values.map((node) => operationContainmentLinks[node]).filter(Boolean))]
    const activeCategoryLinks = isBillingFocus ? [] : categoryLinksFor(focusedNodes)
    const contextCategoryLinks = isBillingFocus ? [] : categoryLinksFor(contextualNodes)
    const activeTaskLinks = isBillingFocus ? [] : taskLinksFor(focusedNodes)
    const nodes = [...ontologyPathNodes, ...(focusedNodes || [])]
    const contextNodes = [...ontologyPathNodes, ...operationTaskContextNodes, ...(contextualNodes || [])]
    const links = [...ontologyPathLinks, ...activeTaskLinks, ...activeCategoryLinks, ...(focusedLinks || [])]
    const contextLinks = [...ontologyPathLinks, ...operationTaskContextLinks, ...contextCategoryLinks, ...(contextualLinks || [])]
    ontologyFrame.current?.contentWindow?.postMessage({
      type: 'ontology-diagnosis-view', theme, language, nodes, links, contextNodes, contextLinks, zoomScale: focus.zoomScale, compact: true, resetHistory: focus.resetHistory || focus.stage === 1,
    }, '*')
  }, [focus, language, theme])

  useEffect(() => () => controllerRef.current?.abort(), [])
  useEffect(() => { syncOntologyFocus() }, [syncOntologyFocus])
  useEffect(() => {
    baselineConversationRef.current?.scrollTo({ top: baselineConversationRef.current.scrollHeight, behavior: 'smooth' })
    assistedConversationRef.current?.scrollTo({ top: assistedConversationRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])
  useEffect(() => {
    if (isBaselineTyping || !baselinePendingMessages.length) return
    const [nextMessage, ...remaining] = baselinePendingMessages
    setMessages((current) => [...current, nextMessage])
    setBaselinePendingMessages(remaining)
    setIsBaselineTyping(Boolean(nextMessage.animate))
  }, [isBaselineTyping, baselinePendingMessages])
  useEffect(() => {
    if (isAssistedTyping || !assistedPendingMessages.length) return
    const [nextMessage, ...remaining] = assistedPendingMessages
    setMessages((current) => [...current, nextMessage])
    setAssistedPendingMessages(remaining)
    setIsAssistedTyping(Boolean(nextMessage.animate))
    const nextFocus = focusByStageRef.current[nextMessage.stage]
    if (nextFocus) {
      setFocus({ ...nextFocus, stage: nextMessage.stage })
      setFocusHistory((prev) => {
        if (prev.some((f) => f.stage === nextMessage.stage)) return prev
        return [...prev, { ...nextFocus, stage: nextMessage.stage }]
      })
    }
    setStage(nextMessage.stage || 0)
    setOntologyActive(true)
  }, [isAssistedTyping, assistedPendingMessages])

  const handleBaselineMessageTypingComplete = useCallback(() => setIsBaselineTyping(false), [])
  const handleAssistedMessageTypingComplete = useCallback(() => setIsAssistedTyping(false), [])

  const handleEvent = (event) => {
    setEventLog((current) => [...current, { ...event, observedAt: new Date().toISOString() }])
    if (event.type === 'run.started') {
      setRunId(event.runId)
      setSelectedRecordId(event.runId)
    }

    if (event.type === 'ontology.focus') {
      focusByStageRef.current[event.stage] = event.focus
    }
    if (event.type === 'agent.message') {
      const phase = event.stage === 0 && event.message.role !== 'ontology-reasoner' ? 'baseline' : 'assisted'
      const appendMessage = (current) => [...current, {
        id: event.stage + '-' + Date.now() + '-' + current.length,
        agent: event.message.agent,
        type: messageType(event.message.agent, event.stage, event.message.role),
        time: timeLabel(event.message.timestamp),
        text: event.message.text,
        phase,
        stage: event.stage,
        a2aTaskMarkdown: event.message.a2aTaskMarkdown,
        animate: true,
      }]
      if (phase === 'baseline') setBaselinePendingMessages(appendMessage)
      else setAssistedPendingMessages(appendMessage)
    }
    if (event.type === 'run.completed') {
      setResult(event.result)
      setRunning(false)
    }
    if (event.type === 'baseline.completed') setBaselineRunning(false)
    if (event.type === 'run.failed') throw new Error(event.error)
  }

  const runExecution = async () => {
    if (!input.trim()) return notify(copy.fillInput)
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setRunning(true)
    setBaselineRunning(true)
    setStage(0)
    setFocus(defaultFocus)
    setFocusHistory([])
    focusByStageRef.current = {}
    setOntologyActive(false)
    setMessages(openingMessages)
    setBaselinePendingMessages([])
    setAssistedPendingMessages([])
    setIsBaselineTyping(false)
    setIsAssistedTyping(false)
    setResult(null)
    setEventLog([])
    setObservabilityDrawers({ baseline: false, assisted: false })

    try {
      const response = await fetch('/api/runs', {
        method: 'POST',
        signal: controller.signal,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ input: input.trim(), language }),
      })
      if (!response.ok) {
        const payload = await response.json()
        throw new Error(payload.error || copy.executionFailed)
      }
      if (!response.body) throw new Error(copy.streamingUnsupported)
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let sawTerminalEvent = false
      while (true) {
        const { value, done } = await reader.read()
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) if (line.trim()) {
          const event = JSON.parse(line)
          if (event.type === 'run.completed' || event.type === 'run.failed') sawTerminalEvent = true
          handleEvent(event)
        }
        if (done) break
      }
      if (buffer.trim()) {
        const event = JSON.parse(buffer)
        if (event.type === 'run.completed' || event.type === 'run.failed') sawTerminalEvent = true
        handleEvent(event)
      }
      if (!sawTerminalEvent) throw new Error(copy.streamInterrupted)
    } catch (error) {
      if (error.name === 'AbortError') return
      setRunning(false)
      setBaselineRunning(false)
      setMessages((current) => [...current, { id: 'error-' + Date.now(), agent: copy.executionService, type: 'error', time: timeLabel(), text: error.message }])
      notify(error.message)
    }
  }


  const hasExecution = running || Boolean(result) || messages.length > 0 || baselinePendingMessages.length > 0 || assistedPendingMessages.length > 0

  const loadRecord = (record) => {
    if (running) return
    setSelectedRecordId(record.id)
    setRunId(record.id)
    setInput(language === 'EN' ? (record.queryEN ?? record.query ?? input) : (record.query ?? input))
    setStage(record.category === 'billing' ? 4 : 8)
    setFocus({ ...focusForRecord(record), resetHistory: true })
    setFocusHistory(focusHistoryForRecord(record))
    setOntologyActive(true)
    setResult(null)
    setMessages(mockMessagesForRecord(record))
    setBaselinePendingMessages([])
    setAssistedPendingMessages([])
    setIsBaselineTyping(false)
    setIsAssistedTyping(false)
    setBaselineRunning(false)
    setEventLog([])
    setObservabilityDrawers({ baseline: false, assisted: false })
  }

  const baselineMessages = messages.filter((message) => message.phase === 'baseline')
  const assistedMessages = messages.filter((message) => message.phase !== 'baseline')
  const baselinePending = baselinePendingMessages.length > 0
  const assistedPending = assistedPendingMessages.length > 0
  const selectedHistoryRecord = historySeed.find((record) => record.id === selectedRecordId)
  const tokenUsageCategory = selectedHistoryRecord?.category ?? inferTokenUsageCategory(input)
  const tokenUsageProfile = tokenUsageProfiles[tokenUsageCategory] ?? tokenUsageProfiles.business
  const observationCategoryProfile = observationProfiles[tokenUsageCategory] ?? observationProfiles.business
  const baselineTokenReady = baselineMessages.length > 0 && !baselineRunning && !baselinePending && !isBaselineTyping
  const assistedTokenReady = assistedMessages.length > 0 && !running && !assistedPending && !isAssistedTyping

  const currentRecord = runId && !historySeed.some((record) => record.id === runId) ? {
    id: runId, time: timeLabel().slice(0, 5), title: input.trim(),
    meta: running ? copy.runningStatus : result ? copy.completedStatus : copy.stoppedStatus, query: input,
  } : null
  const observabilityStatus = running ? copy.runningStatus : (result || selectedHistoryRecord ? copy.completedStatus : copy.stoppedStatus)
  const toggleObservabilityDrawer = (variant) => setObservabilityDrawers((current) => ({ ...current, [variant]: !current[variant] }))
  const observabilityDragRef = useRef({ variant: '', pointerId: null, startY: 0, suppressClick: false })
  const handleObservabilityClick = (variant) => {
    if (observabilityDragRef.current.suppressClick) {
      observabilityDragRef.current.suppressClick = false
      return
    }
    toggleObservabilityDrawer(variant)
  }
  const handleObservabilityPointerDown = (variant, event) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return
    observabilityDragRef.current = { variant, pointerId: event.pointerId, startY: event.clientY, suppressClick: false }
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }
  const handleObservabilityPointerUp = (variant, event) => {
    const drag = observabilityDragRef.current
    if (drag.variant !== variant || drag.pointerId !== event.pointerId) return
    const distance = event.clientY - drag.startY
    const shouldOpen = !observabilityDrawers[variant] && distance <= -36
    const shouldClose = observabilityDrawers[variant] && distance >= 36
    observabilityDragRef.current.suppressClick = Math.abs(distance) >= 8
    if (shouldOpen || shouldClose) {
      setObservabilityDrawers((current) => ({ ...current, [variant]: shouldOpen }))
    }
    event.currentTarget.releasePointerCapture?.(event.pointerId)
  }
  const handleObservabilityPointerCancel = () => {
    observabilityDragRef.current = { variant: '', pointerId: null, startY: 0, suppressClick: false }
  }

  return (
    <section className={'application-page ' + (collapsed ? 'history-collapsed' : '')} aria-label={language === 'EN' ? 'Ontology application execution' : '本体应用执行'}>
      <aside className="incident-history panel">
        <div className="history-head">
          {!collapsed && <h2>{copy.executionHistory}</h2>}
          <button className="collapse-button" onClick={() => setCollapsed((value) => !value)} aria-label={collapsed ? copy.expandHistory : copy.collapseHistory}>{collapsed ? '›' : '‹'}</button>
        </div>
        {!collapsed && <>
          <div className="history-filter"><span>⌕</span><span>{copy.historyFilter}</span></div>
          <div className="history-date">{copy.recentRuns}</div>
          <div className="history-list">
            {[...(currentRecord ? [currentRecord] : []), ...historySeed].map((item) => (
              <button key={item.id} className={item.id === selectedRecordId ? 'active' : ''} onClick={() => loadRecord(item)}>
                <span className={'incident-state ' + (item.meta === '运行中' ? 'running' : 'done')}></span>
                <span className="incident-copy"><strong>{language === 'EN' ? (item.titleEN ?? item.title) : item.title}</strong><small>{item.id} · {language === 'EN' ? (item.metaEN ?? item.meta) : item.meta}</small></span>
                <time>{item.time}</time>
              </button>
            ))}
          </div>
        </>}
      </aside>

      <div className="application-main">
        <header className="application-trigger">
          <label className="event-input">
            <span className="input-type">{copy.input}</span>
            <input value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !running) runExecution() }} aria-label={copy.userInput} />
            <button onClick={runExecution} disabled={running}>{running ? <><i className="button-spinner"></i>{copy.running}</> : <>{copy.start} <span>→</span></>}</button>
          </label>
          <div className="quick-questions" aria-label={copy.commonQuestions}>
            <span>{copy.commonQuestions}</span>
            {quickQuestions.map((item) => <button key={item.label} type="button" onClick={() => setInput(language === 'EN' ? (item.valueEN ?? item.value) : item.value)}>{language === 'EN' ? (item.labelEN ?? item.label) : item.label}</button>)}
          </div>
        </header>

        <div className="application-workspace ontology-application-workspace">
          <section className="ontology-reasoner panel">
            <div className="application-panel-head">
              <div><h2>{copy.ontologyView}</h2><p className="panel-subtitle">{copy.ontologySubtitle}</p></div>
              <div className="ontology-head-tools">
                <details className="ontology-download-menu">
                  <summary>{copy.downloadOntology}</summary>
                  <a href="/ontology/downloads/ip-network-fault-management.owl" download="ip-network-five-layer-tbox.owl">{language === 'EN' ? 'OWL format' : 'OWL格式'}</a>
                  <a href="/ontology/downloads/ip-network-fault-management.ttl" download="ip-network-five-layer-tbox.ttl">{language === 'EN' ? 'TTL format' : 'TTL格式'}</a>
                </details>
              </div>
            </div>
            <div className="ontology-diagnosis-canvas ontology-application-canvas">
              {hasExecution && ontologyActive ? <iframe ref={ontologyFrame} title={language === 'EN' ? 'Third-layer ontology view synchronized with execution stages' : '随执行阶段联动的第三层本体视图'} src={`/ontology/index.html?theme=${theme}&language=${language}`} onLoad={syncOntologyFocus} /> : <div className="application-empty-state ontology-empty-state"><i aria-hidden="true">◇</i><strong>{hasExecution ? copy.waitingForReasoning : copy.waitingForInput}</strong><p>{hasExecution ? copy.reasoningWaiting : copy.inputWaiting}</p></div>}
            </div>
            <ReasoningTree focusHistory={focusHistory} result={result} theme={theme} hasExecution={hasExecution} input={input} language={language} />
          </section>



            <aside className={'agent-conversation application-agent-panel baseline-panel panel' + (baselineTokenReady ? ' has-token-summary' : '')}>
              <div className="application-panel-head">
                <div><h2>{copy.withoutOntology}</h2><p className="panel-subtitle">{copy.collaborationSubtitle}</p></div>
              </div>
              <div className="message-stream" ref={baselineConversationRef} aria-live="polite">
                {!baselineMessages.length && !baselinePending && <div className="application-empty-state conversation-empty-state"><i aria-hidden="true">⌁</i><strong>{copy.waitingForUser}</strong><p>{copy.startAfterInput}</p></div>}
                {baselineMessages.map((message) => <Message key={message.id} message={message} onTypingComplete={handleBaselineMessageTypingComplete} copy={copy} language={language} />)}
                {baselineRunning && <div className="agent-typing"><i></i><i></i><i></i><span>{copy.analyzing}</span></div>}
              </div>
              {baselineTokenReady && <div className={'observability-drawer-host' + (observabilityDrawers.baseline ? ' open' : '')}>
                <TokenUsageSummary variant="baseline" profile={tokenUsageProfile.baseline} language={language} open={observabilityDrawers.baseline} drawerId="observability-drawer-baseline" onClick={() => handleObservabilityClick('baseline')} onPointerDown={(event) => handleObservabilityPointerDown('baseline', event)} onPointerUp={(event) => handleObservabilityPointerUp('baseline', event)} onPointerCancel={handleObservabilityPointerCancel} />
                <ObservabilityDrawer variant="baseline" open={observabilityDrawers.baseline} runId={runId || selectedRecordId} status={observabilityStatus} profile={tokenUsageProfile.baseline} performance={observationCategoryProfile.baseline} messages={baselineMessages} focusHistory={focusHistory} eventLog={eventLog} language={language} />
              </div>}
            </aside>

            <div className="ontology-comparison-divider" aria-hidden="true"></div>

            <aside className={'agent-conversation application-agent-panel assisted-panel panel' + (assistedTokenReady ? ' has-token-summary' : '')}>
              <div className="application-panel-head">
                <div><h2>{copy.withOntology}</h2><p className="panel-subtitle">{copy.collaborationSubtitle}</p></div>
              </div>
              <div className="message-stream" ref={assistedConversationRef} aria-live="polite">
                {!assistedMessages.length && !assistedPending && <div className="application-empty-state conversation-empty-state"><i aria-hidden="true">◇</i><strong>{copy.waitingForUser}</strong><p>{copy.startAfterInput}</p></div>}
                {assistedMessages.map((message) => <Message key={message.id} message={message} onTypingComplete={handleAssistedMessageTypingComplete} copy={copy} language={language} />)}
                {running && <div className="agent-typing"><i></i><i></i><i></i><span>{copy.analyzing}</span></div>}
              </div>
              {assistedTokenReady && <div className={'observability-drawer-host' + (observabilityDrawers.assisted ? ' open' : '')}>
                <TokenUsageSummary variant="assisted" profile={tokenUsageProfile.assisted} language={language} open={observabilityDrawers.assisted} drawerId="observability-drawer-assisted" onClick={() => handleObservabilityClick('assisted')} onPointerDown={(event) => handleObservabilityPointerDown('assisted', event)} onPointerUp={(event) => handleObservabilityPointerUp('assisted', event)} onPointerCancel={handleObservabilityPointerCancel} />
                <ObservabilityDrawer variant="assisted" open={observabilityDrawers.assisted} runId={runId || selectedRecordId} status={observabilityStatus} profile={tokenUsageProfile.assisted} performance={observationCategoryProfile.assisted} messages={assistedMessages} focusHistory={focusHistory} eventLog={eventLog} language={language} />
              </div>}
            </aside>
        </div>
      </div>
    </section>
  )
}
