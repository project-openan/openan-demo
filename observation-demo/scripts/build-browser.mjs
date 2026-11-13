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
import fs from 'node:fs';
import path from 'node:path';

// build-browser.mjs — HTML 直开版打包：dist → release-html
// vite singlefile 产物 index.html 内联全部 JS/CSS，但资源引用为根相对（/icons/…、
// /design/…、/assets/…）——file:// 双击打开会解析到盘符根，故改写为相对路径；
// icons/design/assets 三个目录随包拷贝。产出：web\release-html\（双击 index.html 即可运行）。
// 运行方式：web 目录下 node scripts/build-browser.mjs（前置：npm run build）
const dist = 'dist';
const out = 'release-html';
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out);
let html = fs.readFileSync(path.join(dist, 'index.html'), 'utf8');
const count = (t) => html.split(t).length - 1;
const nIcons = count('/icons/');
const nDesign = count('/design/');
const nAssets = count('/assets/');
html = html
  .replaceAll('/icons/', 'icons/')
  .replaceAll('/design/', 'design/')
  .replaceAll('/assets/', 'assets/');
fs.writeFileSync(path.join(out, 'index.html'), html);
for (const f of ['icons', 'design', 'assets']) {
  fs.cpSync(path.join(dist, f), path.join(out, f), { recursive: true });
}
const leftover = (html.match(/"(\/(icons|design|assets))\//g) || []).length;
console.log(`refs rewritten: /icons/ x${nIcons}, /design/ x${nDesign}, /assets/ x${nAssets}; leftover absolute: ${leftover}`);
if (leftover) process.exit(1);
