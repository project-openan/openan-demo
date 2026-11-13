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
import ScreenCanvas from './components/ScreenCanvas';
import { StorylineProvider } from './storyline/StorylineContext';
import StorylineOverlays from './storyline/overlays/StorylineOverlays';
import BackgroundRegion from './components/regions/BackgroundRegion';
import FlowChartRegion from './components/regions/FlowChartRegion';
import LeftPanelRegion from './components/regions/LeftPanelRegion';
import LogPanelRegion from './components/regions/LogPanelRegion';
import TitleRegion from './components/regions/TitleRegion';
import TopNavRegion from './components/regions/TopNavRegion';

export default function App() {
  // V2.14：Provider 移到 ScreenCanvas 外（画布需读取 pub.vscale 做整页铺满变换），
  // 覆盖层与各区域同在画布内（画布坐标系渲染）
  return (
    <StorylineProvider>
      <ScreenCanvas>
        <BackgroundRegion />
        <FlowChartRegion />
        <TitleRegion />
        <LeftPanelRegion />
        <LogPanelRegion />
        <TopNavRegion />
        <StorylineOverlays />
      </ScreenCanvas>
    </StorylineProvider>
  );
}
