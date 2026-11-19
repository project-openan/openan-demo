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
// LeftSearch.jsx — 左侧工单搜索框（V5.13 用户规格：搜索框支持点击/输入，实时过滤工单列表）
// 覆盖于设计搜索框（23:137118，画布 24,114 256×32 = 区域本地 24,66 + 左栏区域根 y48）之上：
// 设计边框/放大镜图标保留；设计占位文字已隐藏（buildUiPatches），由输入框原生 placeholder
// 同文案取代（#939393）；输入经 pub.api.setSearch（纯 UI 状态）→ buildUiPatches
// orderVisible（搜索+状态复合过滤）隐藏不匹配工单卡（角标同步隐藏，见 WorkOrderSel）；Esc 清空
import React from 'react';

export default function LeftSearch({ pub }) {
  const ref = React.useRef(null);
  return (
    <div
      className="st-layer st-search"
      style={{ left: 24, top: 114, width: 256, height: 32 }}
      onPointerDown={(e) => {
        if (e.target !== ref.current) {
          e.preventDefault();
          if (ref.current) ref.current.focus();
        }
      }}
      title="搜索工单号、投诉客户、会话意图"
    >
      <input
        ref={ref}
        className="st-search__input"
        value={pub.search || ''}
        onChange={(e) => pub.api.setSearch(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape' && pub.search) pub.api.setSearch('');
        }}
        placeholder="请搜索工单号、投诉客户、会话意图"
        spellCheck={false}
      />
    </div>
  );
}
