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
from sqlalchemy import select
from sqlalchemy.orm import Session

from openan_debug.models import Agent, Variant
from openan_debug.stub_service import fill_placeholders, pick_variant


def _add_variant(session, agent_id, template_uri, seq, data, enabled=True):
    session.add(Variant(agent_id=agent_id, template_uri=template_uri, variant_json=data, seq=seq, enabled=enabled))
    session.commit()


def test_pick_variant_round_robin(engine):
    with Session(engine) as session:
        agent = session.scalars(select(Agent)).first()
        uri = "Task-T/network-layer/private-line-complaint/v1"
        _add_variant(session, agent.id, uri, 0, {"n": "a"})
        _add_variant(session, agent.id, uri, 1, {"n": "b"})
        cursor = {}
        picked = [pick_variant(session, agent.id, uri, cursor).variant_json["n"] for _ in range(4)]
        assert picked == ["a", "b", "a", "b"]


def test_pick_variant_skips_disabled_and_missing(engine):
    with Session(engine) as session:
        agent = session.scalars(select(Agent)).first()
        _add_variant(session, agent.id, "Task-T/x/v9", 0, {"n": "on"}, enabled=True)
        _add_variant(session, agent.id, "Task-T/x/v9", 1, {"n": "off"}, enabled=False)
        assert pick_variant(session, agent.id, "Task-T/x/v9", {}).variant_json == {"n": "on"}
        assert pick_variant(session, agent.id, "Task-T/none/v1", {}) is None


def test_fill_placeholders():
    params = {"通知主题": "Incident", "level": 3}
    data = {
        "csn": "INC-{{timestamp}}",
        "topic": "{{slots.通知主题}}",
        "level": "{{slots.level}}",
        "missing": "{{slots.nope}}",
        "nested": {"reqId": "{{uuid}}", "list": ["{{slots.通知主题}}"]},
        "num": 7,
    }
    filled = fill_placeholders(data, params)
    assert filled["topic"] == "Incident"
    assert filled["level"] == "3"
    assert filled["missing"] == ""
    assert "{{" not in filled["csn"] and "T" in filled["csn"]
    assert len(filled["nested"]["reqId"]) == 36
    assert filled["nested"]["list"] == ["Incident"]
    assert filled["num"] == 7
