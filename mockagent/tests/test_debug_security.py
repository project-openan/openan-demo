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
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from mockagent_engine.auth import create_token, hash_password
from mockagent_engine.config import Settings
from mockagent_engine.models import RequestLog, User
from mockagent_engine.routers import debug_proxy_router


def test_default_signing_secret_is_generated_and_legacy_secret_is_rejected(client):
    assert Settings().jwt_secret != Settings().jwt_secret
    legacy_secret = "dev-secret-change-me"
    with pytest.raises(ValueError, match="at least 32 bytes"):
        Settings(jwt_secret=legacy_secret)
    token = create_token("admin", "admin", legacy_secret, 10)
    response = client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_proxy_history_keeps_metadata_and_isolates_owners(app, client, auth_headers, monkeypatch):
    marker = "synthetic-upstream-credential"
    async_client = httpx.AsyncClient

    def upstream(request):
        assert request.headers["authorization"] == marker
        return httpx.Response(200, json={"echo": marker})

    monkeypatch.setattr(
        debug_proxy_router.httpx, "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(upstream), **kwargs),
    )
    response = client.post(
        "/api/v1/debug-proxy/registry", headers=auth_headers,
        json={"method": "GET", "path": "/test", "headers": {"Authorization": marker}},
    )
    assert response.status_code == 200
    assert response.json()["body"] == {"echo": marker}
    with Session(app.state.engine) as db:
        row = db.scalar(select(RequestLog))
        assert row.request_body == {"method": "GET"}
        assert row.response_body == {"status": 200}
        row_id = row.id
        row.request_body = {"method": "GET", "headers": {"Authorization": marker}}
        row.response_body = {"status": 200, "response": {"echo": marker}}
        db.add(User(username="reader", role="user", password_hash=hash_password("reader-password")))
        db.commit()

    path = f"/api/v1/history/{row_id}"
    response = client.get(path, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["requestBody"] == {"method": "GET"}
    assert response.json()["responseBody"] == {"status": 200}

    login = client.post("/api/v1/auth/login", json={"username": "reader", "password": "reader-password"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    assert client.get("/api/v1/history", headers=headers).json() == {"total": 0, "items": []}
    assert client.get(path, headers=headers).status_code == 404
