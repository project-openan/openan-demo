// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0
//
//    Licensed under the Apache License, Version 2.0 (the "License"); you may
//    not use this file except in compliance with the License. You may obtain
//    a copy of the License at
//
//         http://www.apache.org/licenses/LICENSE-2.0
//
//    Unless required by applicable law or agreed to in writing, software
//    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
//    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
//    License for the specific language governing permissions and limitations
//    under the License.
// LogHeader.jsx — V6.0 流式布局：协作日志面板头（标题 + 实时计数）
// 设计标题/计数文字节点（LOGS.titleTextId/countTextId）隐藏，本组件以横向 flex 重建
//（左标题右计数）；表体沿用 LogTable（本为流式滚动表）；左栏收起时随面板同步左向拉伸
//（logFitStyle，右缘 1920 锚定——与 LogTable 同口径）。
import React from 'react';
import { LOGS, logStretchX } from '../roles';
import { CASES } from '../cases';
import './flow.css';

export default function LogHeader({ pub }) {
  if (pub.logHidden) return null;
  const n = pub.world ? pub.world.logs.length : CASES[pub.caseId].logs.length;
  // 左栏收起：left/width 真实重排（与 LogTable 同口径，文字保持原尺寸不缩放拉伸）
  const left = logStretchX(pub, LOGS.panelBox.x + 16);
  const width = logStretchX(pub, 1904) - left; // 右缘与设计计数文字右缘一致（x1904）
  return (
    <div className="fl-loghead" style={{ left, top: 910, width, height: 26 }}>
      <div className="fl-loghead__title">A2A-T协作日志</div>
      <div className="fl-loghead__count">{n}条</div>
    </div>
  );
}
