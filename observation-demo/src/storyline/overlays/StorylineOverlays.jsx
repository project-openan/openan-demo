// StorylineOverlays.jsx — 覆盖层总装
// 快照态（默认加载）：仅渲染透明交互层（回放工具栏/工单卡/缩放按钮/日志传感器），画面与设计稿逐像素一致
// （例外为用户要求的有意偏差：房间白色高亮底默认隐藏、第二条日志改文字、占位文案粤东/粤西化）
// 回放态：流程覆盖层（连线/圆点/描述）随画布缩放变换；日志表接管静态行
import React, { useContext } from 'react';
import { StoryContext } from '../StorylineContext';
import { CASES } from '../cases';
import { LOGS, ROOMS, overlayFitStyle, overlayZoomStyle, logFitStyle, totalFactors } from '../roles';
import ConnectionFlow from './ConnectionFlow';
import ConnectionLines, { snapshotLinesWorld } from './ConnectionLines';
import MiniCircles from './MiniCircles';
import StepDesc from './StepDesc';
import NegotiationPanel from './NegotiationPanel';
import SubStepPanels from './SubStepPanels';
import LogTable from './LogTable';
import Toolbar from './Toolbar';
import WorkOrderSel from './WorkOrderSel';
import LeftSearch from './LeftSearch';
import OrderFilter from './OrderFilter';
import ZoomToolbar from './ZoomToolbar';
import PanelHandles from './PanelHandles';

// 组间连线滑块动效：渐变短条沿线从左端滑到右端、首尾淡入淡出
// 关键帧由导出的连线/滑块几何生成（roles-data.js ROOMS.glides）；
// V5.12（用户规格）：行程收窄至连线两端以内（滑块不再越至矩形胶囊上）；
// V5.30 rem 缩放：translateX 改 rem（<style> 文本不经 remjsx 包装器，手工换算）；
// V5.37（用户规格）：光点只移动一次然后消失——animation 单次播放（1 forwards，一遍后
// 定格于终点透明态、由窗口隐藏兜底移除）；原 infinite 在窗口实长略超行程周期时可见
// 第二次起跑闪光（1x 下 g2 超 0.19s 最明显），废止；
// V5.54→V5.57（用户规格）：g1（监控室—传输室）随 CS_LINK 按案缩短（c1 251.92 / c2 473.21，
// 世界 820.58 起）——行程 = (线宽−80)/2（c1 ±85.96 / c2 ±196.61）、等速 74.9px/s
//（c1 2.3s / c2 5.25s），由本组件按 caseId 传入 lim/dur 生成 keyframes；
// V5.56/V5.57：两案监控室均单枚——传输室—监控室 roomline 登场光点 g2 全程滑
//（行程 = (roomline宽−80)/2，V5.54 硬编码 ±1.9rem/中点起废止——V5.56 曾置线中点错位）
const GLIDE_LIM = [89.97];
const glideCss = (g1Lim, g1Dur, g2Half, g2Dur) => {
  let css = ROOMS.glides.map((g, i) => {
    const lim = i === 1 ? g1Lim : (GLIDE_LIM[i] != null ? GLIDE_LIM[i] : Math.max(Math.abs(g.from), Math.abs(g.to)));
    const from = -Math.min(Math.abs(g.from), lim);
    const to = Math.min(g.to, lim);
    const dur = i === 1 ? g1Dur : g.dur;
    return '.st-glide' + i + '{animation:stGlide' + i + ' ' + dur + 's linear 1 forwards}' +
      '@keyframes stGlide' + i + '{' +
        '0%{transform:translateX(' + from / 16 + 'rem);opacity:0}' +
        '15%{opacity:.8}' +
        '85%{opacity:.8}' +
        '100%{transform:translateX(' + to / 16 + 'rem);opacity:0}' +
      '}';
  }).join('');
  css += '.st-glide2{animation:stGlide2 ' + g2Dur + 's linear 1 forwards}' +
    '@keyframes stGlide2{' +
      '0%{transform:translateX(' + (-g2Half / 16) + 'rem);opacity:0}' +
      '15%{opacity:.8}' +
      '85%{opacity:.8}' +
      '100%{transform:translateX(' + (g2Half / 16) + 'rem);opacity:0}' +
    '}';
  return css;
};

function LogSensor({ onActivate, fit }) {
  const b = LOGS.panelBox;
  // 顶部让出 14px 把手带（设计把手可点收起，V2.12），其余区域滚轮/点击点亮日志
  return (
    <div
      className="st-logsensor"
      style={{ left: b.x, top: b.y + 14, width: b.w, height: b.h - 14, ...fit }}
      onWheel={onActivate}
      onPointerDown={onActivate}
      title="A2A-T协作日志"
    />
  );
}

export default function StorylineOverlays() {
  const pub = useContext(StoryContext);
  if (!pub) return null;
  const live = !!pub.world;
  const logs = !pub.logHidden && live ? pub.world.logs : (!pub.logHidden && pub.logLive ? CASES[pub.caseId].logs : null);
  const zoomStyle = overlayFitStyle(pub);
  // V2.21：内层 .st-zoomz = 用户缩放 Z（绕画布中心、瞬时）——与 .fc-zoom 区域内容同步，
  // 外层 .st-zoomwrap 仍为区域重适配 F（收起/展开 0.25s 过渡），等效 CTM = F∘Z
  const zoomZ = overlayZoomStyle(pub);
  // 左栏收起时日志面板内容（实时表/传感器）随面板同步左向拉伸
  const lgFit = logFitStyle(pub, LOGS.bodyBox.x);
  // V2.13/V2.14：快照+收起/非 16:9 视口——设计连线 sprite 已隐藏（位图无法随集群端点重适配），改由 SVG 全量呈现
  const TF = totalFactors(pub);
  const lineWorld = live ? pub.world : ((TF.fx !== 1 || TF.fy !== 1) ? snapshotLinesWorld() : null);
  // V5.54→V5.56（用户规格）：房间条按步骤揭示且两案各自分区——
  //   c1：传输室=根因定位（胶囊对齐根因定位步骤）；监控室=问题处置+修复验证+投诉报结
  //       （单枚胶囊对齐修复验证，随问题处置步骤揭示）
  //   c2：传输室=根因定位+问题处置+修复验证（胶囊对齐问题处置）；监控室=投诉报结
  //       （胶囊对齐投诉报结，随投诉报结步骤揭示）
  // 传输室胶囊随根因定位步骤揭示（V5.56 起步骤3 与 Task-T 面板同拍 t=144）
  const stepOn = (i) => !live || pub.world.steps[i] !== 'todo';
  // V5.56：房间条几何（按 caseId 分支；胶囊宽 80+左右边框 2，left=目标步骤中心-40）
  const isC1 = pub.caseId === 'c1';
  const pillA = isC1 ? 1072.5 : 1293.79;   // 传输室胶囊（根因定位中心 1112.5 / 问题处置中心 1333.79）
  const pillB = isC1 ? 1514.6 : 1736.36;   // 监控室胶囊（修复验证中心 1554.6 / 投诉报结中心 1776.36）
  const sepB = isC1 ? 1223.14 : 1666.76;   // 传输室|监控室 竖线（根因|处置界 / 验证|报结界）
  const stepB = isC1 ? 4 : 6;              // 监控室段起始步骤（胶囊/竖线/虚线/光点揭示拍）
  // V5.57：roomline 自胶囊右边框外起（胶囊 80+2 边框——原 1152.5 起穿入右 border）
  const lineL = pillA + 82, lineW = pillB - lineL;
  // V5.56/V5.57：传输室—监控室连线登场光点 g2（一次），随监控室段起始步骤；
  // 全程滑（left=线左端+行程，行程=(线宽−80)/2，等速 38.7px/s——V5.54 g2 惯例速度）
  const g2Half = (lineW - 80) / 2;
  const g2Dur = (lineW - 80) / 38.7;
  const g1Half = isC1 ? 85.96 : 196.61;    // g1 随 CS_LINK 按案（roles.js 同值）
  const g1Dur = isC1 ? 2.3 : 5.25;
  // 原第二枚监控室胶囊/roomline/g3 光点废止（两案监控室均为单枚）
  const TB = CASES[pub.caseId].boundaries[stepB - 1];
  const glideWin = Math.ceil(g2Dur * 4 * (pub.speed || 1));
  const g2on = live && stepOn(stepB) && pub.t >= TB && pub.t < TB + glideWin;
  return (
    <>
      <style>{glideCss(g1Half, g1Dur, g2Half, g2Dur)}</style>
      <div className="st-zoomwrap" style={zoomStyle}>
        <div className="st-zoomz" style={zoomZ}>
          {/* V5.33/V5.56：房间条竖线分隔——客服|监控室 558.8（恒显）、监控室|传输室 999.39
              （随步骤3）、传输室|监控室（c1 根因|处置界 1223.14 / c2 验证|报结界 1666.76，
              随监控室段起始步骤） */}
          <div className="st-roomsep" style={{ left: 558.8 }} />
          {stepOn(3) ? <div className="st-roomsep" style={{ left: 999.39 }} /> : null}
          {stepOn(stepB) ? <div className="st-roomsep" style={{ left: sepB }} /> : null}
          {/* V5.34/V5.56（用户规格）：两枚覆盖层胶囊（设计 23:135680 两案均隐藏）——
              传输室/监控室 各一枚，位置按两案分区（见上 V5.56 注释）；
              传输室随步骤3（V5.56 与 Task-T 面板同拍 144）、监控室随其段起始步骤揭示 */}
          {stepOn(3) ? <div className="st-roompill" style={{ left: pillA }}>传输室</div> : null}
          {stepOn(stepB) ? <div className="st-roompill" style={{ left: pillB }}>监控室</div> : null}
          {/* 胶囊间虚线（连接相邻胶囊边沿）随监控室胶囊同拍出现 */}
          {stepOn(stepB) ? <div className="st-roomline" style={{ left: lineL, width: lineW }} /> : null}
          {/* V5.35/V5.56/V5.57：传输室—监控室连线登场光点一次（g2，全程滑：
              left=线左端+行程、±行程/38.7px/s；暂停/seek 静止呈现，窗口外隐藏；
              监控室—传输室 g1 见 roles.js 滑块窗口；原监控室—监控室 g3 废止 */}
          {g2on ? (
            <div className={'st-glidebar' + (pub.mode === 'playing' ? ' st-glide2' : '')} style={{ left: lineL + g2Half }} />
          ) : null}
          {lineWorld ? <ConnectionLines world={lineWorld} pub={pub} /> : null}
          {live ? (
            <>
              <ConnectionFlow world={pub.world} pub={pub} />
              <StepDesc world={pub.world} pub={pub} />
              <NegotiationPanel world={pub.world} pub={pub} />
            </>
          ) : null}
          <MiniCircles world={pub.world} pub={pub} />
          <SubStepPanels world={pub.world} pub={pub} />
        </div>
      </div>
      <Toolbar pub={pub} />
      <ZoomToolbar pub={pub} />
      {!logs ? null : <LogTable logs={logs} anchor={live ? 'bottom' : 'top'} pub={pub} />}
      {pub.logHidden || live || pub.logLive ? null : <LogSensor onActivate={pub.api.activateLog} fit={lgFit} />}
      {pub.ordersHidden ? null : <WorkOrderSel pub={pub} />}
      {/* V5.13（用户规格）：左侧搜索框 + 状态筛选（面板收起时随面板隐藏）——输入/选择实时过滤工单列表 */}
      {pub.ordersHidden ? null : <LeftSearch pub={pub} />}
      {pub.ordersHidden ? null : <OrderFilter pub={pub} />}
      <PanelHandles pub={pub} />
    </>
  );
}
