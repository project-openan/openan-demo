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

"""共享 fixture：隔离的临时数据库 + 真实登录态（不 mock 业务代码，只隔离副作用）。"""
import pytest
from fastapi.testclient import TestClient

TEST_ADMIN_PASSWORD = "test-admin-pass"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """每个测试独立 SQLite + 固定管理员密码（bootstrap 会用它创建 admin 用户）。"""
    monkeypatch.setenv("MOCK_AGENT_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("MOCK_AGENT_ADMIN_PASSWORD", TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("MOCK_AGENT_JWT_SECRET", "fixture-only-64-byte-test-key-" * 3)
    from mockagent_engine.main import create_app

    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def admin_password():
    return TEST_ADMIN_PASSWORD


@pytest.fixture()
def auth_headers(client, admin_password):
    """走真实 /auth/login 拿 token（同时覆盖登录链路）。"""
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": admin_password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}
