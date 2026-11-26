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

"""调测台路由覆盖率补测：console / history / debug-proxy / settings / registry。"""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from mockagent_engine.auth import hash_password
from mockagent_engine.models import Agent, RequestLog, ServiceSettings, User
from mockagent_engine.routers import console_router, debug_proxy_router
from mockagent_engine.routers.debug_proxy_router import (
    MAX_RESPONSE_CHARS,
    TRUNCATION_MARKER,
    _truncate,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _mock_async_client(monkeypatch, router_module, handler):
    """Patch router_module.httpx.AsyncClient to use MockTransport(handler)."""
    real = httpx.AsyncClient

    def factory(**kwargs):
        kwargs.pop("transport", None)
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(router_module.httpx, "AsyncClient", factory)


def _create_agent(app, **kwargs):
    with Session(app.state.engine) as db:
        agent = Agent(**kwargs)
        db.add(agent)
        db.commit()
        db.refresh(agent)
        return agent.id


def _create_log(app, **kwargs):
    with Session(app.state.engine) as db:
        log = RequestLog(**kwargs)
        db.add(log)
        db.commit()
        db.refresh(log)
        return log.id


def _user_headers(client, username, password):
    resp = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


# ===================================================================
# console_router — helper functions
# ===================================================================

def test_local_base_strips_message_send_suffix():
    """TC-CON-001 | _local_base 剥离 /debug/a2a/message:send 后缀

    输入: url = "http://h:9000/debug/a2a/message:send"
    预期输出: "http://h:9000"
    断言点: 返回值等于去掉后缀的 base url
    防回归: 若后缀匹配逻辑被改坏，返回值不等于预期 base
    """
    assert console_router._local_base("http://h:9000/debug/a2a/message:send") == "http://h:9000"


def test_local_base_returns_url_unchanged_without_suffix():
    """TC-CON-002 | _local_base 无后缀时原样返回

    输入: url = "http://h:9000/other"
    预期输出: "http://h:9000/other"
    断言点: 返回值与输入相同
    防回归: 若误截非匹配后缀的 URL，返回值改变
    """
    assert console_router._local_base("http://h:9000/other") == "http://h:9000/other"


def test_derive_extension_task_t_template():
    """TC-CON-003 | _derive_extension 对 Task-T 前缀返回 Task-T 扩展 URI

    输入: request_body 含 message.metadata.templateUri = "Task-T/x/y/v1"
    预期输出: TASK_T_EXTENSION_URI
    断言点: 返回值等于 TASK_T_EXTENSION_URI
    防回归: 若模板前缀映射被删除，回退到 DEFAULT_EXTENSION
    """
    from mockagent_engine.agent.flow_env import EXT_URI_BY_PREFIX

    body = {"message": {"metadata": {"templateUri": "Task-T/x/y/v1"}}}
    assert console_router._derive_extension(body) == EXT_URI_BY_PREFIX["Task-T"]


def test_derive_extension_no_template_returns_default():
    """TC-CON-004 | _derive_extension 无 templateUri 返回 DEFAULT_EXTENSION

    输入: request_body = {}
    预期输出: DEFAULT_EXTENSION
    断言点: 返回值等于 DEFAULT_EXTENSION 常量
    防回归: 若回退逻辑被删除，返回 None
    """
    assert console_router._derive_extension({}) == console_router.DEFAULT_EXTENSION


def test_extract_task_state_returns_state():
    """TC-CON-005 | _extract_task_state 从有效响应提取 task state

    输入: {"task": {"status": {"state": "completed"}}}
    预期输出: "completed"
    断言点: 返回值等于 "completed"
    防回归: 若 state 提取逻辑被改坏，返回 None 或错误值
    """
    assert console_router._extract_task_state({"task": {"status": {"state": "completed"}}}) == "completed"


def test_extract_task_state_none_for_non_dict():
    """TC-CON-006 | _extract_task_state 对非 dict 输入返回 None

    输入: "not a dict"
    预期输出: None
    断言点: 返回值 is None
    防回归: 若类型守卫被删除，AttributeError
    """
    assert console_router._extract_task_state("not a dict") is None
    assert console_router._extract_task_state(42) is None


def test_extract_task_state_none_when_task_missing():
    """TC-CON-007 | _extract_task_state task 缺失或非 dict 时返回 None

    输入: {"task": "scalar"} 和 {}
    预期输出: None
    断言点: 两个输入都返回 None
    防回归: 若 task 类型守卫被删除，对字符串调用 .get 导致 AttributeError
    """
    assert console_router._extract_task_state({"task": "scalar"}) is None
    assert console_router._extract_task_state({}) is None


def test_extract_task_state_none_when_status_missing():
    """TC-CON-008 | _extract_task_state status 缺失或非 dict 时返回 None

    输入: {"task": {"status": "scalar"}} 和 {"task": {}}
    预期输出: None
    断言点: 两个输入都返回 None
    防回归: 若 status 类型守卫被删除，对字符串调用 .get 导致 AttributeError
    """
    assert console_router._extract_task_state({"task": {"status": "scalar"}}) is None
    assert console_router._extract_task_state({"task": {}}) is None


# ===================================================================
# console_router — console_send endpoint
# ===================================================================

def test_console_send_default_agent_json_response(client, auth_headers, monkeypatch):
    """TC-CON-009 | console_send 默认 Agent 返回 JSON 响应并记录 task_state

    输入: POST /console/send，agentId=None，mock httpx 返回 {"task":{"status":{"state":"completed"}}}
    预期输出: 200，response.status=200，response.response 含 task state
    断言点: HTTP 200 + response.status==200 + response.response.task.status.state=="completed"
    防回归: 若 task_state 提取或响应体组装被改坏，断言失败
    """
    def handler(request):
        return httpx.Response(200, json={"task": {"status": {"state": "completed"}}})

    _mock_async_client(monkeypatch, console_router, handler)

    resp = client.post(
        "/api/v1/console/send",
        headers=auth_headers,
        json={"request": {"message": {"metadata": {"templateUri": "Task-T/test/v1"}}}, "note": "tc009"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == 200
    assert body["response"]["task"]["status"]["state"] == "completed"


def test_console_send_httpx_error_returns_status_zero(client, auth_headers, monkeypatch):
    """TC-CON-010 | console_send httpx 连接错误返回 status=0

    输入: POST /console/send，mock httpx 抛 ConnectError
    预期输出: 200（HTTP 层），response.status=0，response.response.error 含异常信息
    断言点: body.status==0 + body.response 含 "error" 键
    防回归: 若异常分支被删除，请求 500
    """
    def handler(request):
        raise httpx.ConnectError("connection refused")

    _mock_async_client(monkeypatch, console_router, handler)

    resp = client.post(
        "/api/v1/console/send",
        headers=auth_headers,
        json={"request": {}, "note": "tc010"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == 0
    assert "error" in body["response"]


def test_console_send_non_json_response(client, auth_headers, monkeypatch):
    """TC-CON-011 | console_send 非 JSON 响应回退到 raw text

    输入: POST /console/send，mock httpx 返回纯文本
    预期输出: 200，response.response.raw 含原始文本
    断言点: body.response.raw == "plain text body"
    防回归: 若 ValueError 回退分支被删除，500 错误
    """
    def handler(request):
        return httpx.Response(200, content=b"plain text body", headers={"content-type": "text/plain"})

    _mock_async_client(monkeypatch, console_router, handler)

    resp = client.post(
        "/api/v1/console/send",
        headers=auth_headers,
        json={"request": {}, "note": "tc011"},
    )
    assert resp.status_code == 200
    assert resp.json()["response"]["raw"] == "plain text body"


def test_console_send_nonexistent_agent_returns_404(client, auth_headers, monkeypatch):
    """TC-CON-012 | console_send 不存在的 agentId 返回 404

    输入: POST /console/send，agentId=999999
    预期输出: 404，detail 含 "Agent not found"
    断言点: HTTP 404 + detail=="Agent not found"
    防回归: 若 404 守卫被删除，请求继续发到不存在的 target
    """
    _mock_async_client(monkeypatch, console_router, lambda r: httpx.Response(200, json={}))

    resp = client.post(
        "/api/v1/console/send",
        headers=auth_headers,
        json={"request": {}, "agentId": 999999},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Agent not found"


def test_console_send_disabled_agent_returns_409(app, client, auth_headers, monkeypatch):
    """TC-CON-013 | console_send 禁用 Agent 返回 409

    输入: POST /console/send，agentId=<已禁用 Agent>
    预期输出: 409，detail 含 "Agent 已禁用"
    断言点: HTTP 409 + detail=="Agent 已禁用"
    防回归: 若禁用检查被删除，请求发到禁用 Agent 的 debug 端点
    """
    agent_id = _create_agent(app, organization="TestOrg", name="DisabledAgent", enabled=False)
    _mock_async_client(monkeypatch, console_router, lambda r: httpx.Response(200, json={}))

    resp = client.post(
        "/api/v1/console/send",
        headers=auth_headers,
        json={"request": {}, "agentId": agent_id},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Agent 已禁用"


def test_console_send_enabled_nondefault_agent_targets_debug_url(app, client, auth_headers, monkeypatch):
    """TC-CON-014 | console_send 启用的非默认 Agent 走 /debug/a2a/agent/{id} 路径

    输入: POST /console/send，agentId=<已启用非默认 Agent>
    预期输出: 200，mock handler 收到的 URL 含 /debug/a2a/agent/{id}/message:send
    断言点: HTTP 200 + handler 收到的 URL path 包含 agent id
    防回归: 若 _local_base 或 target 拼接被改坏，handler 收到错误 URL
    """
    agent_id = _create_agent(app, organization="TestOrg", name="EnabledAgent", enabled=True)
    captured = []

    def handler(request):
        captured.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    _mock_async_client(monkeypatch, console_router, handler)

    resp = client.post(
        "/api/v1/console/send",
        headers=auth_headers,
        json={"request": {}, "agentId": agent_id},
    )
    assert resp.status_code == 200
    assert f"/debug/a2a/agent/{agent_id}/message:send" in captured[0]


def test_console_send_instance_not_running_returns_409(client, auth_headers, monkeypatch):
    """TC-CON-015 | console_send 实例未运行返回 409

    输入: POST /console/send，instanceId="fault-diagnosis-stub"，不 mock health probe（返回 False）
    预期输出: 409，detail 含 "未运行"
    断言点: HTTP 409 + detail 含 "未运行"
    防回归: 若健康检查守卫被删除，请求发到不可达端口
    """
    monkeypatch.setattr(console_router, "_health_probe", lambda port: False)

    resp = client.post(
        "/api/v1/console/send",
        headers=auth_headers,
        json={"request": {}, "instanceId": "fault-diagnosis-stub"},
    )
    assert resp.status_code == 409
    assert "未运行" in resp.json()["detail"]


def test_console_send_running_instance_targets_port(app, client, auth_headers, monkeypatch):
    """TC-CON-016 | console_send 运行中实例请求发到实例端口

    输入: POST /console/send，instanceId="fault-diagnosis-stub"，mock health probe=True
    预期输出: 200，handler 收到的 URL 含 :9005/message:send
    断言点: HTTP 200 + captured URL 含 "127.0.0.1:9005/message:send"
    防回归: 若端口提取或 target 拼接被改坏，handler 收到错误端口
    """
    monkeypatch.setattr(console_router, "_health_probe", lambda port: True)
    _create_agent(
        app, organization="OpenAN-Stub", name="故障诊断打桩 Agent", enabled=True
    )
    captured = []

    def handler(request):
        captured.append(str(request.url))
        return httpx.Response(200, json={"task": {"status": {"state": "submitted"}}})

    _mock_async_client(monkeypatch, console_router, handler)

    resp = client.post(
        "/api/v1/console/send",
        headers=auth_headers,
        json={"request": {}, "instanceId": "fault-diagnosis-stub"},
    )
    assert resp.status_code == 200
    assert any("127.0.0.1:9005/message:send" in u for u in captured)


def test_console_send_unknown_instance_returns_404(client, auth_headers, monkeypatch):
    """TC-CON-017 | console_send 未知 instanceId 返回 404

    输入: POST /console/send，instanceId="does-not-exist"
    预期输出: 404，detail 含 "未定义"
    断言点: HTTP 404 + detail 含 "未定义"
    防回归: 若实例查找守卫被删除，后续 port 提取 KeyError
    """
    resp = client.post(
        "/api/v1/console/send",
        headers=auth_headers,
        json={"request": {}, "instanceId": "does-not-exist"},
    )
    assert resp.status_code == 404
    assert "未定义" in resp.json()["detail"]


def test_console_send_without_auth_returns_401(client):
    """TC-CON-018 | console_send 无 token 返回 401

    输入: POST /console/send，无 Authorization 头
    预期输出: 401
    断言点: HTTP 401
    防回归: 若鉴权依赖被删除，返回 200 或 422
    """
    assert client.post("/api/v1/console/send", json={"request": {}}).status_code == 401


def test_console_send_missing_request_field_returns_422(client, auth_headers):
    """TC-CON-019 | console_send 缺少 request 字段返回 422

    输入: POST /console/send，body 不含 request 字段
    预期输出: 422
    断言点: HTTP 422
    防回归: 若 pydantic 校验被绕过，缺失字段仍进入业务逻辑
    """
    resp = client.post("/api/v1/console/send", headers=auth_headers, json={"note": "no request"})
    assert resp.status_code == 422


# ===================================================================
# console_router — trace_prompts / demo_dataset
# ===================================================================

def test_trace_prompts_returns_data(client, auth_headers):
    """TC-CON-020 | trace-prompts 返回实采 prompt 数据集

    输入: GET /console/trace-prompts
    预期输出: 200，body 含 examples 列表
    断言点: HTTP 200 + body["examples"] 非空列表
    防回归: 若文件读取或 JSON 解析被改坏，返回 404 或缺 examples
    """
    resp = client.get("/api/v1/console/trace-prompts", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json()["examples"], list)
    assert len(resp.json()["examples"]) > 0


def test_trace_prompts_file_error_returns_404(client, auth_headers, monkeypatch):
    """TC-CON-021 | trace-prompts 文件读取失败返回 404

    输入: GET /console/trace-prompts，mock _dataset_file 抛 OSError
    预期输出: 404，detail 含 "数据不可用"
    断言点: HTTP 404 + detail 含 "数据不可用"
    防回归: 若异常处理被删除，返回 500
    """
    def boom(filename):
        raise OSError("disk gone")

    monkeypatch.setattr(console_router, "_dataset_file", boom)
    resp = client.get("/api/v1/console/trace-prompts", headers=auth_headers)
    assert resp.status_code == 404
    assert "数据不可用" in resp.json()["detail"]


def test_demo_dataset_returns_data(client, auth_headers):
    """TC-CON-022 | demo-dataset 返回 Demo 数据集

    输入: GET /console/demo-dataset
    预期输出: 200，body 含 pairs 列表
    断言点: HTTP 200 + body["pairs"] 非空列表
    防回归: 若文件读取被改坏，返回 404 或缺 pairs
    """
    resp = client.get("/api/v1/console/demo-dataset", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json()["pairs"], list)
    assert len(resp.json()["pairs"]) > 0


def test_demo_dataset_file_error_returns_404(client, auth_headers, monkeypatch):
    """TC-CON-023 | demo-dataset 文件读取失败返回 404

    输入: GET /console/demo-dataset，mock _dataset_file 抛 OSError
    预期输出: 404，detail 含 "数据集不可用"
    断言点: HTTP 404 + detail 含 "数据集不可用"
    防回归: 若异常处理被删除，返回 500
    """
    def boom(filename):
        raise OSError("disk gone")

    monkeypatch.setattr(console_router, "_dataset_file", boom)
    resp = client.get("/api/v1/console/demo-dataset", headers=auth_headers)
    assert resp.status_code == 404
    assert "数据集不可用" in resp.json()["detail"]


# ===================================================================
# console_router — list_datasets / dataset_pairs / dataset_pair_detail
# ===================================================================

def test_list_datasets_returns_both(client, auth_headers):
    """TC-CON-024 | list_datasets 返回 seed + expanded 两个数据集

    输入: GET /console/datasets
    预期输出: 200，datasets 列表含 id="seed" 和 id="expanded"
    断言点: 两个数据集 id 出现在结果中
    防回归: 若文件加载被改坏，列表为空或缺失
    """
    console_router._DATASET_CACHE.clear()
    resp = client.get("/api/v1/console/datasets", headers=auth_headers)
    assert resp.status_code == 200
    ids = {d["id"] for d in resp.json()["datasets"]}
    assert ids == {"seed", "expanded"}


def test_list_datasets_handles_load_error(client, auth_headers, monkeypatch):
    """TC-CON-025 | list_datasets 文件加载失败时跳过该数据集

    输入: GET /console/datasets，mock _load_dataset_file 抛 OSError
    预期输出: 200，datasets 列表为空
    断言点: HTTP 200 + datasets==[]
    防回归: 若 except 分支被删除，500 错误
    """
    console_router._DATASET_CACHE.clear()

    def boom(filename):
        raise OSError("disk gone")

    monkeypatch.setattr(console_router, "_load_dataset_file", boom)
    resp = client.get("/api/v1/console/datasets", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["datasets"] == []


def test_dataset_pairs_pagination(client, auth_headers):
    """TC-CON-026 | dataset_pairs 分页返回正确页

    输入: GET /console/datasets/expanded/pairs?page=1&pageSize=2
    预期输出: 200，items 长度 2，total>2
    断言点: len(items)==2 + total>2
    防回归: 若分页逻辑被改坏，返回错误数量
    """
    console_router._DATASET_CACHE.clear()
    resp = client.get(
        "/api/v1/console/datasets/expanded/pairs",
        params={"page": 1, "pageSize": 2},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["total"] > 2


def test_dataset_pairs_unknown_ds_returns_404(client, auth_headers):
    """TC-CON-027 | dataset_pairs 未知 ds_id 返回 404

    输入: GET /console/datasets/unknown/pairs
    预期输出: 404，detail 含 "未知数据集"
    断言点: HTTP 404 + detail 含 "未知数据集"
    防回归: 若 ds_id 校验被删除，后续文件加载 KeyError
    """
    resp = client.get("/api/v1/console/datasets/unknown/pairs", headers=auth_headers)
    assert resp.status_code == 404
    assert "未知数据集" in resp.json()["detail"]


def test_dataset_pairs_load_error_returns_404(client, auth_headers, monkeypatch):
    """TC-CON-028 | dataset_pairs 文件加载失败返回 404

    输入: GET /console/datasets/seed/pairs，mock _load_dataset_file 抛 OSError
    预期输出: 404，detail 含 "数据集不可用"
    断言点: HTTP 404 + detail 含 "数据集不可用"
    防回归: 若 except 分支被删除，500 错误
    """
    def boom(filename):
        raise OSError("disk gone")

    monkeypatch.setattr(console_router, "_load_dataset_file", boom)
    resp = client.get("/api/v1/console/datasets/seed/pairs", headers=auth_headers)
    assert resp.status_code == 404
    assert "数据集不可用" in resp.json()["detail"]


def test_dataset_pairs_agent_scope_matching_instance(app, client, auth_headers):
    """TC-CON-029 | dataset_pairs agentId 匹配实例时按模板范围过滤

    输入: GET /console/datasets/expanded/pairs?agentId=<匹配实例的 Agent>，实例有 datasetTemplates
    预期输出: 200，agentScopeTemplates 非空，items 仅含范围内模板
    断言点: agentScopeTemplates 非空 + 所有 item 的 templateUri 在范围内
    防回归: 若范围过滤被删除，返回全部 pairs
    """
    console_router._DATASET_CACHE.clear()
    agent_id = _create_agent(
        app, organization="OpenAN-Stub", name="故障诊断打桩 Agent", enabled=True
    )
    resp = client.get(
        "/api/v1/console/datasets/expanded/pairs",
        params={"agentId": agent_id, "pageSize": 100},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["agentScopeTemplates"] is not None
    scope = set(data["agentScopeTemplates"])
    assert scope  # non-empty
    for item in data["items"]:
        assert item["templateUri"] in scope


def test_dataset_pairs_agent_scope_no_matching_instance(app, client, auth_headers):
    """TC-CON-030 | dataset_pairs agentId 无匹配实例时返回空列表

    输入: GET /console/datasets/expanded/pairs?agentId=<不匹配任何实例的 Agent>
    预期输出: 200，total=0，items=[]
    断言点: total==0 + items==[]
    防回归: 若空列表回退被删除，返回全部 pairs
    """
    console_router._DATASET_CACHE.clear()
    agent_id = _create_agent(
        app, organization="NoMatch", name="NoMatchAgent", enabled=True
    )
    resp = client.get(
        "/api/v1/console/datasets/expanded/pairs",
        params={"agentId": agent_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["items"] == []


def test_dataset_pairs_agent_id_nonexistent(app, client, auth_headers):
    """TC-CON-031 | dataset_pairs 不存在 agentId 返回空列表

    输入: GET /console/datasets/expanded/pairs?agentId=999999
    预期输出: 200，total=0，items=[]
    断言点: total==0 + items==[]
    防回归: 若 agent_row None 守卫被删除，后续逻辑 KeyError
    """
    console_router._DATASET_CACHE.clear()
    resp = client.get(
        "/api/v1/console/datasets/expanded/pairs",
        params={"agentId": 999999},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_dataset_pairs_protocol_filter(client, auth_headers):
    """TC-CON-032 | dataset_pairs 按 protocol 过滤

    输入: GET /console/datasets/seed/pairs?protocol=Task-T
    预期输出: 200，所有 item 的 protocol=="Task-T"
    断言点: 所有 item.protocol=="Task-T"
    防回归: 若 protocol 过滤被删除，返回非 Task-T 的 pair
    """
    console_router._DATASET_CACHE.clear()
    resp = client.get(
        "/api/v1/console/datasets/seed/pairs",
        params={"protocol": "Task-T"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["protocol"] == "Task-T"


def test_dataset_pairs_template_uri_filter(client, auth_headers):
    """TC-CON-033 | dataset_pairs 按 templateUri 过滤

    输入: GET /console/datasets/seed/pairs?templateUri=Task-T/private-line-complaint/v1
    预期输出: 200，所有 item 的 templateUri 匹配
    断言点: 所有 item.templateUri=="Task-T/private-line-complaint/v1"
    防回归: 若 templateUri 过滤被删除，返回其他模板的 pair
    """
    console_router._DATASET_CACHE.clear()
    tpl = "Task-T/private-line-complaint/v1"
    resp = client.get(
        "/api/v1/console/datasets/seed/pairs",
        params={"templateUri": tpl},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["templateUri"] == tpl


def test_dataset_pairs_search_query(client, auth_headers):
    """TC-CON-034 | dataset_pairs 按 q 关键词搜索

    输入: GET /console/datasets/seed/pairs?q=专线中断
    预期输出: 200，至少一个 item 的 scenario/direction/label 含 "专线中断"
    断言点: total>0 + 至少一个 item 含搜索词
    防回归: 若 q 过滤被删除，返回不含关键词的 pair
    """
    console_router._DATASET_CACHE.clear()
    resp = client.get(
        "/api/v1/console/datasets/seed/pairs",
        params={"q": "专线中断"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] > 0
    found = any(
        "专线中断" in str(item.get("scenario", "")) + str(item.get("direction", "")) + str(item.get("label", ""))
        for item in data["items"]
    )
    assert found


def test_dataset_pair_detail_returns_pair(client, auth_headers):
    """TC-CON-035 | dataset_pair_detail 返回完整 pair

    输入: GET /console/datasets/seed/pairs/demo-pair-1
    预期输出: 200，pairId=="demo-pair-1"，含 requestPrompt
    断言点: pairId=="demo-pair-1" + requestPrompt 非空
    防回归: 若 pair 查找被改坏，返回 404 或缺字段
    """
    console_router._DATASET_CACHE.clear()
    resp = client.get(
        "/api/v1/console/datasets/seed/pairs/demo-pair-1",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["pairId"] == "demo-pair-1"
    assert resp.json()["requestPrompt"]


def test_dataset_pair_detail_unknown_ds_returns_404(client, auth_headers):
    """TC-CON-036 | dataset_pair_detail 未知 ds_id 返回 404

    输入: GET /console/datasets/unknown/pairs/p1
    预期输出: 404，detail 含 "未知数据集"
    断言点: HTTP 404 + detail 含 "未知数据集"
    防回归: 若 ds_id 校验被删除，后续文件加载 KeyError
    """
    resp = client.get("/api/v1/console/datasets/unknown/pairs/p1", headers=auth_headers)
    assert resp.status_code == 404
    assert "未知数据集" in resp.json()["detail"]


def test_dataset_pair_detail_load_error_returns_404(client, auth_headers, monkeypatch):
    """TC-CON-037 | dataset_pair_detail 文件加载失败返回 404

    输入: GET /console/datasets/seed/pairs/p1，mock _load_dataset_file 抛 OSError
    预期输出: 404，detail 含 "数据集不可用"
    断言点: HTTP 404 + detail 含 "数据集不可用"
    防回归: 若 except 分支被删除，500 错误
    """
    def boom(filename):
        raise OSError("disk gone")

    monkeypatch.setattr(console_router, "_load_dataset_file", boom)
    resp = client.get("/api/v1/console/datasets/seed/pairs/p1", headers=auth_headers)
    assert resp.status_code == 404
    assert "数据集不可用" in resp.json()["detail"]


def test_dataset_pair_detail_not_found_returns_404(client, auth_headers):
    """TC-CON-038 | dataset_pair_detail pair 不存在返回 404

    输入: GET /console/datasets/seed/pairs/nonexistent-pair
    预期输出: 404，detail 含 "不存在"
    断言点: HTTP 404 + detail 含 "不存在"
    防回归: 若 pair not-found 守卫被删除，返回 None 或 500
    """
    console_router._DATASET_CACHE.clear()
    resp = client.get(
        "/api/v1/console/datasets/seed/pairs/nonexistent-pair",
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


def test_dataset_agent_associations_template_count_error(client, auth_headers, monkeypatch):
    """TC-CON-039 | agent-associations 在模板计数失败时仍返回 200

    输入: GET /console/datasets/agent-associations，mock _load_dataset_file 抛 OSError
    预期输出: 200，associations 列表非空（默认 Agent 行仍在）
    断言点: HTTP 200 + associations 非空
    防回归: 若 _dataset_template_counts 异常处理被删除，500 错误
    """
    def boom(filename):
        raise OSError("disk gone")

    monkeypatch.setattr(console_router, "_load_dataset_file", boom)
    resp = client.get("/api/v1/console/datasets/agent-associations", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json()["associations"], list)
    assert len(resp.json()["associations"]) > 0


def test_dataset_agent_associations_normal_path(client, auth_headers):
    """TC-CON-040 | agent-associations 正常路径返回含模板计数的关联视图

    输入: GET /console/datasets/agent-associations（无 mock）
    预期输出: 200，associations 非空，默认 Agent 的 pairCounts 含 seed/expanded 键
    断言点: HTTP 200 + 默认 Agent 的 pairCounts["seed"]>0
    防回归: 若 _dataset_template_counts 成功路径被改坏，pairCounts 全为 0
    """
    console_router._DATASET_CACHE.clear()
    resp = client.get("/api/v1/console/datasets/agent-associations", headers=auth_headers)
    assert resp.status_code == 200
    assoc = resp.json()["associations"]
    assert len(assoc) > 0
    default = next(a for a in assoc if a["instanceId"] is None)
    assert default["pairCounts"]["seed"] > 0
    assert default["pairCounts"]["expanded"] > 0
    assert default["templateCount"] is None


def test_console_send_explicit_default_agent_id(app, client, auth_headers, monkeypatch):
    """TC-CON-068 | console_send 显式传 default_agent_id 走内部 URL

    输入: POST /console/send，agentId=<default_agent_id>
    预期输出: 200，handler 收到的 URL 含 /debug/a2a/message:send（内部 URL，非 /agent/{id}/）
    断言点: HTTP 200 + captured URL 不含 "/agent/" 前缀
    防回归: 若 agent.id == default_agent_id 分支被删除，走 /debug/a2a/agent/{id}/ 路径
    """
    default_id = app.state.default_agent_id
    captured = []

    def handler(request):
        captured.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    _mock_async_client(monkeypatch, console_router, handler)
    resp = client.post(
        "/api/v1/console/send",
        headers=auth_headers,
        json={"request": {}, "agentId": default_id},
    )
    assert resp.status_code == 200
    assert "/debug/a2a/message:send" in captured[0]
    assert "/agent/" not in captured[0]


def test_console_endpoints_without_auth_return_401(client):
    """TC-CON-069 | console 各端点无 token 返回 401

    输入: GET /console/trace-prompts、/demo-dataset、/datasets 无 Authorization
    预期输出: 401
    断言点: 三个端点都返回 401
    防回归: 若鉴权依赖被删除，返回 200
    """
    for path in ("/api/v1/console/trace-prompts", "/api/v1/console/demo-dataset", "/api/v1/console/datasets"):
        assert client.get(path).status_code == 401, f"{path} should require auth"


# ===================================================================
# history_router
# ===================================================================

def test_history_list_filters_by_template_uri(app, client, auth_headers):
    """TC-CON-041 | list_history 按 templateUri 过滤

    输入: 创建两条 log（不同 templateUri），GET /history?templateUri=T1
    预期输出: 200，仅返回 templateUri==T1 的记录
    断言点: total==1 + item.templateUri==T1
    防回归: 若 templateUri 过滤被删除，返回全部记录
    """
    _create_log(app, template_uri="T1", direction="console", feature="a2at", user_id=1)
    _create_log(app, template_uri="T2", direction="console", feature="a2at", user_id=1)
    resp = client.get("/api/v1/history", params={"templateUri": "T1"}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["templateUri"] == "T1"


def test_history_list_filters_by_direction(app, client, auth_headers):
    """TC-CON-042 | list_history 按 direction 过滤

    输入: 创建两条 log（不同 direction），GET /history?direction=inbound
    预期输出: 200，仅返回 direction==inbound 的记录
    断言点: total==1 + item.direction=="inbound"
    防回归: 若 direction 过滤被删除，返回全部记录
    """
    _create_log(app, direction="inbound", feature="a2at", user_id=1)
    _create_log(app, direction="console", feature="a2at", user_id=1)
    resp = client.get("/api/v1/history", params={"direction": "inbound"}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["direction"] == "inbound"


def test_history_list_filters_by_state(app, client, auth_headers):
    """TC-CON-043 | list_history 按 state（task_state）过滤

    输入: 创建两条 log（不同 task_state），GET /history?state=completed
    预期输出: 200，仅返回 taskState==completed 的记录
    断言点: total==1 + item.taskState=="completed"
    防回归: 若 state 过滤被删除，返回全部记录
    """
    _create_log(app, task_state="completed", feature="a2at", user_id=1)
    _create_log(app, task_state="failed", feature="a2at", user_id=1)
    resp = client.get("/api/v1/history", params={"state": "completed"}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["taskState"] == "completed"


def test_history_list_filters_by_feature(app, client, auth_headers):
    """TC-CON-044 | list_history 按 feature 过滤

    输入: 创建两条 log（不同 feature），GET /history?feature=debug
    预期输出: 200，仅返回 feature==debug 的记录
    断言点: total==1 + item.feature=="debug"
    防回归: 若 feature 过滤被删除，返回全部记录
    """
    _create_log(app, feature="a2at", user_id=1)
    _create_log(app, feature="debug", user_id=1)
    resp = client.get("/api/v1/history", params={"feature": "debug"}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["feature"] == "debug"


def test_history_non_admin_sees_only_own_logs(app, client):
    """TC-CON-045 | list_history 非 admin 用户仅看到自己的日志

    输入: 创建 admin 的 log，创建 reader 用户，reader 登录后 GET /history
    预期输出: 200，total==0（reader 没有自己的日志）
    断言点: total==0
    防回归: 若 user_id 过滤被删除，reader 看到 admin 的日志
    """
    _create_log(app, feature="a2at", user_id=1)
    with Session(app.state.engine) as db:
        db.add(User(username="reader", role="user", password_hash=hash_password("reader-pass")))
        db.commit()
    headers = _user_headers(client, "reader", "reader-pass")
    resp = client.get("/api/v1/history", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_history_get_returns_log_with_user_info(app, client, auth_headers):
    """TC-CON-046 | get_history 返回单条日志含 userId

    输入: 创建一条 log，GET /history/{log_id}
    预期输出: 200，body.feature 存在，body.userId 存在
    断言点: HTTP 200 + body.feature 存在 + body.userId==1
    防回归: 若 with_user 标志被改坏，缺 userId 字段
    """
    log_id = _create_log(app, feature="a2at", user_id=1)
    resp = client.get(f"/api/v1/history/{log_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["feature"] == "a2at"
    assert resp.json()["userId"] == 1


def test_history_get_nonexistent_returns_404(client, auth_headers):
    """TC-CON-047 | get_history 不存在 log_id 返回 404

    输入: GET /history/999999
    预期输出: 404，detail=="Log not found"
    断言点: HTTP 404 + detail=="Log not found"
    防回归: 若 not-found 守卫被删除，返回 None 或 500
    """
    resp = client.get("/api/v1/history/999999", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Log not found"


def test_history_get_non_admin_other_user_returns_404(app, client):
    """TC-CON-048 | get_history 非 admin 访问他人日志返回 404

    输入: 创建 admin 的 log，reader 登录后 GET /history/{log_id}
    预期输出: 404
    断言点: HTTP 404
    防回归: 若 user_id 隔离被删除，reader 看到 admin 的日志
    """
    log_id = _create_log(app, feature="a2at", user_id=1)
    with Session(app.state.engine) as db:
        db.add(User(username="reader", role="user", password_hash=hash_password("reader-pass")))
        db.commit()
    headers = _user_headers(client, "reader", "reader-pass")
    resp = client.get(f"/api/v1/history/{log_id}", headers=headers)
    assert resp.status_code == 404


def test_history_legacy_proxy_row_masks_credentials(app, client, auth_headers):
    """TC-CON-049 | list_history 对 legacy proxy 行脱敏 request/response body

    输入: 创建一条 feature="registry" direction="console" 的 log（含敏感 body），GET /history
    预期输出: 200，该 log 的 requestBody 仅含 method、responseBody 仅含 status
    断言点: requestBody=={"method":"GET"} + responseBody=={"status":200}
    防回归: 若 legacy 脱敏分支被删除，敏感 credentials 泄露到 history
    """
    _create_log(
        app,
        feature="registry",
        direction="console",
        request_body={"method": "GET", "headers": {"Authorization": "secret"}},
        response_body={"status": 200, "response": {"token": "leak"}},
        user_id=1,
    )
    resp = client.get("/api/v1/history", headers=auth_headers)
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["requestBody"] == {"method": "GET"}
    assert item["responseBody"] == {"status": 200}


def test_history_without_auth_returns_401(client):
    """TC-CON-070 | history 无 token 返回 401

    输入: GET /history 无 Authorization
    预期输出: 401
    断言点: HTTP 401
    防回归: 若鉴权依赖被删除，返回 200
    """
    assert client.get("/api/v1/history").status_code == 401


# ===================================================================
# debug_proxy_router
# ===================================================================

def test_truncate_short_text_unchanged():
    """TC-CON-050 | _truncate 短文本原样返回

    输入: "hello"（长度 < MAX_RESPONSE_CHARS）
    预期输出: "hello"
    断言点: 返回值等于输入
    防回归: 若截断逻辑误截短文本，返回值改变
    """
    assert _truncate("hello") == "hello"


def test_truncate_long_text_gets_marker():
    """TC-CON-051 | _truncate 超长文本被截断并附加标记

    输入: "x" * (MAX_RESPONSE_CHARS + 100)
    预期输出: 前 MAX_RESPONSE_CHARS 字符 + TRUNCATION_MARKER
    断言点: 返回值长度 == MAX_RESPONSE_CHARS + len(marker) + 末尾含 marker
    防回归: 若截断逻辑被删除，返回原始长文本
    """
    long_text = "x" * (MAX_RESPONSE_CHARS + 100)
    result = _truncate(long_text)
    assert result.endswith(TRUNCATION_MARKER)
    assert len(result) == MAX_RESPONSE_CHARS + len(TRUNCATION_MARKER)


def test_debug_proxy_unknown_feature_returns_404(client, auth_headers):
    """TC-CON-052 | debug-proxy 未知 feature 返回 404

    输入: POST /debug-proxy/unknown
    预期输出: 404，detail=="Unknown feature"
    断言点: HTTP 404 + detail=="Unknown feature"
    防回归: 若 feature 校验被删除，后续 SERVICE_URL_DEFAULTS KeyError
    """
    resp = client.post(
        "/api/v1/debug-proxy/unknown",
        headers=auth_headers,
        json={"method": "GET", "path": "/test"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Unknown feature"


def test_debug_proxy_with_body_sends_json(client, auth_headers, monkeypatch):
    """TC-CON-053 | debug-proxy 携带 body 时设置 Content-Type: application/json

    输入: POST /debug-proxy/registry，body.body={"k":"v"}
    预期输出: 200，handler 收到 Content-Type=application/json + kind=="json"
    断言点: HTTP 200 + kind=="json" + handler 收到 content-type
    防回归: 若 body 分支被删除，handler 不收到 content-type
    """
    captured = {}

    def handler(request):
        captured["content_type"] = request.headers.get("content-type", "")
        return httpx.Response(200, json={"echo": "ok"})

    _mock_async_client(monkeypatch, debug_proxy_router, handler)
    resp = client.post(
        "/api/v1/debug-proxy/registry",
        headers=auth_headers,
        json={"method": "POST", "path": "/test", "body": {"k": "v"}},
    )
    assert resp.status_code == 200
    assert resp.json()["kind"] == "json"
    assert "application/json" in captured["content_type"]


def test_debug_proxy_stream_content_type(client, auth_headers, monkeypatch):
    """TC-CON-054 | debug-proxy 流式 content-type 返回 transcript

    输入: POST /debug-proxy/registry，mock 返回 content-type=text/event-stream
    预期输出: 200，kind=="stream"，transcript 含响应内容
    断言点: kind=="stream" + transcript 含 "data chunk"
    防回归: 若流式分支被删除，回退到 text/json 解析
    """
    def handler(request):
        return httpx.Response(
            200,
            content=b"data chunk\n",
            headers={"content-type": "text/event-stream"},
        )

    _mock_async_client(monkeypatch, debug_proxy_router, handler)
    resp = client.post(
        "/api/v1/debug-proxy/registry",
        headers=auth_headers,
        json={"method": "GET", "path": "/stream"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "stream"
    assert "data chunk" in body["transcript"]


def test_debug_proxy_text_response(client, auth_headers, monkeypatch):
    """TC-CON-055 | debug-proxy 非 JSON 文本响应返回 kind=text

    输入: POST /debug-proxy/registry，mock 返回纯文本（非 JSON）
    预期输出: 200，kind=="text"，body 含原始文本
    断言点: kind=="text" + body=="plain response"
    防回归: 若 ValueError 回退分支被删除，500 错误
    """
    def handler(request):
        return httpx.Response(
            200,
            content=b"plain response",
            headers={"content-type": "text/plain"},
        )

    _mock_async_client(monkeypatch, debug_proxy_router, handler)
    resp = client.post(
        "/api/v1/debug-proxy/registry",
        headers=auth_headers,
        json={"method": "GET", "path": "/text"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "text"
    assert body["body"] == "plain response"


def test_debug_proxy_httpx_error_returns_status_zero(client, auth_headers, monkeypatch):
    """TC-CON-056 | debug-proxy httpx 连接错误返回 status=0

    输入: POST /debug-proxy/registry，mock httpx 抛 ConnectError
    预期输出: 200，kind=="error"，status==0
    断言点: status==0 + kind=="error" + body.error 含异常信息
    防回归: 若异常分支被删除，500 错误
    """
    def handler(request):
        raise httpx.ConnectError("upstream down")

    _mock_async_client(monkeypatch, debug_proxy_router, handler)
    resp = client.post(
        "/api/v1/debug-proxy/registry",
        headers=auth_headers,
        json={"method": "GET", "path": "/test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == 0
    assert body["kind"] == "error"
    assert "upstream down" in body["body"]["error"]


def test_debug_proxy_stream_truncation(client, auth_headers, monkeypatch):
    """TC-CON-058 | debug-proxy 流式响应超长时截断并附加标记

    输入: POST /debug-proxy/registry，mock 返回 content-type=text/event-stream，body 超 MAX_RESPONSE_CHARS
    预期输出: 200，kind=="stream"，transcript 以 TRUNCATION_MARKER 结尾
    断言点: kind=="stream" + transcript 末尾含 TRUNCATION_MARKER
    防回归: 若 size >= MAX_RESPONSE_CHARS break 被删除，读取全部内容不截断
    """
    big_body = ("x" * (MAX_RESPONSE_CHARS + 5000)).encode("utf-8")

    def handler(request):
        return httpx.Response(
            200,
            content=big_body,
            headers={"content-type": "text/event-stream"},
        )

    _mock_async_client(monkeypatch, debug_proxy_router, handler)
    resp = client.post(
        "/api/v1/debug-proxy/registry",
        headers=auth_headers,
        json={"method": "GET", "path": "/big-stream"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "stream"
    assert body["transcript"].endswith(TRUNCATION_MARKER)


def test_debug_proxy_without_auth_returns_401(client):
    """TC-CON-057 | debug-proxy 无 token 返回 401

    输入: POST /debug-proxy/registry 无 Authorization
    预期输出: 401
    断言点: HTTP 401
    防回归: 若鉴权依赖被删除，返回 200 或 422
    """
    resp = client.post(
        "/api/v1/debug-proxy/registry",
        json={"method": "GET", "path": "/test"},
    )
    assert resp.status_code == 401


def test_debug_proxy_invalid_method_returns_422(client, auth_headers):
    """TC-CON-058 | debug-proxy 非法 method 返回 422

    输入: POST /debug-proxy/registry，method="TRACE"（不在 pattern 中）
    预期输出: 422
    断言点: HTTP 422
    防回归: 若 method pattern 校验被删除，非法 method 进入 httpx
    """
    resp = client.post(
        "/api/v1/debug-proxy/registry",
        headers=auth_headers,
        json={"method": "TRACE", "path": "/test"},
    )
    assert resp.status_code == 422


# ===================================================================
# settings_router
# ===================================================================

def test_get_service_urls_returns_defaults(client, auth_headers):
    """TC-CON-059 | GET service-urls 返回默认值

    输入: GET /settings/service-urls
    预期输出: 200，含 registryUrl / orchestrationUrl / executionHostUrl / ontologyUrl
    断言点: 四个字段都存在且非空
    防回归: 若 _service_urls_view 被改坏，字段缺失或为空
    """
    resp = client.get("/api/v1/settings/service-urls", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    for field in ("registryUrl", "orchestrationUrl", "executionHostUrl", "ontologyUrl"):
        assert data[field]


def test_put_service_urls_updates_existing(app, client, auth_headers):
    """TC-CON-060 | PUT service-urls 更新已存在的行

    输入: PUT /settings/service-urls，registryUrl="http://new-registry:5000"
    预期输出: 200，registryUrl==新值
    断言点: 返回的 registryUrl 等于新值
    防回归: 若 update 分支被删除，值不改变
    """
    resp = client.put(
        "/api/v1/settings/service-urls",
        headers=auth_headers,
        json={"registryUrl": "http://new-registry:5000"},
    )
    assert resp.status_code == 200
    assert resp.json()["registryUrl"] == "http://new-registry:5000"


def test_put_service_urls_skips_none_values(client, auth_headers):
    """TC-CON-061 | PUT service-urls 跳过 None 值

    输入: PUT /settings/service-urls，仅设置 ontologyUrl，其余为 null
    预期输出: 200，ontologyUrl 更新，registryUrl 保持默认
    断言点: ontologyUrl==新值 + registryUrl 含默认 203.0.113.10
    防回归: 若 None 跳过逻辑被删除，其他字段被置空
    """
    resp = client.put(
        "/api/v1/settings/service-urls",
        headers=auth_headers,
        json={"ontologyUrl": "http://new-ontology:8787", "registryUrl": None},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ontologyUrl"] == "http://new-ontology:8787"
    assert "203.0.113.10" in data["registryUrl"]


def test_put_service_urls_inserts_new_row(app, client, auth_headers):
    """TC-CON-062 | PUT service-urls 当行不存在时插入新行

    输入: 删除 registry_url 行后 PUT，registryUrl="http://inserted:5000"
    预期输出: 200，registryUrl==新值
    断言点: 返回的 registryUrl 等于新值
    防回归: 若 insert 分支被删除，db.scalar 返回 None 后 AttributeError
    """
    with Session(app.state.engine) as db:
        row = db.scalar(select(ServiceSettings).where(ServiceSettings.key == "registry_url"))
        if row is not None:
            db.delete(row)
            db.commit()
    resp = client.put(
        "/api/v1/settings/service-urls",
        headers=auth_headers,
        json={"registryUrl": "http://inserted:5000"},
    )
    assert resp.status_code == 200
    assert resp.json()["registryUrl"] == "http://inserted:5000"


def test_put_service_urls_non_admin_returns_403(app, client):
    """TC-CON-063 | PUT service-urls 非 admin 返回 403

    输入: 创建 reader 用户，reader 登录后 PUT /settings/service-urls
    预期输出: 403，detail=="Admin required"
    断言点: HTTP 403 + detail=="Admin required"
    防回归: 若 require_admin 依赖被删除，非 admin 可修改设置
    """
    with Session(app.state.engine) as db:
        db.add(User(username="setter", role="user", password_hash=hash_password("setter-pass")))
        db.commit()
    headers = _user_headers(client, "setter", "setter-pass")
    resp = client.put(
        "/api/v1/settings/service-urls",
        headers=headers,
        json={"registryUrl": "http://forbidden:5000"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin required"


def test_put_service_urls_without_auth_returns_401(client):
    """TC-CON-064 | PUT service-urls 无 token 返回 401

    输入: PUT /settings/service-urls 无 Authorization
    预期输出: 401
    断言点: HTTP 401
    防回归: 若鉴权依赖被删除，返回 200 或 422
    """
    resp = client.put(
        "/api/v1/settings/service-urls",
        json={"registryUrl": "http://no-auth:5000"},
    )
    assert resp.status_code == 401


def test_put_service_urls_invalid_url_returns_422(client, auth_headers):
    """TC-CON-065 | PUT service-urls 非 http(s) URL 返回 422

    输入: PUT /settings/service-urls，registryUrl="ftp://bad"
    预期输出: 422
    断言点: HTTP 422
    防回归: 若 URL 校验被删除，非法协议写入 DB
    """
    resp = client.put(
        "/api/v1/settings/service-urls",
        headers=auth_headers,
        json={"registryUrl": "ftp://bad"},
    )
    assert resp.status_code == 422


# ===================================================================
# registry_router
# ===================================================================

def test_list_samples_returns_sorted_samples(client, auth_headers):
    """TC-CON-066 | GET /registry/samples 返回按 key 排序的样例列表

    输入: GET /registry/samples
    预期输出: 200，非空列表，按 key 升序
    断言点: 列表非空 + keys 升序
    防回归: 若 load_samples 被改坏，返回空或未排序
    """
    from mockagent_engine.routers.registry_router import load_samples

    load_samples.cache_clear()
    resp = client.get("/api/v1/registry/samples", headers=auth_headers)
    assert resp.status_code == 200
    samples = resp.json()
    assert isinstance(samples, list)
    assert len(samples) > 0
    keys = [s.get("key", "") for s in samples]
    assert keys == sorted(keys)


def test_list_samples_without_auth_returns_401(client):
    """TC-CON-067 | GET /registry/samples 无 token 返回 401

    输入: GET /registry/samples 无 Authorization
    预期输出: 401
    断言点: HTTP 401
    防回归: 若鉴权依赖被删除，返回 200
    """
    assert client.get("/api/v1/registry/samples").status_code == 401
