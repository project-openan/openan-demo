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

"""Print the aggregated MockAgent registry summary."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mockagent_engine.agent_registry import load_define

define = load_define()
instances = define["instances"]
an_l4 = [i for i in instances if i["id"].startswith("an-l4-")]
legacy = [i for i in instances if not i["id"].startswith("an-l4-")]
ports = sorted(i["port"] for i in instances)
skills = sum(len(i.get("skills") or []) for i in an_l4)
cards = sum(1 for i in instances if (i.get("cardName") or "").startswith("mockagent_"))
card_files = len(list((Path(__file__).resolve().parents[1] / "agents").glob("*/agent_card.json")))
print(f"instances: {len(instances)} total = {len(legacy)} legacy + {len(an_l4)} an-l4")
print(f"ports: {ports[0]}..{ports[-1]} unique={len(set(ports))}")
print(f"an-l4 card skills total: {skills}")
print(f"cardName mockagent_*: {cards}/{len(instances)}; agent_card.json files: {card_files}")
