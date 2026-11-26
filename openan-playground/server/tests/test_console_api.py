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

import json

import httpx
import pytest
from a2a_t.core.metadata import TASK_T_EXTENSION_URI
from sqlalchemy import select
from sqlalchemy.orm import Session

from openan_debug.models import RequestLog
from openan_debug.routers import console_router
from tests.conftest import auth_header

DEFAULT_EXTENSION = console_router.DEFAULT_EXTENSION


def _request_body(template_uri=None):
    metadata = {"templateUri": template_uri} if template_uri else {}
    return {
        "message": {
            "messageId": "m-1",
            "role": "ROLE_USER",
            "parts": [{"text": "hi"}],
            "metadata": metadata,
        }
    }


def _install_mock_backend(monkeypatch, handler):
    real_client_factory = httpx.AsyncClient

    def fake_client_factory(**kwargs):
        return real_client_factory(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(console_router.httpx, "AsyncClient", fake_client_factory)


def _create_agent(client, admin_token, name, organization="OpenAN"):
    resp = client.post(
        "/api/v1/agents",
        json={"name": name, "organization": organization, "description": "scoped"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _default_agent_id(client, admin_token):
    agents = client.get("/api/v1/agents", headers=auth_header(admin_token)).json()
    return next(a["id"] for a in agents if a["isDefault"])


def _write_define(tmp_path, instances):
    path = tmp_path / "mock_agent_define.json"
    path.write_text(json.dumps({"instances": instances}, ensure_ascii=False), encoding="utf-8")
    return path


_SCOPED_INSTANCE = {
    "id": "inst-scoped",
    "name": "Scoped Agent One",
    "organization": "OpenAN",
    "port": 9301,
    "datasetTemplates": [
        "Task-T/private-line-complaint/v1",
        "Notification-T/network-layer/subscribe-incident/v1",
    ],
}


class _MissingResource:
    def joinpath(self, _name):
        return self

    def read_text(self, encoding=None):
        raise OSError("simulated missing dataset file")


def _install_missing_resources(monkeypatch):
    monkeypatch.setattr(console_router.importlib_resources, "files", lambda _pkg: _MissingResource())


def _last_console_log(client):
    with Session(client.app.state.engine) as session:
        return session.scalar(
            select(RequestLog).where(RequestLog.direction == "console").order_by(RequestLog.id.desc())
        )


# ---------------------------------------------------------------------------
# Pure helper function unit tests
# ---------------------------------------------------------------------------


def test_local_base_strips_suffix_and_passthrough():
    """TC-DCON-001 | _local_base 按后缀剥离，无后缀原样返回

    输入: 带 /debug/a2a/message:send 后缀的 url；不带后缀的 url
    预期输出: 前者返回去掉后缀的基址；后者原样返回
    断言点: 返回值精确等于期望基址/原 url
    防回归: 若后缀判定被改为 startswith 或长度计算错误，基址会错
    """
    assert console_router._local_base("http://h:9/debug/a2a/message:send") == "http://h:9"
    assert console_router._local_base("http://h:9/foo") == "http://h:9/foo"


def test_derive_extension_mapping_and_default():
    """TC-DCON-002 | _derive_extension 按 templateUri 前缀映射，无则取默认扩展

    输入: Task-T 前缀 templateUri；无 templateUri 的请求体
    预期输出: Task-T 映射到 TASK_T_EXTENSION_URI；无则 DEFAULT_EXTENSION
    断言点: 返回值分别等于两个常量
    防回归: 若前缀表或默认回退被删除，扩展头会错
    """
    assert (
        console_router._derive_extension({"message": {"metadata": {"templateUri": "Task-T/private-line-complaint/v1"}}})
        == TASK_T_EXTENSION_URI
    )
    assert console_router._derive_extension({"message": {"metadata": {}}}) == DEFAULT_EXTENSION
    assert console_router._derive_extension({}) == DEFAULT_EXTENSION


def test_extract_task_state_branches():
    """TC-DCON-003 | _extract_task_state 全分支：非 dict/ task 非 dict/ status 非 dict/ 取 state

    输入: 四类响应结构
    预期输出: 非 dict→None；task 非 dict→None；status 非 dict→None；正常→state 字符串
    断言点: 每个分支返回值精确
    防回归: 若任一 isinstance 守卫被删，会抛 AttributeError 或取错值
    """
    assert console_router._extract_task_state([1, 2]) is None
    assert console_router._extract_task_state({"task": "x"}) is None
    assert console_router._extract_task_state({"task": {"status": "x"}}) is None
    assert console_router._extract_task_state({"task": {}}) is None
    assert (
        console_router._extract_task_state({"task": {"status": {"state": "TASK_STATE_COMPLETED"}}})
        == "TASK_STATE_COMPLETED"
    )


def test_dataset_file_for_lang_selection_and_fallback():
    """TC-DCON-004 | _dataset_file_for 语言选择与英文缺失回退中文

    输入: seed/expanded × None/en；en 文件加载失败时回退
    预期输出: en 选 *_en.json；en 加载抛错时回退 base 文件名
    断言点: 返回文件名精确
    防回归: 若回退分支被删，en 文件缺失会抛错而非回退
    """
    assert console_router._dataset_file_for("seed", None) == "demo_dataset.json"
    assert console_router._dataset_file_for("expanded", None) == "expanded_dataset.json"
    assert console_router._dataset_file_for("seed", "en") == "demo_dataset_en.json"
    assert console_router._dataset_file_for("expanded", "en") == "expanded_dataset_en.json"

    def _raising_loader(_filename):
        raise OSError("nope")

    monkeypatch_local = pytest.MonkeyPatch()
    monkeypatch_local.setattr(console_router, "_load_dataset_file", _raising_loader)
    try:
        assert console_router._dataset_file_for("seed", "en") == "demo_dataset.json"
    finally:
        monkeypatch_local.undo()


def test_load_dataset_file_caches():
    """TC-DCON-005 | _load_dataset_file 首次加载后缓存同一对象

    输入: 同一文件名连续两次加载
    预期输出: 第二次返回缓存中的同一 dict 对象
    断言点: 返回对象身份一致（is）
    防回归: 若缓存写入被删，第二次会重复读文件
    """
    console_router._DATASET_CACHE.clear()
    first = console_router._load_dataset_file("demo_dataset.json")
    assert "pairs" in first
    second = console_router._load_dataset_file("demo_dataset.json")
    assert second is first


def test_dataset_template_counts_success_and_missing():
    """TC-DCON-006 | _dataset_template_counts 正常计数与某文件缺失时跳过

    输入: 真实两份数据集；expanded 加载失败
    预期输出: 正常返回 seed/expanded 计数；expanded 失败则只剩 seed
    断言点: seed 计数含 private-line-complaint=4；失败时 expanded 键不存在
    防回归: 若 except continue 被删，单文件缺失会整体抛错
    """
    counts = console_router._dataset_template_counts()
    assert counts["seed"]["Task-T/private-line-complaint/v1"] == 4
    assert "expanded" in counts

    real = console_router._load_dataset_file

    def _selective(filename):
        if filename == "expanded_dataset.json":
            raise OSError("nope")
        return real(filename)

    monkeypatch_local = pytest.MonkeyPatch()
    monkeypatch_local.setattr(console_router, "_load_dataset_file", _selective)
    try:
        partial = console_router._dataset_template_counts()
    finally:
        monkeypatch_local.undo()
    assert "seed" in partial
    assert "expanded" not in partial


def test_agent_scopes_with_define(tmp_path, monkeypatch):
    """TC-DCON-007 | _agent_scopes 含内嵌默认范围与实例范围

    输入: define 含一个实例
    预期输出: 返回 [默认(无模板), 实例(scoped 模板列表)]
    断言点: 长度 2；默认 scoped=False/datasetTemplates=None；实例 scoped=True 且模板列表一致
    防回归: 若默认 scope 或实例遍历被删，结构会缺项
    """
    monkeypatch.setenv("OPENAN_DEBUG_MOCK_DEFINE", str(_write_define(tmp_path, [_SCOPED_INSTANCE])))
    scopes = console_router._agent_scopes()
    assert len(scopes) == 2
    assert scopes[0]["instanceId"] is None
    assert scopes[0]["scoped"] is False
    assert scopes[0]["datasetTemplates"] is None
    assert scopes[1]["instanceId"] == "inst-scoped"
    assert scopes[1]["scoped"] is True
    assert scopes[1]["datasetTemplates"] == _SCOPED_INSTANCE["datasetTemplates"]


# ---------------------------------------------------------------------------
# POST /api/v1/console/send
# ---------------------------------------------------------------------------


def test_console_send_default_agent_url_and_log(client, admin_token, monkeypatch):
    """TC-DCON-008 | 发送到默认 Agent：目标为内嵌 URL 且写日志

    输入: agentId=default，mock 远端 200 带 task state
    预期输出: status=200；task_state 记录到 RequestLog；日志 agent_id=default
    断言点: 返回 status/response；日志 task_state 与 agent_id
    防回归: 若默认 Agent 短路或日志写入被删，断言失败
    """
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"task": {"status": {"state": "TASK_STATE_COMPLETED"}}})

    _install_mock_backend(monkeypatch, handler)
    default_id = _default_agent_id(client, admin_token)
    resp = client.post(
        "/api/v1/console/send",
        json={"request": _request_body(), "agentId": default_id},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == 200
    assert captured["url"].endswith("/debug/a2a/message:send")
    log = _last_console_log(client)
    assert log.agent_id == default_id
    assert log.task_state == "TASK_STATE_COMPLETED"


def test_console_send_no_agent_uses_default_url(client, admin_token, monkeypatch):
    """TC-DCON-009 | agentId 缺省时走默认内嵌 URL，日志归默认 Agent

    输入: agentId=None，mock 远端 200
    预期输出: 目标为 agent_internal_url；日志 agent_id=default
    断言点: 捕获 URL 后缀；日志 agent_id=default
    防回归: 若 None 分支不再回退默认 URL，会 404
    """
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    _install_mock_backend(monkeypatch, handler)
    default_id = _default_agent_id(client, admin_token)
    resp = client.post(
        "/api/v1/console/send",
        json={"request": _request_body()},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert captured["url"].endswith("/debug/a2a/message:send")
    assert _last_console_log(client).agent_id == default_id


def test_console_send_created_agent_url(client, admin_token, monkeypatch):
    """TC-DCON-010 | 发送到已创建非默认 Agent：目标含 /agent/{id}/ 前缀

    输入: agentId=新建 Agent，mock 远端 200
    预期输出: 目标 URL 含 /debug/a2a/agent/{id}/message:send；日志 agent_id=新建
    断言点: 捕获 URL 后缀；日志 agent_id
    防回归: 若 _local_base 剥离或 agent 路径拼接被改，URL 会错
    """
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    _install_mock_backend(monkeypatch, handler)
    created = _create_agent(client, admin_token, name="Scoped Agent One")
    resp = client.post(
        "/api/v1/console/send",
        json={"request": _request_body(), "agentId": created["id"]},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert captured["url"].endswith(f"/debug/a2a/agent/{created['id']}/message:send")
    assert _last_console_log(client).agent_id == created["id"]


def test_console_send_unknown_agent_404(client, admin_token):
    """TC-DCON-011 | 发送到不存在 Agent → 404

    输入: agentId=9999
    预期输出: HTTP 404
    断言点: 状态码 404
    防回归: 若 Agent not found 守卫被删，会继续发请求
    """
    resp = client.post(
        "/api/v1/console/send",
        json={"request": _request_body(), "agentId": 9999},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 404


def test_console_send_disabled_agent_409(client, admin_token):
    """TC-DCON-012 | 发送到已禁用非默认 Agent → 409

    输入: agentId=已禁用 Agent
    预期输出: HTTP 409
    断言点: 状态码 409
    防回归: 若 enabled 守卫被删，会向禁用 Agent 发请求
    """
    created = _create_agent(client, admin_token, name="To Disable")
    client.patch(f"/api/v1/agents/{created['id']}", json={"enabled": False}, headers=auth_header(admin_token))
    resp = client.post(
        "/api/v1/console/send",
        json={"request": _request_body(), "agentId": created["id"]},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 409


def test_console_send_instance_running_with_agent_match(client, admin_token, tmp_path, monkeypatch):
    """TC-DCON-013 | 发送到运行中实例且 DB 有匹配 Agent：目标为实例端口且日志归匹配 Agent

    输入: instanceId=运行中实例(org/name 匹配已建 Agent)，mock 健康探测与远端
    预期输出: 目标 http://127.0.0.1:{port}/message:send；日志 agent_id=匹配 Agent
    断言点: 捕获 URL；日志 agent_id
    防回归: 若实例 Agent 匹配查询被删，日志 agent_id 会回退默认
    """
    monkeypatch.setenv("OPENAN_DEBUG_MOCK_DEFINE", str(_write_define(tmp_path, [_SCOPED_INSTANCE])))
    monkeypatch.setattr(console_router, "_health_probe", lambda port, timeout=1.0: True)
    created = _create_agent(client, admin_token, name="Scoped Agent One")
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"task": {"status": {"state": "TASK_STATE_COMPLETED"}}})

    _install_mock_backend(monkeypatch, handler)
    resp = client.post(
        "/api/v1/console/send",
        json={"request": _request_body(), "instanceId": "inst-scoped"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert captured["url"] == "http://127.0.0.1:9301/message:send"
    assert _last_console_log(client).agent_id == created["id"]


def test_console_send_instance_running_no_agent_match(client, admin_token, tmp_path, monkeypatch):
    """TC-DCON-014 | 运行中实例但 DB 无匹配 Agent：日志归默认 Agent

    输入: instanceId=运行中实例(org/name 无匹配 Agent)
    预期输出: 目标仍为实例端口；日志 agent_id=default
    断言点: 捕获 URL；日志 agent_id=default
    防回归: 若无匹配回退默认被改，日志 agent_id 会 None
    """
    no_match_inst = {
        "id": "inst-nomatch",
        "name": "No Match Agent",
        "organization": "OpenAN",
        "port": 9302,
    }
    monkeypatch.setenv("OPENAN_DEBUG_MOCK_DEFINE", str(_write_define(tmp_path, [no_match_inst])))
    monkeypatch.setattr(console_router, "_health_probe", lambda port, timeout=1.0: True)
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    _install_mock_backend(monkeypatch, handler)
    default_id = _default_agent_id(client, admin_token)
    resp = client.post(
        "/api/v1/console/send",
        json={"request": _request_body(), "instanceId": "inst-nomatch"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert captured["url"] == "http://127.0.0.1:9302/message:send"
    assert _last_console_log(client).agent_id == default_id


def test_console_send_instance_not_running_409(client, admin_token, tmp_path, monkeypatch):
    """TC-DCON-015 | 实例端口<=0 视为未运行 → 409

    输入: instanceId=port=0 的实例
    预期输出: HTTP 409，detail 含"未运行"
    断言点: 状态码 409 + detail 关键字
    防回归: 若 port<=0 守卫被删，会尝试连接端口 0
    """
    stopped = {"id": "inst-stopped", "name": "Stopped", "organization": "OpenAN", "port": 0}
    monkeypatch.setenv("OPENAN_DEBUG_MOCK_DEFINE", str(_write_define(tmp_path, [stopped])))
    resp = client.post(
        "/api/v1/console/send",
        json={"request": _request_body(), "instanceId": "inst-stopped"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 409
    assert "未运行" in resp.json()["detail"]


def test_console_send_instance_unhealthy_409(client, admin_token, tmp_path, monkeypatch):
    """TC-DCON-016 | 实例端口>0 但健康探测失败 → 409

    输入: instanceId=port>0 的实例，_health_probe 强制 False
    预期输出: HTTP 409，detail 含"未运行"
    断言点: 状态码 409 + detail 关键字
    防回归: 若 not _health_probe 短路被改，会向死端口发请求
    """
    inst = {"id": "inst-dead", "name": "Dead", "organization": "OpenAN", "port": 9999}
    monkeypatch.setenv("OPENAN_DEBUG_MOCK_DEFINE", str(_write_define(tmp_path, [inst])))
    monkeypatch.setattr(console_router, "_health_probe", lambda port, timeout=1.0: False)
    resp = client.post(
        "/api/v1/console/send",
        json={"request": _request_body(), "instanceId": "inst-dead"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 409
    assert "未运行" in resp.json()["detail"]


def test_console_send_http_error_logs_status_zero(client, admin_token, monkeypatch):
    """TC-DCON-017 | 远端 httpx 抛错：返回 status=0 并写错误日志

    输入: mock handler 抛 httpx.ConnectError
    预期输出: 返回 status=0，response 含 error；日志 response_body status=0
    断言点: 返回 status/response；日志 status=0
    防回归: 若 except HTTPError 被删，异常会冒泡成 500
    """
    def handler(_request):
        raise httpx.ConnectError("boom")

    _install_mock_backend(monkeypatch, handler)
    resp = client.post(
        "/api/v1/console/send",
        json={"request": _request_body()},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == 0
    assert "boom" in body["response"]["error"]
    log = _last_console_log(client)
    assert log.response_body["status"] == 0
    assert log.task_state is None


def test_console_send_non_json_response_raw_fallback(client, admin_token, monkeypatch):
    """TC-DCON-018 | 远端返回非 JSON：回退 {"raw": text} 且 task_state=None

    输入: mock 返回 200 + text/plain 非 JSON
    预期输出: response={"raw": "not-json"}；status=200；日志 task_state=None
    断言点: 返回 response/status；日志 task_state
    防回归: 若 ValueError 捕获被删，非 JSON 会抛 500
    """
    def handler(_request):
        return httpx.Response(200, content=b"not-json", headers={"content-type": "text/plain"})

    _install_mock_backend(monkeypatch, handler)
    resp = client.post(
        "/api/v1/console/send",
        json={"request": _request_body()},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == 200
    assert resp.json()["response"] == {"raw": "not-json"}
    assert _last_console_log(client).task_state is None


def test_console_send_sets_extension_header_from_template(client, admin_token, monkeypatch):
    """TC-DCON-019 | templateUri 前缀映射写入 A2A-Extensions 请求头

    输入: request.message.metadata.templateUri=Task-T/...
    预期输出: 远端收到的 A2A-Extensions 头 == TASK_T_EXTENSION_URI
    断言点: 捕获的请求头值
    防回归: 若 _derive_extension 被绕过，扩展头会变成默认值
    """
    captured = {}

    def handler(request):
        captured["ext"] = request.headers.get("A2A-Extensions")
        return httpx.Response(200, json={"ok": True})

    _install_mock_backend(monkeypatch, handler)
    client.post(
        "/api/v1/console/send",
        json={"request": _request_body("Task-T/private-line-complaint/v1")},
        headers=auth_header(admin_token),
    )
    assert captured["ext"] == TASK_T_EXTENSION_URI


def test_console_send_default_extension_when_no_template(client, admin_token, monkeypatch):
    """TC-DCON-020 | 无 templateUri 时 A2A-Extensions 取 DEFAULT_EXTENSION

    输入: request 无 templateUri
    预期输出: 远端收到的 A2A-Extensions 头 == DEFAULT_EXTENSION
    断言点: 捕获的请求头值
    防回归: 若默认回退被删，扩展头会为空
    """
    captured = {}

    def handler(request):
        captured["ext"] = request.headers.get("A2A-Extensions")
        return httpx.Response(200, json={"ok": True})

    _install_mock_backend(monkeypatch, handler)
    client.post(
        "/api/v1/console/send",
        json={"request": _request_body()},
        headers=auth_header(admin_token),
    )
    assert captured["ext"] == DEFAULT_EXTENSION


def test_console_send_unauthorized_401(client):
    """TC-DCON-021 | 未认证访问 /console/send → 401

    输入: 无 Authorization 头
    预期输出: HTTP 401
    断言点: 状态码 401
    防回归: 若 get_current_user 依赖被删，匿名可发送
    """
    assert client.post("/api/v1/console/send", json={"request": _request_body()}).status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/console/trace-prompts
# ---------------------------------------------------------------------------


def test_trace_prompts_returns_examples(client, admin_token):
    """TC-DCON-022 | trace-prompts 返回实采示例数据

    输入: 已认证 GET
    预期输出: 200，含 examples 列表
    断言点: 状态码 + examples 非空且每项有 id/templateUri
    防回归: 若文件读取被改，examples 会缺失
    """
    resp = client.get("/api/v1/console/trace-prompts", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    examples = resp.json()["examples"]
    assert examples
    assert all("id" in e and "templateUri" in e for e in examples)


def test_trace_prompts_missing_file_404(client, admin_token, monkeypatch):
    """TC-DCON-023 | trace_examples.json 不可读 → 404

    输入: importlib_resources.files 被替换为抛 OSError 的桩
    预期输出: HTTP 404，detail 含"实采 prompt 数据不可用"
    断言点: 状态码 404 + detail 关键字
    防回归: 若 except 分支被删，OSError 会冒泡成 500
    """
    _install_missing_resources(monkeypatch)
    resp = client.get("/api/v1/console/trace-prompts", headers=auth_header(admin_token))
    assert resp.status_code == 404
    assert "实采 prompt 数据不可用" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/v1/console/demo-dataset
# ---------------------------------------------------------------------------


def test_demo_dataset_returns_seed(client, admin_token):
    """TC-DCON-024 | demo-dataset 返回中文种子数据集

    输入: 已认证 GET（无 lang）
    预期输出: 200，datasetId=seed，pairs 8 条
    断言点: datasetId + pairCount + 首条 pairId
    防回归: 若文件名选择被改，会返回错误数据集
    """
    resp = client.get("/api/v1/console/demo-dataset", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["datasetId"] == "seed"
    assert len(data["pairs"]) == 8
    assert data["pairs"][0]["pairId"] == "demo-pair-1"


def test_demo_dataset_lang_en(client, admin_token):
    """TC-DCON-025 | demo-dataset?lang=en 返回英文数据集

    输入: lang=en
    预期输出: 200，name 为英文标题
    断言点: name == "A2A-T Demo Seed Dataset"
    防回归: 若 _dataset_file_for en 分支被删，会回退中文
    """
    resp = client.get("/api/v1/console/demo-dataset?lang=en", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "A2A-T Demo Seed Dataset"


def test_demo_dataset_missing_file_404(client, admin_token, monkeypatch):
    """TC-DCON-026 | demo-dataset 文件不可读 → 404

    输入: importlib_resources.files 被替换为抛 OSError 的桩
    预期输出: HTTP 404，detail 含"Demo 数据集不可用"
    断言点: 状态码 404 + detail 关键字
    防回归: 若 except 分支被删，OSError 会冒泡成 500
    """
    _install_missing_resources(monkeypatch)
    resp = client.get("/api/v1/console/demo-dataset", headers=auth_header(admin_token))
    assert resp.status_code == 404
    assert "Demo 数据集不可用" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/v1/console/datasets
# ---------------------------------------------------------------------------


def test_list_datasets_returns_both(client, admin_token):
    """TC-DCON-027 | datasets 返回 seed + expanded 两个数据集元信息

    输入: 已认证 GET
    预期输出: 200，datasets 含 seed(expanded) 两项，seed pairCount=8
    断言点: id 顺序 + seed pairCount + expanded pairCount>0
    防回归: 若某数据集加载被删，会少一项
    """
    resp = client.get("/api/v1/console/datasets", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    datasets = resp.json()["datasets"]
    assert [d["id"] for d in datasets] == ["seed", "expanded"]
    seed = next(d for d in datasets if d["id"] == "seed")
    expanded = next(d for d in datasets if d["id"] == "expanded")
    assert seed["pairCount"] == 8
    assert expanded["pairCount"] > 0


def test_list_datasets_lang_en(client, admin_token):
    """TC-DCON-028 | datasets?lang=en 返回英文版元信息

    输入: lang=en
    预期输出: seed name 为英文标题
    断言点: seed name == "A2A-T Demo Seed Dataset"
    防回归: 若 en 分支被删，回退中文 name
    """
    resp = client.get("/api/v1/console/datasets?lang=en", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    seed = next(d for d in resp.json()["datasets"] if d["id"] == "seed")
    assert seed["name"] == "A2A-T Demo Seed Dataset"


def test_list_datasets_missing_returns_empty(client, admin_token, monkeypatch):
    """TC-DCON-029 | datasets 文件全部不可读 → 返回空列表

    输入: importlib_resources.files 被替换为抛 OSError 的桩
    预期输出: 200，datasets=[]
    断言点: datasets 为空列表
    防回归: 若 except data=None 回退被删，会抛 500
    """
    console_router._DATASET_CACHE.clear()
    _install_missing_resources(monkeypatch)
    resp = client.get("/api/v1/console/datasets", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["datasets"] == []


def test_datasets_unauthorized_401(client):
    """TC-DCON-030 | 未认证访问 /console/datasets → 401

    输入: 无 Authorization 头
    预期输出: HTTP 401
    断言点: 状态码 401
    防回归: 若 get_current_user 依赖被删，匿名可读
    """
    assert client.get("/api/v1/console/datasets").status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/console/datasets/agent-associations
# ---------------------------------------------------------------------------


def test_dataset_agent_associations_with_define(client, admin_token, tmp_path, monkeypatch):
    """TC-DCON-031 | agent-associations 返回默认范围+实例范围关联视图

    输入: define 含一个 scoped 实例，且 DB 有同名 Agent
    预期输出: associations 含默认(scoped=False)与实例(scoped=True)两项；实例 agentRowId=匹配 Agent
    断言点: 长度 2；默认 templates 非空/scoped False；实例 scoped True/pairCounts/agentRowId
    防回归: 若默认或实例 scope 构建被删，结构会错
    """
    monkeypatch.setenv("OPENAN_DEBUG_MOCK_DEFINE", str(_write_define(tmp_path, [_SCOPED_INSTANCE])))
    created = _create_agent(client, admin_token, name="Scoped Agent One")
    resp = client.get("/api/v1/console/datasets/agent-associations", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    associations = resp.json()["associations"]
    assert len(associations) == 2
    default_assoc = next(a for a in associations if a["instanceId"] is None)
    inst_assoc = next(a for a in associations if a["instanceId"] == "inst-scoped")
    assert default_assoc["scoped"] is False
    assert default_assoc["templates"]
    assert default_assoc["agentRowId"] == _default_agent_id(client, admin_token)
    assert inst_assoc["scoped"] is True
    assert inst_assoc["agentRowId"] == created["id"]
    assert inst_assoc["agentEnabled"] is True
    assert inst_assoc["pairCounts"]["seed"] == 4
    assert inst_assoc["pairCounts"]["expanded"] == 864
    assert inst_assoc["templateCount"] == 2


def test_dataset_agent_associations_returns_default_scope(client, admin_token):
    """TC-DCON-032 | agent-associations 至少返回内嵌默认范围（使用仓库自带 define）

    输入: 已认证 GET（不覆盖 define）
    预期输出: 200，associations 含 instanceId=None 的默认范围且 scoped=False
    断言点: 状态码 200 + 默认范围 instanceId None + scoped False
    防回归: 若默认范围构建被删，首项不再是 instanceId None
    """
    resp = client.get("/api/v1/console/datasets/agent-associations", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    associations = resp.json()["associations"]
    assert associations
    default_assoc = next(a for a in associations if a["instanceId"] is None)
    assert default_assoc["scoped"] is False


# ---------------------------------------------------------------------------
# GET /api/v1/console/datasets/{ds_id}/pairs
# ---------------------------------------------------------------------------


def test_dataset_pairs_seed_basic(client, admin_token):
    """TC-DCON-033 | seed 数据集对分页（含预览瘦身）

    输入: GET pairs seed，默认分页
    预期输出: 200，total=8，items 8 条且含预览字段，protocols/templateUris 已排序
    断言点: total + items 长度 + 预览字段存在且长度<=160 + protocols 首项
    防回归: 若分页或预览拼接被改，结构会错
    """
    resp = client.get("/api/v1/console/datasets/seed/pairs", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["datasetId"] == "seed"
    assert body["total"] == 8
    assert body["page"] == 1
    assert body["pageSize"] == 20
    assert body["agentScopeTemplates"] is None
    assert len(body["items"]) == 8
    item = body["items"][0]
    assert "requestPromptPreview" in item
    assert len(item["requestPromptPreview"]) <= 160
    assert len(item["responseTextPreview"]) <= 160
    assert body["protocols"][0] == "Negotiation-T"
    assert body["templateUris"][0].startswith("Negotiation-T")


def test_dataset_pairs_expanded(client, admin_token):
    """TC-DCON-034 | expanded 数据集对分页

    输入: GET pairs expanded
    预期输出: 200，total>0，items<=pageSize，templateUris 非空
    断言点: total>0 + items 长度<=pageSize + templateUris 非空
    防回归: 若 expanded 加载被删，total=0
    """
    resp = client.get("/api/v1/console/datasets/expanded/pairs", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["datasetId"] == "expanded"
    assert body["total"] > 0
    assert len(body["items"]) <= body["pageSize"]
    assert body["templateUris"]


def test_dataset_pairs_unknown_ds_404(client, admin_token):
    """TC-DCON-035 | 未知数据集 id → 404

    输入: ds_id=bogus
    预期输出: HTTP 404，detail 含"未知数据集"
    断言点: 状态码 404 + detail 关键字
    防回归: 若 ds_id 校验被删，会尝试加载不存在的文件
    """
    resp = client.get("/api/v1/console/datasets/bogus/pairs", headers=auth_header(admin_token))
    assert resp.status_code == 404
    assert "未知数据集" in resp.json()["detail"]


def test_dataset_pairs_missing_file_404(client, admin_token, monkeypatch):
    """TC-DCON-036 | 数据集文件不可读 → 404

    输入: importlib_resources.files 被替换为抛 OSError 的桩
    预期输出: HTTP 404，detail 含"数据集不可用"
    断言点: 状态码 404 + detail 关键字
    防回归: 若 except 分支被删，OSError 会冒泡成 500
    """
    console_router._DATASET_CACHE.clear()
    _install_missing_resources(monkeypatch)
    resp = client.get("/api/v1/console/datasets/seed/pairs", headers=auth_header(admin_token))
    assert resp.status_code == 404
    assert "数据集不可用" in resp.json()["detail"]


def test_dataset_pairs_agent_filter_default(client, admin_token):
    """TC-DCON-037 | agentId=默认 Agent 时不限范围，返回全部对

    输入: agentId=default
    预期输出: agentScopeTemplates=None，total=8
    断言点: agentScopeTemplates + total
    防回归: 若默认 Agent 短路被删，会进入 scope 查询
    """
    default_id = _default_agent_id(client, admin_token)
    resp = client.get(
        f"/api/v1/console/datasets/seed/pairs?agentId={default_id}", headers=auth_header(admin_token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agentScopeTemplates"] is None
    assert body["total"] == 8


def test_dataset_pairs_agent_filter_scoped(client, admin_token, tmp_path, monkeypatch):
    """TC-DCON-038 | agentId=匹配实例 Agent 时按 datasetTemplates 过滤

    输入: define 含 scoped 实例，agentId=同名 Agent
    预期输出: agentScopeTemplates=实例模板，total=4（seed 中 private-line-complaint=4）
    断言点: agentScopeTemplates + total=4 + 所有 item templateUri 属于范围
    防回归: 若 scope 过滤被删，total 会是 8
    """
    monkeypatch.setenv("OPENAN_DEBUG_MOCK_DEFINE", str(_write_define(tmp_path, [_SCOPED_INSTANCE])))
    created = _create_agent(client, admin_token, name="Scoped Agent One")
    resp = client.get(
        f"/api/v1/console/datasets/seed/pairs?agentId={created['id']}", headers=auth_header(admin_token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agentScopeTemplates"] == _SCOPED_INSTANCE["datasetTemplates"]
    assert body["total"] == 4
    assert all(i["templateUri"] in _SCOPED_INSTANCE["datasetTemplates"] for i in body["items"])


def test_dataset_pairs_agent_filter_no_match_empty(client, admin_token, tmp_path, monkeypatch):
    """TC-DCON-039 | agentId=无实例匹配 Agent 时返回空

    输入: define 含 scoped 实例，agentId=不匹配的 Agent
    预期输出: agentScopeTemplates=None，total=0，items=[]
    断言点: agentScopeTemplates + total=0
    防回归: 若 scope_templates=None→[] 被改，会返回全部对
    """
    monkeypatch.setenv("OPENAN_DEBUG_MOCK_DEFINE", str(_write_define(tmp_path, [_SCOPED_INSTANCE])))
    lonely = _create_agent(client, admin_token, name="Lonely Agent")
    resp = client.get(
        f"/api/v1/console/datasets/seed/pairs?agentId={lonely['id']}", headers=auth_header(admin_token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agentScopeTemplates"] is None
    assert body["total"] == 0
    assert body["items"] == []


def test_dataset_pairs_protocol_filter(client, admin_token):
    """TC-DCON-040 | protocol 过滤仅返回该协议对

    输入: protocol=Task-T
    预期输出: total=6，所有 item protocol=Task-T
    断言点: total + 每个 item protocol
    防回归: 若 protocol 过滤被删，total=8
    """
    resp = client.get("/api/v1/console/datasets/seed/pairs?protocol=Task-T", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 6
    assert all(i["protocol"] == "Task-T" for i in body["items"])


def test_dataset_pairs_template_filter(client, admin_token):
    """TC-DCON-041 | templateUri 过滤仅返回该模板对

    输入: templateUri=Task-T/private-line-complaint/v1
    预期输出: total=4，所有 item templateUri 一致
    断言点: total + 每个 item templateUri
    防回归: 若 template 过滤被删，total=8
    """
    resp = client.get(
        "/api/v1/console/datasets/seed/pairs?templateUri=Task-T/private-line-complaint/v1",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 4
    assert all(i["templateUri"] == "Task-T/private-line-complaint/v1" for i in body["items"])


def test_dataset_pairs_query_filter(client, admin_token):
    """TC-DCON-042 | q 关键词搜索：匹配子集且不匹配项走 return False 分支

    输入: q=工单1（仅匹配 label 含"工单1"的对）
    预期输出: total=4（demo-pair-1/2/3/7），其余对被过滤
    断言点: total=4 且 < 全量 8；每条返回 item 的 label 含"工单1"
    防回归: 若 _match 的 return False 被删，未匹配对会泄漏进结果使 total 偏大
    """
    resp = client.get("/api/v1/console/datasets/seed/pairs?q=工单1", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 4
    assert all("工单1" in i["label"] for i in body["items"])


def test_dataset_pairs_pagesize_clamp(client, admin_token):
    """TC-DCON-043 | pageSize 越界被夹到 [1,100]

    输入: pageSize=0 与 pageSize=999
    预期输出: 分别夹为 1 与 100
    断言点: 返回 pageSize 值
    防回归: 若 max/min 夹取被删，pageSize 原样透传
    """
    r0 = client.get("/api/v1/console/datasets/seed/pairs?pageSize=0", headers=auth_header(admin_token))
    assert r0.status_code == 200
    assert r0.json()["pageSize"] == 1
    rbig = client.get("/api/v1/console/datasets/seed/pairs?pageSize=999", headers=auth_header(admin_token))
    assert rbig.json()["pageSize"] == 100


def test_dataset_pairs_pagination(client, admin_token):
    """TC-DCON-044 | 分页第二页返回偏移后的子集

    输入: page=2, pageSize=3
    预期输出: page=2，items 长度 3，首项为第 4 条(demo-pair-7)
    断言点: page + items 长度 + 首项 pairId
    防回归: 若 start 计算被改，首项会错
    """
    resp = client.get(
        "/api/v1/console/datasets/seed/pairs?page=2&pageSize=3", headers=auth_header(admin_token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page"] == 2
    assert body["total"] == 8
    assert len(body["items"]) == 3
    assert body["items"][0]["pairId"] == "demo-pair-7"


def test_dataset_pairs_unauthorized_401(client):
    """TC-DCON-045 | 未认证访问 pairs → 401

    输入: 无 Authorization 头
    预期输出: HTTP 401
    断言点: 状态码 401
    防回归: 若 get_current_user 依赖被删，匿名可读
    """
    assert client.get("/api/v1/console/datasets/seed/pairs").status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/console/datasets/{ds_id}/pairs/{pair_id}
# ---------------------------------------------------------------------------


def test_dataset_pair_detail_existing(client, admin_token):
    """TC-DCON-046 | 取已存在的单对详情

    输入: ds_id=seed, pair_id=demo-pair-1
    预期输出: 200，返回完整对（含 requestPrompt 全文）
    断言点: pairId + requestPrompt 非空
    防回归: 若详情遍历被改，会 404
    """
    resp = client.get("/api/v1/console/datasets/seed/pairs/demo-pair-1", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    pair = resp.json()
    assert pair["pairId"] == "demo-pair-1"
    assert pair["requestPrompt"]


def test_dataset_pair_detail_unknown_pair_404(client, admin_token):
    """TC-DCON-047 | 不存在的 pair_id → 404

    输入: pair_id=nope
    预期输出: HTTP 404，detail 含"不存在"
    断言点: 状态码 404 + detail 关键字
    防回归: 若未匹配 404 被删，会返回 null/200
    """
    resp = client.get("/api/v1/console/datasets/seed/pairs/nope", headers=auth_header(admin_token))
    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


def test_dataset_pair_detail_unknown_ds_404(client, admin_token):
    """TC-DCON-048 | 未知 ds_id 取详情 → 404

    输入: ds_id=bogus
    预期输出: HTTP 404，detail 含"未知数据集"
    断言点: 状态码 404 + detail 关键字
    防回归: 若 ds_id 校验被删，会尝试加载文件
    """
    resp = client.get("/api/v1/console/datasets/bogus/pairs/demo-pair-1", headers=auth_header(admin_token))
    assert resp.status_code == 404
    assert "未知数据集" in resp.json()["detail"]


def test_dataset_pair_detail_missing_file_404(client, admin_token, monkeypatch):
    """TC-DCON-049 | 详情数据集文件不可读 → 404

    输入: importlib_resources.files 被替换为抛 OSError 的桩
    预期输出: HTTP 404，detail 含"数据集不可用"
    断言点: 状态码 404 + detail 关键字
    防回归: 若 except 分支被删，OSError 会冒泡成 500
    """
    console_router._DATASET_CACHE.clear()
    _install_missing_resources(monkeypatch)
    resp = client.get("/api/v1/console/datasets/seed/pairs/demo-pair-1", headers=auth_header(admin_token))
    assert resp.status_code == 404
    assert "数据集不可用" in resp.json()["detail"]


def test_dataset_pair_detail_unauthorized_401(client):
    """TC-DCON-050 | 未认证访问单对详情 → 401

    输入: 无 Authorization 头
    预期输出: HTTP 401
    断言点: 状态码 401
    防回归: 若 get_current_user 依赖被删，匿名可读
    """
    assert client.get("/api/v1/console/datasets/seed/pairs/demo-pair-1").status_code == 401
