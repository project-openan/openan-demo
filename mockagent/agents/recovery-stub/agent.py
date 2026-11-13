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

"""业务抢通打桩 Agent（服务恢复通知，Notification-T）。

差异化能力：未声明模板的抢通/恢复类请求推断为服务恢复模板。
"""
from mockagent_engine.agent.base import StubAgentBase

TPL = "Notification-T/network-layer/service-recovery/v1"
_KEYWORDS = ("抢通", "恢复", "倒换")


class RecoveryAgent(StubAgentBase):
    agent_type = "service-recovery"
    domain = "service-assurance"

    def transform_request(self, template_uri, prompt_text):
        if template_uri is None and any(k in prompt_text for k in _KEYWORDS):
            return TPL, prompt_text
        return template_uri, prompt_text
