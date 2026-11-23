import React, { useMemo } from 'react'

// 树中的节点和边均复用本体关系；根节点仅表示本次问题，不是本体实体。
function faultOperationFlow(problemChildren) {
  return [{
    id: 'TaskFaultAwareness', name: '故障识别(Awareness)', shortName: '故障识别',
    children: [{
      id: 'TaskProblemAnalysis', name: '问题定界定位（含影响性分析）(Analysis)', shortName: '定界定位', relation: '故障流进入定界定位',
      children: [
        ...problemChildren,
        { id: 'TaskSolutionDecision', name: '方案生成并决策(Decision)', shortName: '方案决策', relation: '定界定位支撑方案决策' },
      ],
    }],
  }]
}

const LAYER3_TREES = {
  fiber: {
    id: 'layer3_root',
    name: 'GD-DL-2048 专线可用率下降',
    children: faultOperationFlow([{
      id: 'CatCrossDomain', name: '跨专业故障', relation: '定界定位包含跨专业类',
      children: [{
        id: 'CatConnection', name: '连接类故障', relation: '跨专业状态影响连接',
        children: [{
          id: 'CatService', name: '业务类故障', relation: '连接质量影响业务',
          children: [{
            id: 'TunnelFault', name: '隧道故障', relation: '业务类→隧道故障',
            children: [
              { id: 'FiberFault', name: '光纤/尾纤故障', relation: '隧道→光纤根因' },
              { id: 'OpticalModule', name: '光模块故障', relation: '隧道→光模块根因' },
            ],
          }],
        }],
      }],
    },
    { id: 'CatDevice', name: '设备类故障', relation: '定界定位包含设备类' },
    { id: 'CatProtocol', name: '协议类故障', relation: '定界定位包含协议类' }]),
  },
  device: {
    id: 'layer3_root',
    name: 'PE-GZ-03 网元离线',
    children: faultOperationFlow([{
      id: 'CatDevice', name: '设备类故障', relation: '定界定位包含设备类',
      children: [
        {
          id: 'DeviceOffline', name: '设备离线', relation: '设备类→设备离线',
          children: [
            { id: 'BoardFault', name: '单板/主控板故障', relation: '离线→单板根因' },
            { id: 'PowerFault', name: '供电/掉电故障', relation: '离线→供电根因' },
          ],
        },
        {
          id: 'CatConnection', name: '连接类故障', relation: '设备状态影响连接',
          children: [{ id: 'CatService', name: '业务类故障', relation: '连接质量影响业务' }],
        },
      ],
    },
    { id: 'CatCrossDomain', name: '跨专业故障', relation: '定界定位包含跨专业类' },
    { id: 'CatProtocol', name: '协议类故障', relation: '定界定位包含协议类' }]),
  },
  optical: {
    id: 'layer3_root',
    name: '广州番禺 PON口丢包超阈',
    children: faultOperationFlow([{
      id: 'CatConnection', name: '连接类故障', relation: '定界定位包含连接类',
      children: [
        { id: 'CatService', name: '业务类故障', relation: '连接质量影响业务' },
        { id: 'LinkFault', name: '链路故障', relation: '连接类→链路故障', children: [{ id: 'OpticalModule', name: '光模块故障', relation: '链路→光模块根因' }] },
      ],
    },
    { id: 'CatDevice', name: '设备类故障', relation: '定界定位包含设备类' },
    { id: 'CatProtocol', name: '协议类故障', relation: '定界定位包含协议类' }]),
  },
  billing: {
    id: 'layer3_root',
    name: '专线重复计费争议',
    children: [{
      id: 'CatCrossDomain', name: '跨专业故障',
      children: [{ id: 'CatService', name: '业务类故障', relation: '跨专业信息关联业务' }],
    },
    { id: 'CatDevice', name: '设备类故障' },
    { id: 'CatConnection', name: '连接类故障' },
  ],
  },
}

const EN = {
  'GD-DL-2048 专线可用率下降': 'GD-DL-2048 dedicated-line availability degradation', 'PE-GZ-03 网元离线': 'PE-GZ-03 network element offline', '广州番禺 PON口丢包超阈': 'Guangzhou Panyu PON-port packet-loss threshold breach', '专线重复计费争议': 'Dedicated-line duplicate-billing dispute',
  '故障识别(Awareness)': 'Fault identification (Awareness)', '故障识别': 'Fault Awareness', '问题定界定位（含影响性分析）(Analysis)': 'Problem demarcation and localization (including impact analysis)', '定界定位': 'Localization Analysis', '方案生成并决策(Decision)': 'Solution generation and decision (Decision)', '方案决策': 'Solution Decision',
  '跨专业故障': 'Cross-domain fault', '连接类故障': 'Connection fault', '业务类故障': 'Service fault', '链路故障': 'Link fault', '隧道故障': 'Tunnel fault', '光纤/尾纤故障': 'Fiber-jumper fault', '光模块故障': 'Optical-module fault', '设备类故障': 'Device fault', '协议类故障': 'Protocol fault', '设备离线': 'Device offline', '单板/主控板故障': 'Board/controller fault', '供电/掉电故障': 'Power failure',
  '故障流进入定界定位': 'Fault flow enters problem localization', '定界定位支撑方案决策': 'Localization supports solution decision', '定界定位包含设备类': 'Problem localization includes device faults', '定界定位包含连接类': 'Problem localization includes connection faults', '定界定位包含协议类': 'Problem localization includes protocol faults', '定界定位包含跨专业类': 'Problem localization includes cross-domain faults', '跨专业状态影响连接': 'Cross-domain state affects connections', '连接质量影响业务': 'Connection quality affects services', '连接类→链路故障': 'Connection → link fault', '链路→光模块根因': 'Link → optical-module root cause', '业务类→隧道故障': 'Service → tunnel fault', '隧道→光纤根因': 'Tunnel → fiber root cause', '隧道→光模块根因': 'Tunnel → optical-module root cause', '设备状态影响连接': 'Device state affects connections', '设备类→设备离线': 'Device fault → device offline', '离线→单板根因': 'Offline → board root cause', '离线→供电根因': 'Offline → power root cause', '跨专业信息关联业务': 'Cross-domain information relates to services',
}
function localize(value, language) { return language === 'EN' ? (EN[value] ?? value) : value }

function displayNodeName(name, language = '中', allowLong = false) {
  if (language !== 'EN') {
    const maxLength = allowLong ? 12 : 7
    return name.length > maxLength ? `${name.slice(0, maxLength)}...` : name
  }
  const maxLength = 44
  if (name.length <= maxLength) return name
  const truncated = name.slice(0, maxLength)
  const wordBoundary = truncated.lastIndexOf(' ')
  return `${(wordBoundary > 20 ? truncated.slice(0, wordBoundary) : truncated).trim()}…`
}
function keepReachedBranches(node, reachedNodes) {
  const { children: sourceChildren = [], ...nodeData } = node
  const children = sourceChildren
    .filter((child) => reachedNodes.has(child.id))
    .map((child) => keepReachedBranches(child, reachedNodes))
  return children.length ? { ...nodeData, children } : nodeData
}

function nodeWidth(name, language, allowLong = false) {
  const label = displayNodeName(name, language, allowLong)
  const units = Array.from(label).reduce((total, char) => {
    if (char === '.') return total + 0.35
    if (/[\u0000-\u00ff]/.test(char)) return total + 0.55
    return total + 1
  }, 0)
  if (language === 'EN') return Math.min(allowLong ? 92 : 104, Math.max(76, Math.ceil(units * 3.8 + 18)))
  return Math.min(allowLong ? 82 : 110, Math.max(60, Math.ceil(units * 8 + 18)))
}function computeTreeLayout(rootNode, language) {
  const NODE_HEIGHT = language === 'EN' ? 30 : 28
  const H_GAP = 12
  const V_GAP = language === 'EN' ? 3 : 9
  const nodes = []
  const edges = []
  let leafIndex = 0

  function layoutNode(node, depth = 0, parent = null) {
    const layoutName = localize(node.shortName || node.name, language)
    const nodeItem = { ...node, depth, parent, x: parent ? parent.x + parent.width + H_GAP : 12, y: 0, width: nodeWidth(layoutName, language, Boolean(node.shortName)), height: NODE_HEIGHT }
    if (!node.children || node.children.length === 0) {
      nodeItem.y = leafIndex * (NODE_HEIGHT + V_GAP) + 8
      leafIndex += 1
    } else {
      const childItems = node.children.map((child) => layoutNode(child, depth + 1, nodeItem))
      nodeItem.y = (childItems[0].y + childItems[childItems.length - 1].y) / 2
      nodeItem.children = childItems
    }
    nodes.push(nodeItem)
    return nodeItem
  }

  const finalRoot = layoutNode(rootNode)
  function collectEdges(node) {
    if (node.children?.length) node.children.forEach((child) => {
      edges.push({
        id: `${node.id}->${child.id}`,
        relation: child.relation || null,
        fromId: node.id,
        toId: child.id,
        fromX: node.x + node.width,
        fromY: node.y + NODE_HEIGHT / 2,
        toX: child.x,
        toY: child.y + NODE_HEIGHT / 2,
      })
      collectEdges(child)
    })
  }
  collectEdges(finalRoot)
  const maxX = Math.max(...nodes.map((n) => n.x + n.width)) + 16
  const maxY = Math.max(...nodes.map((n) => n.y)) + NODE_HEIGHT + 10
  return { nodes, edges, width: Math.max(maxX, 560), height: Math.max(maxY, 112) }
}

export default function ReasoningTree({ focusHistory = [], result, theme, hasExecution, input = '', language = '中' }) {
  const isLight = theme === 'light'
  const text = `${input || ''} ${result?.diagnosis?.problem || ''}`
  const isBilling = result?.collaborationBoundary === 'solution-layer-closed'
    || /计费|账单|扣费|优惠|发票|收费/.test(text)
    || focusHistory.some((focus) => /账单|订购|优惠|计费/.test(`${focus.actor || ''}${focus.label || ''}`))
  const isDevice = result?.diagnosis?.faultCause === '单板故障'
    || /设备|网元|单板|离线|掉电|电源/.test(text)
    || focusHistory.some((focus) => focus.nodes?.includes('BoardFault') || focus.nodes?.includes('DeviceOffline'))
  const isOptical = /PON|光模块/.test(text)
    || focusHistory.some((focus) => focus.nodes?.includes('OpticalModule') && !focus.nodes?.includes('FiberFault'))
  const presetKey = isBilling ? 'billing' : (isDevice ? 'device' : (isOptical ? 'optical' : 'fiber'))

  const latestFocus = focusHistory.length > 0 ? focusHistory[focusHistory.length - 1] : null
  const reachedNodes = useMemo(() => new Set([
    ...focusHistory.flatMap((focus) => focus.nodes || []),
  ]), [focusHistory])
  const rawTree = useMemo(() => {
    const treeTemplate = LAYER3_TREES[presetKey]
    const problemTitle = result?.diagnosis?.problem || input?.trim() || treeTemplate.name
    return keepReachedBranches({ ...treeTemplate, name: problemTitle }, reachedNodes)
  }, [presetKey, result, input, reachedNodes])
  const layout = useMemo(() => computeTreeLayout(rawTree, language), [language, rawTree])
  const activeNodesSet = new Set(latestFocus?.nodes || [])
  const categoryRelations = { CatDevice: '定界定位包含设备类', CatConnection: '定界定位包含连接类', CatProtocol: '定界定位包含协议类', CatCrossDomain: '定界定位包含跨专业类' }
  const activeLinksSet = new Set([...(latestFocus?.links || []), ...[...activeNodesSet].map((id) => categoryRelations[id]).filter(Boolean)])

  if (!hasExecution || !focusHistory?.length) {
    return <div className={`nary-tree-wrapper compact-aux ${isLight ? 'light-theme' : ''}`}></div>
  }

  return (
    <div className={`nary-tree-wrapper compact-aux ${isLight ? 'light-theme' : ''} ${language === 'EN' ? 'nary-tree-en' : ''}`}>

      <div className="nary-responsive-stage compact-stage">
        <svg className="nary-auto-fit-svg" viewBox={`0 0 ${layout.width} ${layout.height}`} width={layout.width} height={layout.height}>
          {layout.edges.map((edge) => {
            const isActive = edge.relation ? activeLinksSet.has(edge.relation) : activeNodesSet.has(edge.toId)
            const midX = (edge.fromX + edge.toX) / 2
            const d = `M ${edge.fromX} ${edge.fromY} C ${midX} ${edge.fromY}, ${midX} ${edge.toY}, ${edge.toX} ${edge.toY}`
            const strokeColor = isActive ? (isLight ? '#64748b' : '#cbd5e1') : (isLight ? '#cbd5e1' : '#334155')
            return <path key={edge.id} d={d} fill="none" stroke={strokeColor} strokeWidth={isActive ? 1.4 : 0.9} strokeDasharray={isActive ? 'none' : '2.5 2.5'} strokeOpacity={isActive ? 0.6 : 0.2} style={{ transition: 'all 0.3s ease' }} />
          })}
          {layout.nodes.map((node) => {
            const isActive = node.id === 'layer3_root' || activeNodesSet.has(node.id)
            const displayName = localize(node.shortName || node.name, language)
            return <foreignObject key={node.id} x={node.x} y={node.y} width={node.width} height={node.height}><div style={{ width: node.width, height: node.height }} className={`nary-node-card compact-card ${isActive ? 'node-bright' : 'node-dimmed'}`}><span className={`nary-card-dot ${isActive ? 'dot-bright' : 'dot-dimmed'}`} /><span className="nary-card-title" title={localize(node.name, language)}>{displayNodeName(displayName, language, Boolean(node.shortName))}</span></div></foreignObject>
          })}
        </svg>
      </div>
    </div>
  )
}
