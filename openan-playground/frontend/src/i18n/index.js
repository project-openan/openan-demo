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
// i18n：与 openan-portal 同栈（i18next + react-i18next + browser LanguageDetector）。
// 字典：base-zh.json / base-en.json（嵌套结构，key 以 '.' 分层）。
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import zh from './base-zh.json'
import en from './base-en.json'

i18n.use(LanguageDetector).use(initReactI18next).init({
  resources: {
    zh: { translation: zh },
    en: { translation: en },
  },
  fallbackLng: 'zh',
  detection: {
    order: ['localStorage', 'navigator'],
    caches: ['localStorage'],
    lookupLocalStorage: 'openan-debug-lang',
  },
  interpolation: { escapeValue: false },
})

export default i18n
