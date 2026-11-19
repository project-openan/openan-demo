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
// remjsx/jsx-dev-runtime.js — react/jsx-dev-runtime 别名包装（V5.30 rem 缩放，开发模式）。
// 生产构建走 jsx-runtime.js；此处包装 jsxDEV（丢弃开发告警参数语义不变，仅拦截 style）。
import { Fragment, jsxDEV as _jsxDEV } from '../../node_modules/react/jsx-dev-runtime.js';
import { remStyleFor, remSvgAttrs } from './convert.js';
export const jsxDEV = (type, props, key, isStaticChildren, source, self) => {
  if (!props) return _jsxDEV(type, props, key, isStaticChildren, source, self);
  let p = props;
  if (p.style) p = { ...p, style: remStyleFor(type, p.style) };
  if (type === 'svg' && (p.width != null || p.height != null)) p = remSvgAttrs(type, p);
  return p === props
    ? _jsxDEV(type, props, key, isStaticChildren, source, self)
    : _jsxDEV(type, p, key, isStaticChildren, source, self);
};
export { Fragment };
