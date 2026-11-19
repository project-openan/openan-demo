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
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';

// V5.30 rem 缩放：react jsx 运行时别名到包装器——全部组件内联 style 的 px→rem 中央换算
// （含 LayerView 合并的设计 JSON/roles 补丁样式；见 src/remjsx/）。字符串 find 为精确匹配
// （'react/jsx-runtime.js' 子路径不受影响），包装器内部经 react/cjs 引真实运行时避免成环。
export default defineConfig({
  base: './',
  plugins: [react(), viteSingleFile()],
  resolve: {
    alias: [
      { find: 'react/jsx-runtime', replacement: fileURLToPath(new URL('./src/remjsx/jsx-runtime.js', import.meta.url)) },
      { find: 'react/jsx-dev-runtime', replacement: fileURLToPath(new URL('./src/remjsx/jsx-dev-runtime.js', import.meta.url)) },
    ],
  },
});
