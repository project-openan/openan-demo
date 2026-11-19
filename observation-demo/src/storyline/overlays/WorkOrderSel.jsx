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
// WorkOrderSel.jsx — 工单卡对号角标（选中卡）
// V2.7：整卡点击切换案例由 LayerView interactions 直接挂接在设计 DOM 卡片容器上（无覆盖按钮），
// 卡内文字（工单号/客户/描述）可正常选中复制；拖拽选字不触发切换（见 StorylineContext interactions）
// V2.29：角标改用设计切图 ic_selected.svg（32×32 蓝角标+白对勾，与设计稿静态选中样式同源）
// V5.2（用户规格 2026-10-12）：角标随选中卡——**未选中的工单卡无角标，选中后出现角标**；
// 选中态 = 蓝框边框（buildPatches sel/uns）+ 对号角标 + 回放中胶囊
import React from 'react';
import { ORDERS, ORDER_SLOT, orderVisible } from '../roles';

export default function WorkOrderSel({ pub }) {
  const cb = ORDERS.checkBox;
  const relX = cb.x - ORDERS.c1.box.x;
  const relY = cb.y - ORDERS.c1.box.y;
  const k = pub.caseId === 'c2' ? 'c2' : 'c1';
  // V5.13：搜索/状态过滤中选中卡被隐藏时角标同步隐藏（与工单卡同一 orderVisible 口径）
  if (!orderVisible(k, pub)) return null;
  const b = ORDERS[ORDER_SLOT[k]].box; // V5.23：角标随对调后槽位
  return (
    <div className="st-layer st-orders">
      <div className="st-check" style={{ left: b.x + relX, top: b.y + relY }}>
        <img src="/icons/ic_selected.svg" alt="" draggable={false} />
      </div>
    </div>
  );
}
