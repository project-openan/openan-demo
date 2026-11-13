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
// OrderFilter.jsx — 左侧工单状态筛选（V5.13 用户规格：根据状态筛选工单）
// 设计「筛选」区（工单列表标题右侧，画布 206,74.91 74×20 = 区域本地 +左栏根 y48）：
// 标签文字（I23:137104;3:27462;2:29596）随所选状态补丁更新、下拉箭头切图保留；
// 点击展开下拉（全部状态/处理中/已完成，样式随 .st-speedmenu 系），选项点击即筛选
//（pub.api.setStatus 纯 UI 状态 → buildUiPatches orderVisible 卡片过滤）；
// 搜索+状态复合过滤后无可见工单时，列表区呈现「暂无匹配工单」空态提示
import React from 'react';
import { ORDER_STATUS_OPTIONS, orderVisible } from '../roles';

export default function OrderFilter({ pub }) {
  const [open, setOpen] = React.useState(false);
  const cur = ORDER_STATUS_OPTIONS.includes(pub.status) ? pub.status : '全部状态';
  const noneVisible = !orderVisible('c1', pub) && !orderVisible('c2', pub);
  return (
    <>
      <div
        className="st-layer st-ofilter"
        style={{ left: 202, top: 73, width: 82, height: 24 }}
        title="按状态筛选工单"
        onClick={() => setOpen((o) => !o)}
      />
      {open ? (
        <>
          <div className="st-ofilter-backdrop" onClick={() => setOpen(false)} />
          <div className="st-ofilter-menu" style={{ left: 202, top: 99 }}>
            {ORDER_STATUS_OPTIONS.map((s) => (
              <div
                key={s}
                className={'st-speeditem' + (s === cur ? ' st-speeditem-cur' : '')}
                onClick={() => { setOpen(false); if (s !== cur) pub.api.setStatus(s); }}
              >
                {s}
              </div>
            ))}
          </div>
        </>
      ) : null}
      {noneVisible ? (
        <div className="st-layer st-oempty" style={{ left: 24, top: 218, width: 256, height: 22 }}>
          暂无匹配工单
        </div>
      ) : null}
    </>
  );
}
