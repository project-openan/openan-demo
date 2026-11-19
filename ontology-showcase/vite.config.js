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
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiPort = process.env.API_PORT || '8787'

export default defineConfig({
  plugins: [react()],
  // 部署在 nginx 子路径 /ontology-showcase/ 下（同源挂载），
  // 资源引用需要带该前缀，否则按根路径请求会 404。
  base: '/ontology-showcase/',
  server: {
    proxy: {
      '/api': `http://localhost:${apiPort}`,
    },
  },
})
