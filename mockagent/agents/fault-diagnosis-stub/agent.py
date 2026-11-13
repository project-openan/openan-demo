# -*- coding: utf-8 -*-
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""故障诊断打桩 Agent（专线投诉诊断，Task-T）。

差异化能力：未声明模板（templateUri 为 None）的请求按域内关键词推断为
专线投诉诊断模板，使无类型意图也能进入数据集匹配链路。
"""
from mockagent_engine.agent.base import StubAgentBase

TPL = "Task-T/network-layer/private-line-complaint/v1"
_KEYWORDS = ("投诉", "专线", "工单", "故障诊断")


class FaultDiagnosisAgent(StubAgentBase):
    agent_type = "fault-diagnosis"
    domain = "service-assurance"

    def transform_request(self, template_uri, prompt_text):
        if template_uri is None and any(k in prompt_text for k in _KEYWORDS):
            return TPL, prompt_text
        return template_uri, prompt_text
