import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..')
const indexPath = join(root, 'public', 'ontology', 'index.html')
const ttlPath = join(root, 'public', 'ontology', 'downloads', 'ip-network-fault-management.ttl')
const owlPath = join(root, 'public', 'ontology', 'downloads', 'ip-network-fault-management.owl')

const LAYERS = {
  business: { concept: 'BusinessOperationConcept', conceptZh: '业务运营层概念', layer: 'BusinessOperationLayer', zh: '业务运营层', comment: 'Layer 1: business operation' },
  governance: { concept: 'GovernanceConcept', conceptZh: '全局治理与主权层概念', layer: 'GovernanceLayer', zh: '全局治理与主权层', comment: 'Layer 2: governance and sovereignty' },
  cross_system: { concept: 'CrossSystemConcept', conceptZh: '跨系统解决方案层概念', layer: 'CrossSystemLayer', zh: '跨系统解决方案层', comment: 'Layer 3: IP-network solution and I-AADE autonomous loop' },
  logical: { concept: 'LogicalResourceConcept', conceptZh: '逻辑资源层概念', layer: 'LogicalResourceLayer', zh: '逻辑资源层', comment: 'Layer 4: logical resources' },
  physical: { concept: 'PhysicalResourceConcept', conceptZh: '物理资源层概念', layer: 'PhysicalResourceLayer', zh: '物理资源层', comment: 'Layer 5: physical resources' },
}
const LAYER_ORDER = ['business', 'governance', 'cross_system', 'logical', 'physical']

const CATS = {
  structural: { cls: 'StructuralRelation', zh: '结构关系' },
  reasoning: { cls: 'ReasoningRelation', zh: '推理关系' },
  evidence: { cls: 'EvidenceRelation', zh: '证据关系' },
  diagnosis: { cls: 'DiagnosisRelation', zh: '诊断关系' },
}
const CAT_ORDER = ['structural', 'reasoning', 'evidence', 'diagnosis']

const BASE = 'https://open-an.example/ontology/ip-network-fault-management'
const NS = BASE + '#'

const html = readFileSync(indexPath, 'utf8')

function extractBlock(name) {
  const re = new RegExp(`const\\s+${name}\\s*=\\s*\\[([\\s\\S]*?)\\];`)
  const match = html.match(re)
  if (!match) throw new Error(`${name} block not found`)
  return match[1]
}

const nodesBlock = extractBlock('NODES')
const linksBlock = extractBlock('LINKS')

const nodes = []
const nodeRe = /id:\s*"([^"]+)"[\s\S]*?zh:\s*"([^"]+)"[\s\S]*?layer:\s*"([^"]+)"/g
let m
while ((m = nodeRe.exec(nodesBlock))) {
  if (!LAYERS[m[3]]) throw new Error(`unknown layer "${m[3]}" for node ${m[1]}`)
  nodes.push({ id: m[1], zh: m[2], layer: m[3] })
}

const links = []
const linkRe = /name:\s*"([^"]+)"[\s\S]*?from:\s*"([^"]+)"[\s\S]*?to:\s*"([^"]+)"[\s\S]*?cat:\s*"([^"]+)"/g
while ((m = linkRe.exec(linksBlock))) {
  if (!CATS[m[4]]) throw new Error(`unknown cat "${m[4]}" for link ${m[1]}`)
  links.push({ name: m[1], from: m[2], to: m[3], cat: m[4] })
}

const nodeIds = new Set(nodes.map((n) => n.id))
for (const link of links) {
  if (!nodeIds.has(link.from)) throw new Error(`link "${link.name}": from "${link.from}" not in NODES`)
  if (!nodeIds.has(link.to)) throw new Error(`link "${link.name}": to "${link.to}" not in NODES`)
}

function escXml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function rid(i) {
  return 'r' + String(i).padStart(2, '0')
}

// ---- TTL ----
const ttl = []
ttl.push(`@prefix an: <${NS}> .`)
ttl.push('@prefix owl: <http://www.w3.org/2002/07/owl#> .')
ttl.push('@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .')
ttl.push('')
ttl.push(`<${BASE}> a owl:Ontology ;`)
ttl.push('  rdfs:label "IP网五层故障管理本体"@zh , "IP network five-layer fault-management ontology"@en ;')
ttl.push('  rdfs:comment "完整导出业务运营、全局治理与主权、跨系统解决方案、逻辑资源、物理资源五层本体，以及 I-AADE 自治闭环和诊断关系；可离线导入 Agent。每条关系保留独立名称与单一 source/target，与演示页面 index.html 的 NODES/LINKS 一一对应。"@zh ; owl:versionInfo "1.0.0" .')
ttl.push('')
ttl.push('an:OntologyConcept a owl:Class .')
for (const key of LAYER_ORDER) {
  const L = LAYERS[key]
  ttl.push(`an:${L.concept} a owl:Class ; rdfs:subClassOf an:OntologyConcept ; rdfs:label "${L.conceptZh}"@zh .`)
}
ttl.push('an:OntologyRelation a owl:Class .')
for (const key of CAT_ORDER) {
  ttl.push(`an:${CATS[key].cls} a owl:Class ; rdfs:subClassOf an:OntologyRelation .`)
}
ttl.push('an:inLayer a owl:ObjectProperty . an:hasSource a owl:ObjectProperty . an:hasTarget a owl:ObjectProperty .')
ttl.push('')
for (const key of LAYER_ORDER) {
  const L = LAYERS[key]
  ttl.push(`an:${L.layer} rdfs:label "${L.zh}"@zh .`)
}
ttl.push('')
for (const key of LAYER_ORDER) {
  const L = LAYERS[key]
  ttl.push(`# ${L.comment}`)
  for (const n of nodes.filter((n) => n.layer === key)) {
    ttl.push(`an:${n.id} a an:${L.concept} ; an:inLayer an:${L.layer} ; rdfs:label "${n.zh}"@zh .`)
  }
  ttl.push('')
}
let idx = 0
for (const key of CAT_ORDER) {
  const C = CATS[key]
  const catLinks = links.filter((l) => l.cat === key)
  ttl.push(`# ${C.zh}（${catLinks.length}）`)
  for (const l of catLinks) {
    idx += 1
    ttl.push(`an:${rid(idx)} a an:${C.cls} ; rdfs:label "${l.name}"@zh ; an:hasSource an:${l.from} ; an:hasTarget an:${l.to} .`)
  }
  ttl.push('')
}
writeFileSync(ttlPath, ttl.join('\n'), 'utf8')

// ---- OWL ----
const owl = []
owl.push('<?xml version="1.0" encoding="UTF-8"?>')
owl.push(`<rdf:RDF xmlns:an="${NS}" xmlns:owl="http://www.w3.org/2002/07/owl#" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">`)
owl.push(`  <owl:Ontology rdf:about="${BASE}"><rdfs:label xml:lang="zh">IP网五层故障管理本体</rdfs:label><rdfs:label xml:lang="en">IP network five-layer fault-management ontology</rdfs:label><rdfs:comment xml:lang="zh">完整五层本体的 RDF/XML（OWL）序列化，包含 I-AADE 自治闭环与诊断关系。每条关系保留独立名称与单一 source/target，与演示页面 index.html 的 NODES/LINKS 一一对应，可离线导入 Agent。</rdfs:comment><owl:versionInfo>1.0.0</owl:versionInfo></owl:Ontology>`)
owl.push('  <!-- classes -->')
const classParts = [`<owl:Class rdf:about="${NS}OntologyConcept"/>`]
for (const key of LAYER_ORDER) {
  classParts.push(`<owl:Class rdf:about="${NS}${LAYERS[key].concept}"><rdfs:subClassOf rdf:resource="${NS}OntologyConcept"/></owl:Class>`)
}
classParts.push(`<owl:Class rdf:about="${NS}OntologyRelation"/>`)
for (const key of CAT_ORDER) {
  classParts.push(`<owl:Class rdf:about="${NS}${CATS[key].cls}"><rdfs:subClassOf rdf:resource="${NS}OntologyRelation"/></owl:Class>`)
}
owl.push('  ' + classParts.join(''))
owl.push(`  <owl:ObjectProperty rdf:about="${NS}inLayer"/><owl:ObjectProperty rdf:about="${NS}hasSource"/><owl:ObjectProperty rdf:about="${NS}hasTarget"/>`)
owl.push('  <!-- layer individuals -->')
const layerParts = []
for (const key of LAYER_ORDER) {
  const L = LAYERS[key]
  layerParts.push(`<rdf:Description rdf:about="${NS}${L.layer}"><rdfs:label xml:lang="zh">${escXml(L.zh)}</rdfs:label></rdf:Description>`)
}
owl.push('  ' + layerParts.join(''))
for (const key of LAYER_ORDER) {
  const L = LAYERS[key]
  owl.push(`  <!-- ${L.comment} -->`)
  const parts = []
  for (const n of nodes.filter((n) => n.layer === key)) {
    parts.push(`<an:${L.concept} rdf:about="${NS}${n.id}"><an:inLayer rdf:resource="${NS}${L.layer}"/><rdfs:label xml:lang="zh">${escXml(n.zh)}</rdfs:label></an:${L.concept}>`)
  }
  owl.push('  ' + parts.join(''))
}
idx = 0
for (const key of CAT_ORDER) {
  const C = CATS[key]
  const catLinks = links.filter((l) => l.cat === key)
  owl.push(`  <!-- ${C.zh}（${catLinks.length}） -->`)
  const parts = []
  for (const l of catLinks) {
    idx += 1
    parts.push(`<an:${C.cls} rdf:about="${NS}${rid(idx)}"><rdfs:label xml:lang="zh">${escXml(l.name)}</rdfs:label><an:hasSource rdf:resource="${NS}${l.from}"/><an:hasTarget rdf:resource="${NS}${l.to}"/></an:${C.cls}>`)
  }
  owl.push('  ' + parts.join(''))
}
owl.push('</rdf:RDF>')
writeFileSync(owlPath, owl.join('\n'), 'utf8')

console.log(`nodes: ${nodes.length}, links: ${links.length}`)
for (const key of CAT_ORDER) {
  const n = links.filter((l) => l.cat === key).length
  console.log(`  ${CATS[key].cls}: ${n}`)
}
console.log(`ttl -> ${ttlPath}`)
console.log(`owl -> ${owlPath}`)
