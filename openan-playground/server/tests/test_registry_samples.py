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
from tests.conftest import auth_header


def test_registry_samples_requires_auth(client):
    assert client.get("/api/v1/registry/samples").status_code == 401


def test_registry_samples_returns_three_samples(client, admin_token):
    resp = client.get("/api/v1/registry/samples", headers=auth_header(admin_token))
    assert resp.status_code == 200
    samples = resp.json()
    assert len(samples) == 3
    keys = [s["key"] for s in samples]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)
    assert "minimal-agent" in keys


def test_registry_sample_cards_are_registry_compliant(client, admin_token):
    resp = client.get("/api/v1/registry/samples", headers=auth_header(admin_token))
    samples = resp.json()
    for sample in samples:
        assert sample["label"]
        assert sample["description"]
        card = sample["card"]
        assert card["name"]
        assert card["version"]
        assert card["description"]
        assert card["provider"]["organization"]
        assert len(card["skills"]) > 0
        for skill in card["skills"]:
            assert skill["id"]
            assert skill["name"]
            assert skill["description"]
        assert len(card["supportedInterfaces"]) > 0
        for interface in card["supportedInterfaces"]:
            assert interface["url"]
            assert interface["protocolBinding"]
