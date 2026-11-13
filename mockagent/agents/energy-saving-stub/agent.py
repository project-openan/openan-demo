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

"""节能降碳打桩 Agent（无线节能策略，Task-T）。

差异化能力：未声明模板的节能类请求推断为 RAN 节能模板。
"""
from mockagent_engine.agent.base import StubAgentBase

TPL = "Task-T/network-layer/ran-energy-saving/v1"
_KEYWORDS = ("节能", "休眠", "关断", "降碳")


class EnergySavingAgent(StubAgentBase):
    agent_type = "energy-saving"
    domain = "ran"

    def transform_request(self, template_uri, prompt_text):
        if template_uri is None and any(k in prompt_text for k in _KEYWORDS):
            return TPL, prompt_text
        return template_uri, prompt_text
