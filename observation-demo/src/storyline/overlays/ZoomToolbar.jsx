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
// ZoomToolbar.jsx — 画布缩放工具条透明点击层（适应/＋/－；百分比文字由 uiPatches 更新设计节点）
import React from 'react';
import { ZOOM } from '../roles';
import { ZOOM_MIN, ZOOM_MAX } from '../StorylineContext';

const boxStyle = (b) => ({ left: b.x, top: b.y, width: b.w, height: b.h });
// V5.28（用户规格）：＋/－图标 CSS 重建（设计版隐藏，见 roles.js）——图标样式
// background:#FFFFFF、border:0.05rem(1px) solid #FFFFFF；放大按钮为＋号。
// 按钮卡片样式（border-radius 0.2rem(4px)、#F3F3F319 底、投影 0 0.05rem 0.3rem 0 #0000007F）
// 由设计节点 23:135645 工具条卡提供；V5.12 放大槽单独叠加层废止（与工具条卡双重叠底）
const GLYPH_BAR = {
  position: 'absolute',
  background: '#FFFFFF',
  border: '1px solid #FFFFFF',
  pointerEvents: 'none',
};
const glyphBox = (b) => ({ position: 'absolute', left: b.x + 9, top: b.y + 5, width: 14, height: 14, pointerEvents: 'none' });

export default function ZoomToolbar({ pub }) {
  const { api, zoom } = pub;
  return (
    <div className="st-layer st-zoombar">
      <div style={glyphBox(ZOOM.plusBox)}>
        <div style={{ ...GLYPH_BAR, left: 1, top: 6, width: 12, height: 2 }} />
        <div style={{ ...GLYPH_BAR, left: 6, top: 1, width: 2, height: 12 }} />
      </div>
      <div style={glyphBox(ZOOM.minusBox)}>
        <div style={{ ...GLYPH_BAR, left: 1, top: 6, width: 12, height: 2 }} />
      </div>
      <button style={boxStyle(ZOOM.fitBox)} onClick={api.zoomFit} title="适应画布" aria-label="适应画布" />
      <button style={boxStyle(ZOOM.plusBox)} onClick={api.zoomIn} title="放大" aria-label="放大" disabled={zoom >= ZOOM_MAX} />
      <button style={boxStyle(ZOOM.minusBox)} onClick={api.zoomOut} title="缩小" aria-label="缩小" disabled={zoom <= ZOOM_MIN} />
    </div>
  );
}
