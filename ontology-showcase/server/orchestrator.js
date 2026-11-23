const focus = {
  1: { actor: '问题分析', label: '在 OSS 侧汇集故障、观测与历史信息', nodes: ['CatService', 'CatDevice', 'CatConnection'], links: [] },
  2: { actor: '问题分析', label: '在跨系统解决方案层判别故障类别', nodes: ['CatService', 'CatDevice', 'CatConnection'], links: [] },
  3: { actor: '关系分析', label: '按故障类别关联专业本体与承载资源', nodes: ['CatService', 'DedicatedLineSvc', 'TunnelFault'], links: ['业务类→隧道故障'] },
  4: { actor: 'OSS–OMC', label: 'OSS–OMC 连接解决方案层与逻辑资源层', nodes: ['CatService', 'TunnelFault', 'LinkFault'], links: ['业务类→隧道故障'] },
  5: { actor: '状态查询', label: '在逻辑资源层与物理资源层之间定位', nodes: ['LinkFault', 'FiberFault', 'OpticalModule'], links: ['链路→光纤根因', '链路→光模块根因'] },
  6: { actor: '状态查询', label: '返回逻辑对象状态与物理根因', nodes: ['LinkFault', 'FiberFault', 'OpticalModule'], links: ['链路→光纤根因', '链路→光模块根因'] },
  7: { actor: '结果回填', label: '回填 D 状态并继续完成 D→E→F 推理', nodes: ['SLAContract', 'DedicatedLineSvc', 'CatService', 'TunnelFault', 'LinkFault', 'FiberFault'], links: ['业务类→隧道故障', '隧道→光纤根因', '链路→光纤根因'] },
}

const fallbackBoundary = {
  summary: '关系匹配：专线、SLA、承载服务；',
  path: ['业务异常 A', '专线服务 B', '承载隧道 C', '网元对象 D'],
  boundaryObject: {
    id: 'PE-GZ-03', type: 'NetworkObject', responsibilityDomain: 'vendor:huawei',
    knownState: { operState: 'unknown', alarmState: 'unavailable' },
    requestedAttributes: ['operState', 'faultCause', 'confidence'],
  },
  capability: 'update-network-object-state',
}
const fallbackDiagnosis = {
  objectId: 'PE-GZ-03', operState: 'impaired', faultCause: '尾纤故障', confidence: 0.96,
  evidenceSummary: '厂商域专业能力确认链路光功率异常，根因指向尾纤。',
}

const solutionLayerFullNodes = [
  'CatDevice', 'CatConnection', 'CatService', 'CatClock', 'CatEnvironment', 'CatProtocol', 'CatCrossDomain',
]
const solutionLayerLinks = [
  '环境变化影响设备运行',
  '设备状态影响连接',
  '协议状态影响连接',
  '时钟状态影响业务',
  '连接质量影响业务',
  '外部条件影响运行环境',
  '跨专业状态影响连接',
  '跨专业信息关联业务',
]
function stageFocus(actor, label, nodes, links, contextNodes = solutionLayerFullNodes, contextLinks = solutionLayerLinks, zoomScale = 1) {
  return { actor, label, nodes, links, contextNodes, contextLinks, zoomScale }
}
function connectFaultOperationFlow(views) {
  const analysisNodes = ['TaskFaultAwareness', 'TaskProblemAnalysis']
  const analysisLinks = ['故障流进入定界定位']
  const connect = (view, phase = 'analysis') => {
    const operationNodes = phase === 'awareness'
      ? ['TaskFaultAwareness']
      : phase === 'decision'
        ? [...analysisNodes, 'TaskSolutionDecision']
        : analysisNodes
    const operationLinks = phase === 'awareness'
      ? []
      : phase === 'decision'
        ? [...analysisLinks, '定界定位支撑方案决策']
        : analysisLinks
    return {
      ...view,
      nodes: [...operationNodes, ...(view.nodes || [])],
      links: [...operationLinks, ...(view.links || [])],
    }
  }
  return {
    full: connect(views.full, 'awareness'),
    ruleCandidates: connect(views.ruleCandidates),
    evidenceCandidates: connect(views.evidenceCandidates),
    final: connect(views.final),
    gate: connect(views.gate),
    request: connect(views.request),
    response: connect(views.response),
    closure: connect(views.closure, 'decision'),
  }
}
function reasoningFocuses(faultClass) {
  const isDevice = faultClass.label.includes('设备')
  if (isDevice) {
    const usedThirdNodes = ['CatDevice', 'CatConnection', 'CatService']
    const usedThirdLinks = ['设备状态影响连接', '连接质量影响业务']
    const crossLayerContextNodes = [...solutionLayerFullNodes, 'DeviceOffline', 'BoardFault', 'PowerFault']
    const crossLayerContextLinks = [...solutionLayerLinks, '设备类→设备离线', '离线→单板根因', '离线→供电根因']
    return connectFaultOperationFlow({
      full: stageFocus('故障范围梳理', '先从设备类型开始核对', ['CatDevice'], []),
      ruleCandidates: stageFocus('故障类型初判', '运行现象关联到设备、连接及外部条件', ['CatDevice', 'CatConnection', 'CatEnvironment', 'CatProtocol', 'CatCrossDomain'], ['环境变化影响设备运行', '设备状态影响连接', '协议状态影响连接', '外部条件影响运行环境', '跨专业状态影响连接']),
      evidenceCandidates: stageFocus('运行情况核对', '离线时间与设备状态一致，继续核对连接影响', usedThirdNodes, usedThirdLinks),
      final: stageFocus('故障类型确认', '设备异常沿连接关系影响业务', usedThirdNodes, usedThirdLinks),
      gate: stageFocus('信息缺口确认', '设备侧状态尚未返回，当前路径暂留在设备节点', usedThirdNodes, usedThirdLinks),
      request: stageFocus('OSS–OMC', '从设备类型关联到下层网元对象', [...usedThirdNodes, 'DeviceOffline'], [...usedThirdLinks, '设备类→设备离线'], crossLayerContextNodes, crossLayerContextLinks),
      response: stageFocus('OSS–OMC', '网元状态返回后关联单板与供电情况', [...usedThirdNodes, 'DeviceOffline', 'BoardFault', 'PowerFault'], [...usedThirdLinks, '设备类→设备离线', '离线→单板根因', '离线→供电根因'], crossLayerContextNodes, crossLayerContextLinks),
      closure: stageFocus('诊断结论', '设备至业务的影响路径与单板异常对应', [...usedThirdNodes, 'DeviceOffline', 'BoardFault'], [...usedThirdLinks, '设备类→设备离线', '离线→单板根因'], crossLayerContextNodes, crossLayerContextLinks, 0.92),
    })
  }

  const isOptical = faultClass.label.includes('光模块')
  if (isOptical) {
    const usedThirdNodes = ['CatConnection', 'CatService']
    const usedThirdLinks = ['连接质量影响业务']
    const crossLayerContextNodes = [...solutionLayerFullNodes, 'LinkFault', 'OpticalModule']
    const crossLayerContextLinks = [...solutionLayerLinks, '连接类→链路故障', '链路→光模块根因']
    return connectFaultOperationFlow({
      full: stageFocus('故障范围梳理', '先从连接与光层故障类型开始核对', ['CatConnection'], []),
      ruleCandidates: stageFocus('故障类型初判', '丢包现象关联到连接、设备及协议状态', ['CatDevice', 'CatConnection', 'CatService', 'CatProtocol'], ['设备状态影响连接', '协议状态影响连接', '连接质量影响业务']),
      evidenceCandidates: stageFocus('运行情况核对', '端口误码与丢包时段一致，保留连接类路径', usedThirdNodes, usedThirdLinks),
      final: stageFocus('故障类型确认', '接收光功率异常沿连接关系影响业务', usedThirdNodes, usedThirdLinks),
      gate: stageFocus('信息缺口确认', '边界端口光功率尚未返回，当前路径暂留在连接节点', usedThirdNodes, usedThirdLinks),
      request: stageFocus('OSS–OMC', '从连接类型关联到下层链路对象', [...usedThirdNodes, 'LinkFault'], [...usedThirdLinks, '连接类→链路故障'], crossLayerContextNodes, crossLayerContextLinks),
      response: stageFocus('OSS–OMC', '端口状态返回后关联光模块收发光功率', [...usedThirdNodes, 'LinkFault', 'OpticalModule'], [...usedThirdLinks, '连接类→链路故障', '链路→光模块根因'], crossLayerContextNodes, crossLayerContextLinks),
      closure: stageFocus('诊断结论', '光模块接收光功率异常与 PON 口丢包对应', [...usedThirdNodes, 'LinkFault', 'OpticalModule'], [...usedThirdLinks, '连接类→链路故障', '链路→光模块根因'], crossLayerContextNodes, crossLayerContextLinks, 0.92),
    })
  }

  const usedThirdNodes = ['CatCrossDomain', 'CatConnection', 'CatService']
  const usedThirdLinks = ['跨专业状态影响连接', '连接质量影响业务']
  const crossLayerContextNodes = [...solutionLayerFullNodes, 'TunnelFault', 'FiberFault', 'OpticalModule']
  const crossLayerContextLinks = [...solutionLayerLinks, '业务类→隧道故障', '隧道→光纤根因', '隧道→光模块根因']
  return connectFaultOperationFlow({
    full: stageFocus('故障范围梳理', '先从跨专业类型开始核对', ['CatCrossDomain'], []),
    ruleCandidates: stageFocus('故障类型初判', '业务变化关联到连接、设备、协议及跨专业状态', ['CatDevice', 'CatConnection', 'CatService', 'CatProtocol', 'CatCrossDomain'], ['设备状态影响连接', '协议状态影响连接', '连接质量影响业务', '跨专业状态影响连接', '跨专业信息关联业务']),
    evidenceCandidates: stageFocus('运行情况核对', '承载告警与业务变化时间一致，保留连接影响路径', usedThirdNodes, usedThirdLinks),
    final: stageFocus('故障类型确认', '连接质量变化传导至业务表现', usedThirdNodes, usedThirdLinks),
    gate: stageFocus('信息缺口确认', '边界承载状态尚未返回，当前路径暂留在连接节点', usedThirdNodes, usedThirdLinks),
    request: stageFocus('OSS–OMC', '从业务类型关联到下层承载对象', [...usedThirdNodes, 'TunnelFault'], [...usedThirdLinks, '业务类→隧道故障'], crossLayerContextNodes, crossLayerContextLinks),
    response: stageFocus('OSS–OMC', '承载状态返回后关联尾纤与光模块情况', [...usedThirdNodes, 'TunnelFault', 'FiberFault', 'OpticalModule'], [...usedThirdLinks, '业务类→隧道故障', '隧道→光纤根因', '隧道→光模块根因'], crossLayerContextNodes, crossLayerContextLinks),
    closure: stageFocus('诊断结论', '跨专业至业务的影响路径与尾纤异常对应', [...usedThirdNodes, 'TunnelFault', 'FiberFault'], [...usedThirdLinks, '业务类→隧道故障', '隧道→光纤根因'], crossLayerContextNodes, crossLayerContextLinks, 0.92),
  })
}
function sendStage(emit, stage, agent, message, stageFocus = focus[stage], details = {}) {
  emit({ type: 'ontology.focus', stage, focus: stageFocus })
  emit({ type: 'agent.message', stage, message: {
    agent, role: agent.toLowerCase().replace(/\s/g, '-'), text: message, timestamp: new Date().toISOString(), ...details,
  } })
}

function waitForSimulation(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}



function waitForSimulationRange(minimum, maximum) {
  return waitForSimulation(minimum + Math.floor(Math.random() * (maximum - minimum + 1)))
}

const waitForBaselineSimulation = () => waitForSimulationRange(7000, 12000)
const waitForOntologySimulation = () => waitForSimulationRange(5000, 10000)

function classifyFault(input) {
  const text = String(input).toLowerCase()
  const billingKeywords = ['计费', '账单', '扣费', '套餐', '优惠', '发票', '重复收费', 'billing', 'bill', 'charge', 'invoice', 'subscription', 'discount']
  if (billingKeywords.some((keyword) => text.includes(keyword))) {
    return {
      label: '计费类非网络问题', agent: '计费推理', requiresOmc: false,
      focus: stageFocus('账单情况核对', '先核对跨专业计费信息', ['CatCrossDomain'], []),
      branchFocus: stageFocus('订购关系核对', '业务信息关联到跨专业核查', ['CatService', 'CatCrossDomain'], ['跨专业信息关联业务']),
      decisionFocus: stageFocus('优惠规则核对', '订购与优惠记录指向跨专业问题', ['CatService', 'CatCrossDomain'], ['跨专业信息关联业务']),
      closureFocus: stageFocus('处理结论', '现有信息足以在当前层完成判断', ['CatService', 'CatCrossDomain'], ['跨专业信息关联业务'], solutionLayerFullNodes, solutionLayerLinks, 0.92),
    }
  }

  const opticalKeywords = ['pon', 'olt', '光模块', '光功率', 'optical module', 'optical-module', 'receive power', 'transmit power']
  if (opticalKeywords.some((keyword) => text.includes(keyword))) {
    return {
      label: '光模块类网络故障', agent: '连接推理', requiresOmc: true,
      focus: { actor: '问题分析', label: '解决方案层判别：连接类网络故障', nodes: ['CatConnection'], links: [] },
    }
  }

  const deviceKeywords = ['设备', '网元', '单板', '掉电', '电源', '风扇', '离线', 'device', 'network element', 'board', 'controller', 'power', 'fan', 'offline', 'unreachable']
  if (deviceKeywords.some((keyword) => text.includes(keyword))) {
    return {
      label: '设备类网络故障', agent: '设备推理', requiresOmc: true,
      focus: { actor: '问题分析', label: '解决方案层判别：设备类网络故障', nodes: ['CatDevice'], links: [] },
      branchFocus: { actor: '设备推理', label: '在解决方案层展开设备故障推理', nodes: ['CatDevice', 'CatConnection', 'CatService', 'DeviceOffline', 'ResourceAnomaly'], links: ['设备状态影响连接', '连接质量影响业务', '设备类→设备离线', '设备类→资源异常'] },
      decisionFocus: { actor: '信息缺口确认', label: '还需确认厂商域内的网元运行状态', nodes: ['CatDevice', 'CatConnection', 'CatService', 'DeviceOffline'], links: ['设备状态影响连接', '连接质量影响业务', '设备类→设备离线'] },
      a2aFocus: { actor: 'OSS–OMC', label: '仅请求卡点对象的缺失状态', nodes: ['CatDevice', 'CatConnection', 'CatService', 'DeviceOffline'], links: ['设备状态影响连接', '连接质量影响业务', '设备类→设备离线'] },
      omcFocus: { actor: '状态查询', label: 'OMC 补全厂商域对象状态', nodes: ['DeviceOffline', 'BoardFault', 'PowerFault'], links: ['离线→单板根因', '离线→供电根因'] },
    }
  }
  return {
    label: '业务类网络故障', agent: '业务推理', requiresOmc: true,
    focus: { actor: '问题分析', label: '解决方案层判别：业务类网络故障', nodes: ['CatService'], links: [] },
    branchFocus: { actor: '业务推理', label: '在解决方案层沿 SLA、业务与承载关系推理', nodes: ['SLAContract', 'DedicatedLineSvc', 'CatService', 'TunnelFault'], links: ['业务类→隧道故障'] },
    decisionFocus: { actor: '信息缺口确认', label: '还需确认厂商域内的边界网元状态', nodes: ['CatService', 'TunnelFault', 'LinkFault'], links: ['业务类→隧道故障'] },
    a2aFocus: { actor: 'OSS–OMC', label: '仅请求卡点对象的缺失状态', nodes: ['TunnelFault', 'LinkFault'], links: [] },
    omcFocus: { actor: '状态查询', label: 'OMC 补全厂商域对象状态', nodes: ['LinkFault', 'FiberFault', 'OpticalModule'], links: ['链路→光纤根因', '链路→光模块根因'] },
  }
}
function buildA2ATask(boundary = fallbackBoundary) {
  const object = boundary.boundaryObject || fallbackBoundary.boundaryObject
  const requested = object.requestedAttributes || ['operState', 'faultCause', 'confidence']
  return {
    taskType: '网络对象状态补全',
    taskDescription: '状态补全请求。范围限定为单个边界对象，不包含客户资料和完整业务上下文。',
    taskTarget: '查询 ' + object.id + ' 的 ' + requested.join('、') + '。',
    taskObject: object.type + '：' + object.id,
    taskContext: [
      '责任域：' + object.responsibilityDomain,
      '当前已知状态：' + JSON.stringify(object.knownState),
      '缺失属性：' + requested.join('、'),
    ],
    expectedOutput: [
      '返回字段限于请求属性及置信度。',
      '无结果时返回原因，不追加无关字段。',
    ],
  }
}
function buildBaselineA2ATask(taskType, taskTarget, taskObject, expectedFields) {
  return {
    taskType,
    taskDescription: 'OSS 请求 OMC 核查指定网络对象状态。',
    taskTarget,
    taskObject,
    taskContext: ['依据当前故障现象限定查询范围。', '仅查询本次分析所需状态。'],
    expectedOutput: expectedFields.map((field) => '返回' + field + '。'),
  }
}
function formatA2ATaskMarkdown(task) {
  return [
    '## 任务类型(Task Type)', task.taskType,
    '## 任务描述(Task Description)', task.taskDescription,
    '## 任务目标(Task Target)', task.taskTarget,
    '## 任务对象(Task Object)', task.taskObject,
    '## 任务上下文(Task Context)', ...task.taskContext.map((item, index) => (index + 1) + '. ' + item),
    '## 预期输出(Expected Output)', ...task.expectedOutput.map((item, index) => (index + 1) + '. ' + item),
  ].join('\n')
}

function inferBoundary(input) {
  const text = String(input).toLowerCase()
  if (['pon', 'olt', '光模块', '光功率', 'optical module', 'optical-module'].some((keyword) => text.includes(keyword))) {
    return {
      summary: '关系匹配：PON端口、链路、光模块；',
      path: ['丢包异常 A', 'PON端口 B', '链路对象 C', '光模块 D'],
      boundaryObject: {
        id: 'OLT-PY-02/PON0/1', type: 'NetworkPort', responsibilityDomain: 'vendor:access-network',
        knownState: { operState: 'up', rxPowerState: 'low' },
        requestedAttributes: ['operState', 'txPower', 'rxPower', 'faultCause', 'confidence'],
      },
      capability: 'update-network-port-state',
    }
  }
  return fallbackBoundary
}

function inferVendor(boundary, input) {
  const objectId = boundary.boundaryObject?.id || fallbackDiagnosis.objectId
  const text = String(input).toLowerCase()
  if (['设备', '网元', '单板', '掉电', '电源', '风扇', '离线', 'device', 'network element', 'board', 'controller', 'power', 'fan', 'offline', 'unreachable'].some((keyword) => text.includes(keyword))) {
    return { objectId, operState: 'offline', faultCause: '单板故障', confidence: 0.94, evidenceSummary: '厂商域返回主控板异常、供电正常。' }
  }
  if (['pon', 'olt', '光模块', '光功率', 'optical module', 'optical-module', 'receive power', 'transmit power'].some((keyword) => text.includes(keyword))) {
    return { objectId, operState: 'impaired', faultCause: '光模块故障', confidence: 0.95, evidenceSummary: '厂商域返回端口状态正常、光模块接收光功率异常。' }
  }
  return { ...fallbackDiagnosis, objectId }
}
function inferClosure(input, boundary, diagnosis) {
  return {
    conclusion: 'OMC 返回的信息显示，' + diagnosis.objectId + ' 运行状态异常，故障原因为' + diagnosis.faultCause + '。',
    nextAction: '建议安排现场处理并持续观察业务 SQI，业务恢复后关闭工单。',
  }
}

async function runBaselineExploration(emit, faultClass) {
  const billingMessages = [
    { agent: '账单明细核对', text: '读取本期账单明细、订购记录和历史账单。' },
    { agent: '费用金额核对', text: '发现两笔金额相同的费用，需要继续确认是否属于不同计费项目。' },
    { agent: '计费周期核对', text: '两笔费用对应同一计费周期，不属于跨账期补收。' },
    { agent: '订购关系核对', text: '客户名下只有一条有效订购，账期内没有新增或变更记录。' },
    { agent: '费用构成核对', text: '安装费、月租费和调整项均未产生第二笔应收费用。' },
    { agent: '优惠记录核对', text: '本账期应执行的优惠规则没有生效，重复金额与应享优惠金额一致。' },
    { agent: '历史账单核对', text: '前几个账期费用正常，未发现同类重复收费记录。' },
    { agent: '处理结论', text: '确认重复计费由优惠规则未生效引起，后续生成计费冲正单。' },
  ]
  const networkMessages = [
    { agent: '事件分析', text: '读取故障事件、性能观测和历史记录。候选范围未收敛。' },
    { agent: '业务分析', text: '业务影响范围与告警对象不一致。' },
    { agent: 'A2A-T', role: 'a2a-request', text: '请求核查候选链路运行状态。', a2aTaskMarkdown: formatA2ATaskMarkdown(buildBaselineA2ATask('候选链路状态核查', '核查候选链路的运行状态与异常范围', '候选链路集合', ['运行状态', '异常对象'])) },
    { agent: 'A2A-T', role: 'a2a-response', text: '返回链路状态，存在两个异常候选。' },
    { agent: '承载分析', text: '逐段核对承载路径，部分状态与劣化时间窗一致。' },
    { agent: '告警分析', text: '设备告警和端口计数器存在多个关联对象。' },
    { agent: 'A2A-T', role: 'a2a-request', text: '请求补充端口和光模块状态。', a2aTaskMarkdown: formatA2ATaskMarkdown(buildBaselineA2ATask('端口与光模块状态核查', '补充候选端口及光模块状态', '候选端口与光模块', ['端口状态', '光模块状态'])) },
    { agent: 'A2A-T', role: 'a2a-response', text: '返回端口和光模块状态，光模块异常待复核。' },
    { agent: '历史分析', text: '同类事件修复记录与当前资源拓扑不一致。' },
    { agent: '范围复核', text: '短时波动已排除，保留链路和尾纤两个候选。' },
    { agent: 'A2A-T', role: 'a2a-request', text: '请求核查尾纤光功率和故障原因。', a2aTaskMarkdown: formatA2ATaskMarkdown(buildBaselineA2ATask('尾纤状态核查', '核查尾纤光功率并确认故障原因', '候选尾纤', ['光功率', '故障原因'])) },
    { agent: 'A2A-T', role: 'a2a-response', text: '返回尾纤光功率异常，故障原因已确认。' },
    { agent: '诊断结论', text: '已结合 OMC 返回的信息确认故障原因，诊断完成。' },
  ]
  const opticalMessages = [
    { agent: '事件分析', text: '读取故障事件、性能观测和历史记录。' },
    { agent: '业务分析', text: 'PON口丢包持续超阈，受影响业务范围还不能确定。' },
    { agent: 'A2A-T', role: 'a2a-request', text: '请求核查候选链路运行状态。', a2aTaskMarkdown: formatA2ATaskMarkdown(buildBaselineA2ATask('PON链路状态核查', '核查PON端口与候选链路的运行状态', 'OLT-PY-02/PON0/1', ['端口状态', '链路状态'])) },
    { agent: 'A2A-T', role: 'a2a-response', text: '返回链路状态，存在两个异常候选。' },
    { agent: '承载分析', text: '端口误码时段与丢包时段一致，继续核对光层状态。' },
    { agent: '告警分析', text: '端口状态正常，光模块接收光功率持续偏低。' },
    { agent: '历史分析', text: '同类事件修复记录与当前资源拓扑不一致。' },
    { agent: '范围复核', text: '短时波动已排除，保留端口和光模块两个可能原因。' },
    { agent: 'A2A-T', role: 'a2a-request', text: '请求核查光模块收发光功率和故障原因。', a2aTaskMarkdown: formatA2ATaskMarkdown(buildBaselineA2ATask('光模块状态核查', '核查光模块收发光功率并确认故障原因', 'OLT-PY-02/PON0/1', ['发送光功率', '接收光功率', '故障原因'])) },
    { agent: 'A2A-T', role: 'a2a-response', text: '返回光模块接收光功率异常，故障原因已确认。' },
    { agent: '诊断结论', text: '最终确认原因为光模块故障。' },
  ]
  const deviceMessages = [
    { agent: '事件分析', text: '读取设备离线事件、网元告警和最近一次状态记录。' },
    { agent: '设备核对', text: '网元无法连通，暂时不能确认是管理通道、单板还是供电问题。' },
    { agent: 'A2A-T', role: 'a2a-request', text: '请求核查网元在线状态和当前告警。', a2aTaskMarkdown: formatA2ATaskMarkdown(buildBaselineA2ATask('网元状态核查', '确认离线网元的在线状态和当前告警', 'PE-GZ-03', ['在线状态', '当前告警'])) },
    { agent: 'A2A-T', role: 'a2a-response', text: '网元仍处于离线状态，返回多条设备告警。' },
    { agent: '告警核对', text: '告警同时涉及主控板和电源模块，故障位置还不能确定。' },
    { agent: 'A2A-T', role: 'a2a-request', text: '请求补充主控板和电源模块状态。', a2aTaskMarkdown: formatA2ATaskMarkdown(buildBaselineA2ATask('部件状态核查', '补充主控板和电源模块状态', 'PE-GZ-03', ['主控板状态', '电源模块状态'])) },
    { agent: 'A2A-T', role: 'a2a-response', text: '电源模块工作正常，主控板状态异常。' },
    { agent: '历史核对', text: '历史记录中出现过短时管理通道中断，仍需排除重复故障。' },
    { agent: 'A2A-T', role: 'a2a-request', text: '请求确认主控板复位记录和故障原因。', a2aTaskMarkdown: formatA2ATaskMarkdown(buildBaselineA2ATask('主控板故障核查', '确认主控板复位记录和本次故障原因', 'PE-GZ-03', ['复位记录', '故障原因'])) },
    { agent: 'A2A-T', role: 'a2a-response', text: '主控板未成功复位，确认本次离线由单板故障引起。' },
    { agent: '诊断结论', text: '最终确认原因为单板故障。' },
  ]
  const messages = !faultClass.requiresOmc
    ? billingMessages
    : faultClass.label.includes('光模块')
      ? opticalMessages
      : faultClass.label.includes('设备')
        ? deviceMessages
        : networkMessages
  if (messages.length) await waitForSimulationRange(900, 1500)
  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index]
    emit({ type: 'agent.message', stage: 0, message: {
      agent: message.agent, role: message.role || 'execution-record', text: message.text, a2aTaskMarkdown: message.a2aTaskMarkdown, timestamp: new Date().toISOString(),
    } })
    if (index < messages.length - 1) await waitForBaselineSimulation()
  }
}
export async function runOntologyApplication({ input, emit }) {
  const runId = 'RUN-' + Date.now().toString(36).toUpperCase()
  const mode = 'simulation'
  emit({ type: 'run.started', runId, mode, startedAt: new Date().toISOString() })

  const faultClass = classifyFault(input)
  const baselineExploration = runBaselineExploration(emit, faultClass)
  const boundary = inferBoundary(input)

  if (!faultClass.requiresOmc) {
    const closure = {
      conclusion: '确认重复计费由优惠规则未生效引起。',
      nextAction: '后续生成计费冲正单。',
    }
    if (mode === 'simulation') await waitForSimulationRange(900, 1500)
    sendStage(emit, 1, '账单情况核对', '同一账期出现两笔金额相同的费用，先从订购关系、计费周期和优惠执行情况入手核对。', faultClass.focus, { role: 'execution-record' })
    if (mode === 'simulation') await waitForOntologySimulation()
    sendStage(emit, 2, '订购关系核对', '客户名下只有一条有效订购，账期内也没有业务变更，新增业务和跨账期补收可以排除。', faultClass.branchFocus, { role: 'execution-record' })
    if (mode === 'simulation') await waitForOntologySimulation()
    sendStage(emit, 3, '优惠规则核对', '优惠规则未执行，重复金额又与应享优惠金额一致，问题落在计费规则执行环节。', faultClass.decisionFocus, { role: 'execution-record' })
    if (mode === 'simulation') await waitForOntologySimulation()
    sendStage(emit, 4, '处理结论', '账单、订购和优惠记录已经形成完整依据，可直接确认计费原因，无需请求 OMC。' + closure.nextAction, faultClass.closureFocus, { role: 'execution-record' })
    emit({ type: 'run.completed', stage: 4, runId, mode, result: { ...closure, collaborationBoundary: 'solution-layer-closed', omcRequested: false }, completedAt: new Date().toISOString() })
    await baselineExploration
    emit({ type: 'baseline.completed', runId, completedAt: new Date().toISOString() })
    return
  }

  const reasoningViews = reasoningFocuses(faultClass)
  const reasoningText = faultClass.label.includes('设备') ? {
    full: '输入显示网元离线，在 IP网 / 故障管理下识别为已发生故障，并沿“故障识别 → 问题定界定位”关系进入分析，先核对可能导致离线的故障类型。',
    rule: '网元无法连通并伴随设备告警，设备、连接、环境、协议和跨专业方向需要优先排查。',
    evidence: '离线时刻与设备和连接告警一致，范围进一步集中到设备、连接和业务方向。',
    final: '设备告警出现时间与网元离线时间吻合，问题归到设备类故障。',
    gate: '故障类型已经明确，但网元运行状态保存在厂商域，现有信息不足以继续定位，需要查询 OMC。',
    closure: 'OMC 返回主控板异常、供电正常，设备离线最终定位为单板故障。',
  } : faultClass.label.includes('光模块') ? {
    full: 'PON口丢包持续超阈，在 IP网 / 故障管理下识别为已发生故障，并沿“故障识别 → 问题定界定位”关系进入分析，先核对连接与光层故障类型。',
    rule: '端口误码与丢包发生在同一时段，连接、设备、业务和协议方向需要优先排查。',
    evidence: '端口运行状态正常但接收光功率持续偏低，范围集中到连接和业务方向。',
    final: '丢包时段与接收光功率异常吻合，问题归到连接类故障。',
    gate: '故障类型已经明确，但光模块收发光功率保存在厂商域，现有信息不足以继续定位，需要查询 OMC。',
    closure: 'OMC 返回光模块接收光功率异常、端口状态正常，最终定位为光模块故障。',
  } : {
    full: '专线可用率连续下降并伴随持续丢包，在 IP网 / 故障管理下识别为已发生故障，并沿“故障识别 → 问题定界定位”关系进入分析，先核对可能影响专线质量的故障类型。',
    rule: '业务可用率与丢包在同一时段劣化，设备、连接、业务、协议和跨专业方向需要优先排查。',
    evidence: '承载告警与劣化时段吻合，同时未发现设备离线、时钟或环境告警，范围进一步集中到业务、连接和跨专业方向。',
    final: 'SLA 劣化时段与承载异常时间一致，问题归到业务类故障。',
    gate: '故障类型已经明确，但边界承载对象状态保存在厂商域，现有信息不足以继续定位，需要查询 OMC。',
    closure: 'OMC 返回的尾纤异常与业务劣化时段吻合，光模块状态正常，最终定位为尾纤故障。',
  }
  if (mode === 'simulation') await waitForSimulationRange(900, 1500)
  sendStage(emit, 1, '故障识别（Awareness）', reasoningText.full, reasoningViews.full, { role: 'execution-record' })
  if (mode === 'simulation') await waitForOntologySimulation()

  sendStage(emit, 2, '问题定界（Analysis）', reasoningText.rule, reasoningViews.ruleCandidates, { role: 'execution-record' })
  if (mode === 'simulation') await waitForOntologySimulation()

  sendStage(emit, 3, '影响性分析（Analysis）', reasoningText.evidence, reasoningViews.evidenceCandidates, { role: 'execution-record' })
  if (mode === 'simulation') await waitForOntologySimulation()

  sendStage(emit, 4, '问题定位（Analysis）', reasoningText.final, reasoningViews.final, { role: 'execution-record' })
  if (mode === 'simulation') await waitForOntologySimulation()

  sendStage(emit, 5, '定位信息缺口（Analysis）', reasoningText.gate, reasoningViews.gate, { role: 'execution-record' })
  if (mode === 'simulation') await waitForOntologySimulation()

  const a2aTask = buildA2ATask(boundary)
  sendStage(emit, 6, 'A2A-T', '对象=' + boundary.boundaryObject.id + '；字段=' + boundary.boundaryObject.requestedAttributes.join('、') + '。', reasoningViews.request, { role: 'a2a-request', a2aTaskMarkdown: formatA2ATaskMarkdown(a2aTask) })
  emit({ type: 'a2at.request', stage: 6, payload: { boundaryObject: boundary.boundaryObject, capability: boundary.capability, task: a2aTask } })
  if (mode === 'simulation') await waitForOntologySimulation()

  const diagnosis = inferVendor(boundary, input)
  sendStage(emit, 7, 'A2A-T', '对象=' + diagnosis.objectId + '；operState=' + diagnosis.operState + '；faultCause=' + diagnosis.faultCause + '；confidence=' + diagnosis.confidence + '。', reasoningViews.response, { role: 'a2a-response' })
  emit({ type: 'a2at.response', stage: 7, payload: diagnosis })
  if (mode === 'simulation') await waitForOntologySimulation()

  const closure = inferClosure(input, boundary, diagnosis)
  sendStage(emit, 8, '方案生成并决策（Decision）', reasoningText.closure + '依据定位结果生成现场修复方案并完成实施影响评估。' + closure.nextAction, reasoningViews.closure, { role: 'execution-record' })
  emit({ type: 'run.completed', stage: 8, runId, mode, result: { ...closure, diagnosis, collaborationBoundary: 'omc-state-update-required', omcRequested: true }, completedAt: new Date().toISOString() })
  await baselineExploration
  emit({ type: 'baseline.completed', runId, completedAt: new Date().toISOString() })
}
