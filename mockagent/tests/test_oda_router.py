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

"""ODA Canvas 路由 / 场景路由 / 场景注册表覆盖补测（TestClient + MockTransport，不发真实 K8s 请求）。"""
import json

import httpx
import pytest
from fastapi import HTTPException

from mockagent_engine import scenario_registry, workflow_mode
from mockagent_engine.routers import oda_router, scenarios_router


# ---------- 共用 fixture ----------
@pytest.fixture()
def oda_config_path(tmp_path, monkeypatch):
    """把 ODA 配置落位指向临时文件（不写项目 data/）。"""
    p = tmp_path / "oda_canvas.json"
    monkeypatch.setattr(oda_router, "_config_path", lambda: p)
    return p


@pytest.fixture()
def oda_configured(oda_config_path):
    """预置一份可用的 K8s 配置（apiServer/image/jwtSecret 齐全）。"""
    cfg = oda_router.OdaConfig(
        apiServer="https://k8s.local",
        token="k8s-token",
        namespace="components",
        image="registry/mockagent:1.0",
        jwtSecret="x" * 40,
        adminPassword="admin-pass",
    )
    oda_router._save_config(cfg)
    return cfg


@pytest.fixture()
def patch_k8s(monkeypatch):
    """把 oda_router 的 httpx.Client 替换为走 MockTransport 的封装。"""

    def _apply(handler):
        real = oda_router.httpx.Client

        def fake(**kwargs):
            kwargs.pop("verify", None)
            return real(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(oda_router.httpx, "Client", fake)

    return _apply


@pytest.fixture()
def fake_workflow_dir(tmp_path, monkeypatch):
    """工作流注册表指向临时目录（不污染项目根）。"""
    wf_dir = tmp_path / "wf-registry"
    monkeypatch.setattr(workflow_mode, "workflows_dir", lambda: wf_dir)
    return wf_dir


def _fake_spawn(status="running"):
    def _ensure(instance, timeout=15.0):
        return {"id": instance["id"], "port": instance["port"], "status": status, "pid": 4321}

    return _ensure


# ==================== ODA 配置 ====================
def test_get_config_defaults_when_no_file(client, auth_headers, oda_config_path):
    """TC-ODA-001 | 无配置文件时 get_config 返回默认值且 hasToken=False

    输入: 空配置目录，GET /api/v1/console/oda/config
    预期输出: 200，config 为默认值，hasToken=False，jwtSecret/adminPassword 为空串
    断言点: 状态码 + hasToken + 敏感字段不回显
    防回归: 若 _load_config 默认分支被改，默认值会丢失
    """
    resp = client.get("/api/v1/console/oda/config", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hasToken"] is False
    assert body["config"]["apiServer"] == ""
    assert body["config"]["namespace"] == "components"
    assert body["config"]["jwtSecret"] == ""
    assert body["config"]["adminPassword"] == ""


def test_get_config_requires_auth(client):
    """TC-ODA-002 | 未认证访问 get_config 返回 401

    输入: 无 Authorization 头，GET /api/v1/console/oda/config
    预期输出: 401
    断言点: 状态码
    防回归: 若鉴权依赖被移除，未认证可读配置
    """
    assert client.get("/api/v1/console/oda/config").status_code in (401, 403)


def test_put_config_then_get_masks_secrets(client, auth_headers, oda_config_path):
    """TC-ODA-003 | 写入完整配置后回读，敏感字段回显掩码且 hasToken=True

    输入: PUT 含 token/jwtSecret/adminPassword 的配置；GET 回读
    预期输出: PUT 200；GET hasToken=True，jwtSecret="***"，adminPassword="***"
    断言点: 掩码值 + hasToken
    防回归: 若掩码逻辑被删，明文密钥会回显
    """
    full = {
        "apiServer": "https://k8s.local", "token": "real-token", "namespace": "components",
        "image": "img:1", "jwtSecret": "x" * 40, "adminPassword": "ap",
    }
    r = client.put("/api/v1/console/oda/config", json=full, headers=auth_headers)
    assert r.status_code == 200, r.text
    cfg = oda_router._load_config()
    assert cfg.token == "real-token"  # 未走掩码保留分支，直接写入

    body = client.get("/api/v1/console/oda/config", headers=auth_headers).json()
    assert body["hasToken"] is True
    assert body["config"]["jwtSecret"] == "***"
    assert body["config"]["adminPassword"] == "***"


def test_put_config_masked_token_preserves_old(client, auth_headers, oda_config_path):
    """TC-ODA-004 | PUT 传入掩码 token/**时保留旧值（幂等更新）

    输入: 先 PUT 真实 token；再 PUT token="***"/jwtSecret="***"/adminPassword="***"
    预期输出: 底层配置三项仍为旧真实值
    断言点: _load_config().token/jwtSecret/adminPassword 未被掩码覆盖
    防回归: 若保留分支删除，掩码会清空已存密钥
    """
    full = {"apiServer": "https://k8s.local", "token": "real-token", "namespace": "components",
            "image": "img:1", "jwtSecret": "x" * 40, "adminPassword": "ap"}
    client.put("/api/v1/console/oda/config", json=full, headers=auth_headers)
    masked = {**full, "token": "***", "jwtSecret": "***", "adminPassword": "***"}
    assert client.put("/api/v1/console/oda/config", json=masked, headers=auth_headers).status_code == 200
    cfg = oda_router._load_config()
    assert cfg.token == "real-token"
    assert cfg.jwtSecret == "x" * 40
    assert cfg.adminPassword == "ap"


def test_put_config_empty_token_preserves_old(client, auth_headers, oda_config_path):
    """TC-ODA-005 | PUT 传入空 token 时保留旧 token（幂等更新）

    输入: 先 PUT 真实 token；再 PUT token=""
    预期输出: 底层 token 仍为旧真实值
    断言点: _load_config().token == "real-token"
    防回归: 若空串保留分支删除，空 token 会清空已存密钥
    """
    full = {"apiServer": "https://k8s.local", "token": "real-token", "namespace": "components",
            "image": "img:1", "jwtSecret": "x" * 40, "adminPassword": "ap"}
    client.put("/api/v1/console/oda/config", json=full, headers=auth_headers)
    client.put("/api/v1/console/oda/config", json={**full, "token": ""}, headers=auth_headers)
    assert oda_router._load_config().token == "real-token"


def test_put_config_requires_auth(client):
    """TC-ODA-006 | 未认证访问 put_config 返回 401

    输入: 无 Authorization 头，PUT /api/v1/console/oda/config
    预期输出: 401
    断言点: 状态码
    防回归: 若鉴权依赖被移除，未认证可写配置
    """
    assert client.put("/api/v1/console/oda/config", json={}).status_code in (401, 403)


def test_load_config_corrupt_file_returns_defaults(oda_config_path):
    """TC-ODA-007 | 配置文件 JSON 损坏时 _load_config 回退默认值

    输入: 写入非法 JSON 到配置路径
    预期输出: _load_config() 返回默认 OdaConfig
    断言点: apiServer="" 且 namespace="components"（默认值）
    防回归: 若 except 分支删除，损坏 JSON 会以异常冒泡
    """
    oda_config_path.write_text("{not valid json", encoding="utf-8")
    cfg = oda_router._load_config()
    assert cfg.apiServer == ""
    assert cfg.namespace == "components"


def test_config_path_points_to_data_oda_canvas_json():
    """TC-ODA-056 | _config_path 返回 data/oda_canvas.json 相对路径

    输入: 直接调用未打补丁的 _config_path()
    预期输出: 路径名 oda_canvas.json，父目录 data
    断言点: 路径段精确值
    防回归: 若配置文件位置被改，落盘/读取路径会错
    """
    p = oda_router._config_path()
    assert p.name == "oda_canvas.json"
    assert p.parent.name == "data"


# ==================== 打桩实例清单 ====================
def test_list_agents_endpoint_returns_agents(client, auth_headers):
    """TC-ODA-008 | GET /oda/agents 返回打桩实例清单

    输入: 带管理员 token，GET /api/v1/console/oda/agents
    预期输出: 200，agents 含 26 项，每项有 id/port/running
    断言点: 数量 + running=False + 端口为整数
    防回归: 若清单生成被改，数量或字段会错
    """
    resp = client.get("/api/v1/console/oda/agents", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    agents = resp.json()["agents"]
    assert len(agents) == 26
    by_id = {a["id"]: a for a in agents}
    assert by_id["fault-diagnosis-stub"]["port"] == 9005
    assert all(a["running"] is False for a in agents)


def test_list_agents_requires_auth(client):
    """TC-ODA-009 | 未认证访问 /oda/agents 返回 401

    输入: 无 Authorization 头
    预期输出: 401
    断言点: 状态码
    防回归: 若鉴权依赖被移除，未认证可枚举实例
    """
    assert client.get("/api/v1/console/oda/agents").status_code in (401, 403)


def test_selected_agents_empty_returns_all_with_stripped_name():
    """TC-ODA-010 | selectedAgents 为空时返回全部实例，_agents 去除 -stub 后缀

    输入: OdaConfig(selectedAgents=[])
    预期输出: 26 个；fault-diagnosis-stub 的 name="fault-diagnosis"
    断言点: 数量 + name 字段精确值
    防回归: 若 replace 或空=全部逻辑被改，name/数量会错
    """
    cfg = oda_router.OdaConfig(selectedAgents=[])
    selected = oda_router._selected_agents(cfg)
    assert len(selected) == 26
    by_id = {a["id"]: a for a in selected}
    assert by_id["fault-diagnosis-stub"]["name"] == "fault-diagnosis"
    assert by_id["an-l4-assurance-agent"]["name"] == "an-l4-assurance-agent"


def test_selected_agents_filtered_returns_subset():
    """TC-ODA-011 | selectedAgents 非空时只返回匹配项

    输入: OdaConfig(selectedAgents=["fault-diagnosis-stub"])
    预期输出: 恰好 1 个，id 匹配
    断言点: 数量 + id 集合
    防回归: 若过滤逻辑被改，会返回全部或不匹配项
    """
    cfg = oda_router.OdaConfig(selectedAgents=["fault-diagnosis-stub"])
    selected = oda_router._selected_agents(cfg)
    assert {a["id"] for a in selected} == {"fault-diagnosis-stub"}


# ==================== _require / _client ====================
def test_require_missing_field_raises_400():
    """TC-ODA-012 | _require 对空字段抛 400 并指明字段名

    输入: OdaConfig(apiServer="")，_require("apiServer", cfg)
    预期输出: HTTPException 400，detail 含 "apiServer"
    断言点: 异常类型 + 状态码 + detail 关键字
    防回归: 若守卫删除，空 apiServer 会进入 HTTP 调用
    """
    cfg = oda_router.OdaConfig(apiServer="")
    with pytest.raises(HTTPException) as exc:
        oda_router._require("apiServer", cfg)
    assert exc.value.status_code == 400
    assert "apiServer" in exc.value.detail


def test_client_with_token_sets_authorization_and_insecure_verify(monkeypatch):
    """TC-ODA-013 | _client 带 token 时设置 Authorization 头，insecureTLS=True → verify=False

    输入: OdaConfig(apiServer, token, insecureTLS=True)
    预期输出: 传给 httpx.Client 的 headers 含 Authorization，verify=False
    断言点: 捕获 kwargs 的 headers/verify/base_url
    防回归: 若 token 注入或 TLS 开关被改，头/verify 会错
    """
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)

        class _C:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _C()

    monkeypatch.setattr(oda_router.httpx, "Client", fake)
    cfg = oda_router.OdaConfig(apiServer="https://k8s.local/", token="my-token", insecureTLS=True)
    oda_router._client(cfg)
    assert captured["headers"]["Authorization"] == "Bearer my-token"
    assert captured["headers"]["Accept"] == "application/json"
    assert captured["verify"] is False
    assert captured["base_url"] == "https://k8s.local"


def test_client_without_token_omits_authorization_and_enforces_tls(monkeypatch):
    """TC-ODA-014 | _client 无 token 时无 Authorization，insecureTLS=False → verify=True

    输入: OdaConfig(apiServer, token="", insecureTLS=False)
    预期输出: headers 无 Authorization，verify=True
    断言点: Authorization 缺失 + verify=True
    防回归: 若 TLS 开关反转，verify 会错
    """
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)

        class _C:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _C()

    monkeypatch.setattr(oda_router.httpx, "Client", fake)
    cfg = oda_router.OdaConfig(apiServer="https://k8s.local", token="", insecureTLS=False)
    oda_router._client(cfg)
    assert "Authorization" not in captured["headers"]
    assert captured["verify"] is True


def test_client_missing_apiserver_raises_400():
    """TC-ODA-015 | _client 在 apiServer 缺失时抛 400

    输入: OdaConfig(apiServer="")
    预期输出: HTTPException 400
    断言点: 异常类型 + 状态码
    防回归: 若 _require 未被 _client 调用，空 apiServer 会进入 httpx 构造
    """
    cfg = oda_router.OdaConfig(apiServer="")
    with pytest.raises(HTTPException) as exc:
        oda_router._client(cfg)
    assert exc.value.status_code == 400


# ==================== _apply ====================
def test_apply_grouped_resource_200_ok():
    """TC-ODA-016 | _apply 对带 group 的资源 PATCH 200 返回 ok=True

    输入: group="oda.tmforum.org" 的 Component 对象，MockTransport 返回 200
    预期输出: {"ok": True, "status": 200, "detail": None}
    断言点: ok/status/detail 字段
    防回归: 若 ok 判定被改，200 会判失败
    """
    cfg = oda_router.OdaConfig(namespace="components")

    def handler(request):
        return httpx.Response(200)

    client = httpx.Client(base_url="https://k8s.local", transport=httpx.MockTransport(handler))
    result = oda_router._apply(client, cfg, "oda.tmforum.org", "v1beta3", "components", "rel",
                               {"kind": "Component"})
    assert result == {"kind": "Component", "name": "rel", "ok": True, "status": 200, "detail": None}


def test_apply_core_resource_uses_api_v1_url_and_201_ok():
    """TC-ODA-017 | _apply 对 core 资源（group="")使用 /api/v1/ 路径，201 也算 ok

    输入: group="" 的 Secret 对象，MockTransport 返回 201
    预期输出: ok=True；请求路径含 /api/v1/namespaces/.../secrets/rel
    断言点: 捕获的请求路径 + ok=True
    防回归: 若 URL 构造分支反转，core 资源会走 /apis/
    """
    cfg = oda_router.OdaConfig(namespace="components")
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(201)

    client = httpx.Client(base_url="https://k8s.local", transport=httpx.MockTransport(handler))
    r_grouped = oda_router._apply(client, cfg, "oda.tmforum.org", "v1beta3", "components", "rel",
                                   {"kind": "Component"})
    r_core = oda_router._apply(client, cfg, "", "v1", "secrets", "rel", {"kind": "Secret"})
    assert r_grouped["ok"] is True and r_core["ok"] is True
    assert "/apis/oda.tmforum.org/" in seen[0]
    assert seen[0].endswith("/components/rel")
    assert seen[1].startswith("/api/v1/")
    assert seen[1].endswith("/secrets/rel")


def test_apply_500_returns_ok_false_with_detail():
    """TC-ODA-018 | _apply PATCH 500 返回 ok=False 且 detail 含响应文本

    输入: MockTransport 返回 500 + 文本
    预期输出: ok=False, status=500, detail 含错误文本
    断言点: ok/status/detail
    防回归: 若失败判定被改，500 会判成功
    """
    cfg = oda_router.OdaConfig(namespace="components")

    def handler(request):
        return httpx.Response(500, text="apply boom")

    client = httpx.Client(base_url="https://k8s.local", transport=httpx.MockTransport(handler))
    result = oda_router._apply(client, cfg, "", "v1", "secrets", "rel", {"kind": "Secret"})
    assert result["ok"] is False
    assert result["status"] == 500
    assert "apply boom" in result["detail"]


# ==================== _labels / _plural ====================
def test_labels_returns_standard_label_set():
    """TC-ODA-019 | _labels 返回含 release 的标准标签集

    输入: _labels("myrel")
    预期输出: instance/componentName == "myrel"，name == "openan-mockagent"
    断言点: 标签键值
    防回归: 若标签键被改，K8s 选择器会失配
    """
    labels = oda_router._labels("myrel")
    assert labels["app.kubernetes.io/instance"] == "myrel"
    assert labels["app.kubernetes.io/name"] == "openan-mockagent"
    assert labels["oda.tmforum.org/componentName"] == "myrel"
    assert labels["app.kubernetes.io/managed-by"] == "mockagent"


def test_plural_maps_kinds_and_raises_on_unknown():
    """TC-ODA-020 | _plural 映射已知 kind，未知 kind 抛 KeyError

    输入: 各已知 kind + "Unknown"
    预期输出: 正确复数；Unknown → KeyError
    断言点: 映射值 + 异常类型
    防回归: 若映射表被改，deploy 会用错 URL
    """
    assert oda_router._plural("Secret") == "secrets"
    assert oda_router._plural("PersistentVolumeClaim") == "persistentvolumeclaims"
    assert oda_router._plural("Deployment") == "deployments"
    assert oda_router._plural("Service") == "services"
    assert oda_router._plural("Component") == "components"
    with pytest.raises(KeyError):
        oda_router._plural("Unknown")


# ==================== _manifests ====================
def test_manifests_invalid_jwt_secret_raises_400():
    """TC-ODA-021 | _manifests 对过短 jwtSecret 抛 400

    输入: OdaConfig(jwtSecret="short")
    预期输出: HTTPException 400，detail 含 "32 bytes"
    断言点: 异常类型 + 状态码 + detail 关键字
    防回归: 若校验被删，过短密钥会进入清单
    """
    cfg = oda_router.OdaConfig(apiServer="https://k8s.local", image="img", jwtSecret="short")
    with pytest.raises(HTTPException) as exc:
        oda_router._manifests(cfg)
    assert exc.value.status_code == 400
    assert "32 bytes" in exc.value.detail


def test_manifests_full_config_generates_all_kinds_and_extras():
    """TC-ODA-022 | _manifests 完整配置生成 5 类对象并注入 adminPassword/autoStart/agent 端口

    输入: 含 adminPassword/autoStart/selectedAgents/publicUrl 的 OdaConfig
    预期输出: Secret/PVC/Deployment/Service/Component；Deployment env 含 ADMIN_PASSWORD/AUTOSTART；端口含所选 agent
    断言点: kind 顺序 + env + 端口 + 暴露 API 数
    防回归: 若任一清单段被改，对应字段会缺
    """
    cfg = oda_router.OdaConfig(
        apiServer="https://k8s.local", image="img:1", jwtSecret="x" * 40,
        adminPassword="admin-pass", autoStart=True,
        selectedAgents=["fault-diagnosis-stub", "livestream-stub"],
        publicUrl="http://example.com", release="myrel", componentId="TMFC900", storageSize="5Gi",
    )
    objs = oda_router._manifests(cfg)
    by_kind = {o["kind"]: o for o in objs}
    assert [o["kind"] for o in objs] == ["Secret", "PersistentVolumeClaim", "Deployment", "Service", "Component"]

    secret = by_kind["Secret"]
    assert secret["stringData"]["jwt-secret"] == "x" * 40
    assert secret["stringData"]["admin-password"] == "admin-pass"
    assert by_kind["PersistentVolumeClaim"]["spec"]["resources"]["requests"]["storage"] == "5Gi"

    container = by_kind["Deployment"]["spec"]["template"]["spec"]["containers"][0]
    env = {e["name"]: e for e in container["env"]}
    assert env["MOCK_AGENT_ADMIN_PASSWORD"]["valueFrom"]["secretKeyRef"]["key"] == "admin-password"
    assert env["MOCK_AGENT_AUTOSTART"]["value"] == "fault-diagnosis-stub,livestream-stub"
    port_names = {p["name"] for p in container["ports"]}
    assert {"agent-fault-diagnosis", "agent-livestream"} <= port_names

    svc_ports = {p["name"] for p in by_kind["Service"]["spec"]["ports"]}
    assert {"agent-fault-diagnosis", "agent-livestream"} <= svc_ports

    comp = by_kind["Component"]
    assert comp["apiVersion"] == "oda.tmforum.org/v1beta3"
    assert comp["spec"]["id"] == "TMFC900"
    assert len(comp["spec"]["coreFunction"]["exposedAPIs"]) == 3  # a2a + 2 agents
    assert "2 个打桩实例" in comp["spec"]["description"]
    assert comp["spec"]["coreFunction"]["exposedAPIs"][0]["specification"] == ["http://example.com/openapi.json"]


def test_manifests_without_admin_password_and_autostart_omits_env():
    """TC-ODA-023 | _manifests 无 adminPassword/autoStart 时不注入对应 env/secret

    输入: OdaConfig(adminPassword="", autoStart=False)
    预期输出: Secret 无 admin-password；Deployment env 无 ADMIN_PASSWORD/AUTOSTART
    断言点: 字段缺失
    防回归: 若条件分支反转，会注入空值 env
    """
    cfg = oda_router.OdaConfig(apiServer="https://k8s.local", image="img", jwtSecret="x" * 40,
                               adminPassword="", autoStart=False)
    objs = oda_router._manifests(cfg)
    by_kind = {o["kind"]: o for o in objs}
    assert "admin-password" not in by_kind["Secret"]["stringData"]
    env_names = {e["name"] for e in by_kind["Deployment"]["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert "MOCK_AGENT_ADMIN_PASSWORD" not in env_names
    assert "MOCK_AGENT_AUTOSTART" not in env_names


def test_manifests_empty_selected_agents_includes_all_ports():
    """TC-ODA-024 | _manifests selectedAgents 为空时 Deployment 含全部 26 个 agent 端口

    输入: OdaConfig(selectedAgents=[])
    预期输出: Deployment 端口数 == 27（http + 26）
    断言点: 端口数
    防回归: 若空=全部逻辑被改，端口数会错
    """
    cfg = oda_router.OdaConfig(apiServer="https://k8s.local", image="img", jwtSecret="x" * 40)
    objs = oda_router._manifests(cfg)
    dep = next(o for o in objs if o["kind"] == "Deployment")
    ports = dep["spec"]["template"]["spec"]["containers"][0]["ports"]
    assert len(ports) == 27


def test_manifests_no_matching_agents_description_shows_none():
    """TC-ODA-025 | _manifests selectedAgents 无匹配时描述显示 "无" 且无 agent 端口

    输入: OdaConfig(selectedAgents=["nonexistent-agent"])
    预期输出: Component 描述含 "0 个打桩实例"/"无"；Deployment 仅 http 端口
    断言点: 描述关键字 + 端口数
    防回归: 若 join ... or '无' 被改，空 join 会留空串
    """
    cfg = oda_router.OdaConfig(apiServer="https://k8s.local", image="img", jwtSecret="x" * 40,
                               selectedAgents=["nonexistent-agent"])
    objs = oda_router._manifests(cfg)
    comp = next(o for o in objs if o["kind"] == "Component")
    assert "0 个打桩实例" in comp["spec"]["description"]
    assert "无" in comp["spec"]["description"]
    dep = next(o for o in objs if o["kind"] == "Deployment")
    assert len(dep["spec"]["template"]["spec"]["containers"][0]["ports"]) == 1


def test_manifests_release_and_publicurl_fallbacks():
    """TC-ODA-026 | _manifests release/publicUrl 为空时回退默认值

    输入: OdaConfig(release="", publicUrl="")
    预期输出: Service 名 "openan-mockagent-core"；暴露 API 用 http://openan-mockagent-core:9000
    断言点: 回退后的 name/specification
    防回归: 若 or 回退被改，空值会产生空名
    """
    cfg = oda_router.OdaConfig(apiServer="https://k8s.local", image="img", jwtSecret="x" * 40,
                               release="", publicUrl="")
    objs = oda_router._manifests(cfg)
    svc = next(o for o in objs if o["kind"] == "Service")
    assert svc["metadata"]["name"] == "openan-mockagent-core"
    comp = next(o for o in objs if o["kind"] == "Component")
    assert comp["spec"]["coreFunction"]["exposedAPIs"][0]["specification"] == [
        "http://openan-mockagent-core:9000/openapi.json"]


# ==================== test-connection ====================
def test_connection_all_ok(client, auth_headers, oda_configured, patch_k8s):
    """TC-ODA-027 | test-connection 全部 200 时返回版本/CRD/命名空间可达

    输入: 配置含 apiServer；MockTransport 对 /version、/apis/oda.tmforum.org、namespace 均 200
    预期输出: k8sVersion="v1.30.0"，componentCrd=True，versions=["v1beta3"]，namespaceReachable=True
    断言点: 各字段值
    防回归: 若字段映射被改，可达性会误报
    """
    def handler(request):
        p = request.url.path
        if p == "/version":
            return httpx.Response(200, json={"gitVersion": "v1.30.0"})
        if p == "/apis/oda.tmforum.org":
            return httpx.Response(200, json={"versions": [{"version": "v1beta3"}]})
        if p == "/api/v1/namespaces/components":
            return httpx.Response(200, json={})
        return httpx.Response(404)

    patch_k8s(handler)
    resp = client.post("/api/v1/console/oda/test-connection", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["k8sVersion"] == "v1.30.0"
    assert body["componentCrd"] is True
    assert body["versions"] == ["v1beta3"]
    assert body["namespaceReachable"] is True


def test_connection_version_unreachable_returns_502(client, auth_headers, oda_configured, patch_k8s):
    """TC-ODA-028 | test-connection /version 非 200 时返回 502

    输入: MockTransport 对 /version 返回 500
    预期输出: 502，detail 含 "API Server 不可达" 和 "500"
    断言点: 状态码 + detail 关键字
    防回归: 若 502 分支被改，不可达会静默成功
    """
    patch_k8s(lambda request: httpx.Response(500, text="internal error"))
    resp = client.post("/api/v1/console/oda/test-connection", headers=auth_headers)
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "API Server 不可达" in detail
    assert "500" in detail


def test_connection_crd_missing_returns_false_and_empty_versions(client, auth_headers, oda_configured, patch_k8s):
    """TC-ODA-029 | test-connection CRD 404 时 componentCrd=False 且 versions=[]

    输入: /version 200；/apis/oda.tmforum.org 404；namespace 200
    预期输出: componentCrd=False，versions=[]
    断言点: 字段值
    防回归: 若 versions 三元分支被改，404 会取 .json() 崩溃
    """
    def handler(request):
        p = request.url.path
        if p == "/version":
            return httpx.Response(200, json={"gitVersion": "v1.30.0"})
        if p == "/apis/oda.tmforum.org":
            return httpx.Response(404)
        return httpx.Response(200, json={})

    patch_k8s(handler)
    body = client.post("/api/v1/console/oda/test-connection", headers=auth_headers).json()
    assert body["componentCrd"] is False
    assert body["versions"] == []
    assert body["namespaceReachable"] is True


def test_connection_namespace_404_sets_error(client, auth_headers, oda_configured, patch_k8s):
    """TC-ODA-030 | test-connection 命名空间 404 时 namespaceReachable=False 且带 error

    输入: /version 200；/apis/oda.tmforum.org 200；namespace 404
    预期输出: namespaceReachable=False，namespaceError 含 "不存在"
    断言点: 字段值 + 关键字
    防回归: 若 404 分支被改，命名空间缺失会误报可达
    """
    def handler(request):
        p = request.url.path
        if p == "/version":
            return httpx.Response(200, json={"gitVersion": "v1.30.0"})
        if p == "/apis/oda.tmforum.org":
            return httpx.Response(200, json={"versions": [{"version": "v1beta3"}]})
        if p == "/api/v1/namespaces/components":
            return httpx.Response(404)
        return httpx.Response(404)

    patch_k8s(handler)
    body = client.post("/api/v1/console/oda/test-connection", headers=auth_headers).json()
    assert body["namespaceReachable"] is False
    assert "不存在" in body["namespaceError"]


def test_connection_requires_auth(client):
    """TC-ODA-031 | 未认证访问 test-connection 返回 401

    输入: 无 Authorization 头
    预期输出: 401
    断言点: 状态码
    防回归: 若鉴权依赖被移除，未认证可探测集群
    """
    assert client.post("/api/v1/console/oda/test-connection").status_code in (401, 403)


def test_connection_missing_apiserver_returns_400(client, auth_headers, oda_config_path):
    """TC-ODA-032 | test-connection 在 apiServer 缺失时返回 400

    输入: 默认配置（apiServer=""）
    预期输出: 400，detail 含 "apiServer"
    断言点: 状态码 + detail 关键字
    防回归: 若 _client 未守卫 apiServer，会进入 httpx 构造崩
    """
    resp = client.post("/api/v1/console/oda/test-connection", headers=auth_headers)
    assert resp.status_code == 400
    assert "apiServer" in resp.json()["detail"]


# ==================== deploy ====================
def test_deploy_missing_image_returns_400(client, auth_headers, oda_config_path):
    """TC-ODA-033 | deploy 在 image 缺失时返回 400

    输入: 配置含 apiServer 但 image=""
    预期输出: 400，detail 含 "image"
    断言点: 状态码 + detail 关键字
    防回归: 若 _require("image") 被删，空镜像会进入部署
    """
    oda_router._save_config(oda_router.OdaConfig(apiServer="https://k8s.local", image=""))
    resp = client.post("/api/v1/console/oda/deploy", headers=auth_headers)
    assert resp.status_code == 400
    assert "image" in resp.json()["detail"]


def test_deploy_creates_namespace_when_404(client, auth_headers, oda_configured, patch_k8s):
    """TC-ODA-034 | deploy 命名空间 404 时创建命名空间并应用全部清单

    输入: GET namespace 404；POST namespace 201；PATCH 200
    预期输出: ok=True，results 含 Namespace + 5 清单 = 6 项
    断言点: ok + results 长度 + Namespace ok
    防回归: 若 404 创建分支被改，缺失命名空间会部署失败
    """
    def handler(request):
        p, m = request.url.path, request.method
        if m == "GET" and p == "/api/v1/namespaces/components":
            return httpx.Response(404)
        if m == "POST" and p == "/api/v1/namespaces":
            return httpx.Response(201, json={})
        if m == "PATCH":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={})

    patch_k8s(handler)
    resp = client.post("/api/v1/console/oda/deploy", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert len(body["results"]) == 6
    assert body["results"][0]["kind"] == "Namespace"
    assert body["results"][0]["ok"] is True


def test_deploy_skips_namespace_creation_when_exists(client, auth_headers, oda_configured, patch_k8s):
    """TC-ODA-035 | deploy 命名空间已存在时跳过创建仅应用清单

    输入: GET namespace 200；PATCH 200
    预期输出: ok=True，results 仅 5 项（无 Namespace）
    断言点: results 长度 + 无 Namespace kind
    防回归: 若 404 分支判定反转，已存在命名空间会被重复创建
    """
    def handler(request):
        if request.method == "PATCH":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={})

    patch_k8s(handler)
    body = client.post("/api/v1/console/oda/deploy", headers=auth_headers).json()
    assert body["ok"] is True
    assert len(body["results"]) == 5
    assert all(r["kind"] != "Namespace" for r in body["results"])


def test_deploy_apply_failure_returns_ok_false(client, auth_headers, oda_configured, patch_k8s):
    """TC-ODA-036 | deploy 清单 apply 失败时 ok=False 且 detail 含错误

    输入: GET namespace 200；PATCH 500
    预期输出: ok=False，所有清单 result ok=False 且 detail 非空
    断言点: ok + 各 result ok/detail
    防回归: 若失败聚合被改，apply 失败会误报成功
    """
    def handler(request):
        if request.method == "PATCH":
            return httpx.Response(500, text="apply failed boom")
        return httpx.Response(200, json={})

    patch_k8s(handler)
    body = client.post("/api/v1/console/oda/deploy", headers=auth_headers).json()
    assert body["ok"] is False
    assert len(body["results"]) == 5
    assert all(r["ok"] is False for r in body["results"])
    assert all(r["detail"] for r in body["results"])


def test_deploy_requires_auth(client):
    """TC-ODA-037 | 未认证访问 deploy 返回 401

    输入: 无 Authorization 头
    预期输出: 401
    断言点: 状态码
    防回归: 若鉴权依赖被移除，未认证可部署
    """
    assert client.post("/api/v1/console/oda/deploy").status_code in (401, 403)


# ==================== status ====================
def test_status_component_deployed(client, auth_headers, oda_configured, patch_k8s):
    """TC-ODA-038 | status 组件已部署时返回 deploymentStatus/exposedAPIs

    输入: GET component 200（含 summary/spec）；pods 200 空；service 200
    预期输出: deploymentStatus="Ready"，exposedAPIs=2，service.exists=True
    断言点: 字段值
    防回归: 若 summary 解析被改，状态会 unknown
    """
    def handler(request):
        p = request.url.path
        if p.endswith("/components/openan-mockagent"):
            return httpx.Response(200, json={
                "status": {"summary": {"status": {"deployment_status": "Ready"}}},
                "spec": {"coreFunction": {"exposedAPIs": [{"name": "a"}, {"name": "b"}]}},
            })
        if p.endswith("/pods"):
            return httpx.Response(200, json={"items": []})
        if p.endswith("/services/openan-mockagent-core"):
            return httpx.Response(200, json={"spec": {"clusterIP": "10.0.0.1"}})
        return httpx.Response(404)

    patch_k8s(handler)
    body = client.get("/api/v1/console/oda/status", headers=auth_headers).json()
    assert body["component"]["deploymentStatus"] == "Ready"
    assert body["component"]["exposedAPIs"] == 2
    assert body["service"]["exists"] is True
    assert body["service"]["clusterIP"] == "10.0.0.1"
    assert body["pods"] == []
    assert len(body["selectedAgents"]) == 26


def test_status_component_not_deployed_with_pods(client, auth_headers, oda_configured, patch_k8s):
    """TC-ODA-039 | status 组件未部署(404) 但有 Pod 时返回 "未部署" 且列出 Pod 字段

    输入: GET component 404；pods 200 含 2 Pod（其一无 containerStatuses）；service 200
    预期输出: deploymentStatus 含 "未部署"；pod 含 name/phase/ready/restarts/image；无 CS 的 pod ready=None
    断言点: 状态关键字 + Pod 字段 + 缺 containerStatuses 兜底
    防回归: 若 404 分支被改，未部署会崩；若 Pod 字段映射被改，字段会缺
    """
    def handler(request):
        p = request.url.path
        if p.endswith("/components/openan-mockagent"):
            return httpx.Response(404)
        if p.endswith("/pods"):
            return httpx.Response(200, json={"items": [
                {"metadata": {"name": "pod-1"}, "status": {"phase": "Running",
                 "containerStatuses": [{"ready": True, "restartCount": 2, "image": "img:1"}]}},
                {"metadata": {"name": "pod-2"}, "status": {"phase": "Pending"}},
            ]})
        if p.endswith("/services/openan-mockagent-core"):
            return httpx.Response(200, json={"spec": {"clusterIP": "10.0.0.2"}})
        return httpx.Response(404)

    patch_k8s(handler)
    body = client.get("/api/v1/console/oda/status", headers=auth_headers).json()
    assert "未部署" in body["component"]["deploymentStatus"]
    pods = {p["name"]: p for p in body["pods"]}
    assert pods["pod-1"]["phase"] == "Running"
    assert pods["pod-1"]["ready"] is True
    assert pods["pod-1"]["restarts"] == 2
    assert pods["pod-1"]["image"] == "img:1"
    # 无 containerStatuses → 兜底 [{}][0]，ready=None image=""
    assert pods["pod-2"]["phase"] == "Pending"
    assert pods["pod-2"]["ready"] is None
    assert pods["pod-2"]["image"] == ""


def test_status_pods_and_service_missing(client, auth_headers, oda_configured, patch_k8s):
    """TC-ODA-040 | status pods/service 404 时 pods 空、service.exists=False

    输入: component 404；pods 404；service 404
    预期输出: pods=[]，service.exists=False，clusterIP=None
    断言点: 字段值
    防回归: 若 200 守卫被改，404 会取 .json() 崩
    """
    patch_k8s(lambda request: httpx.Response(404))
    body = client.get("/api/v1/console/oda/status", headers=auth_headers).json()
    assert body["pods"] == []
    assert body["service"]["exists"] is False
    assert body["service"]["clusterIP"] is None


def test_status_missing_apiserver_returns_400(client, auth_headers, oda_config_path):
    """TC-ODA-041 | status 在 apiServer 缺失时返回 400

    输入: 默认配置（apiServer=""）
    预期输出: 400，detail 含 "apiServer"
    断言点: 状态码 + detail 关键字
    防回归: 若 _require 未守卫，空 apiServer 会进入 HTTP 调用
    """
    resp = client.get("/api/v1/console/oda/status", headers=auth_headers)
    assert resp.status_code == 400
    assert "apiServer" in resp.json()["detail"]


def test_status_requires_auth(client):
    """TC-ODA-042 | 未认证访问 status 返回 401

    输入: 无 Authorization 头
    预期输出: 401
    断言点: 状态码
    防回归: 若鉴权依赖被移除，未认证可查状态
    """
    assert client.get("/api/v1/console/oda/status").status_code in (401, 403)


# ==================== undeploy ====================
def test_undeploy_all_ok(client, auth_headers, oda_configured, patch_k8s):
    """TC-ODA-043 | undeploy 全部 200 时 ok=True 且 4 个目标

    输入: DELETE 全部 200
    预期输出: ok=True，results 4 项全 ok
    断言点: ok + results 长度 + 各 ok
    防回归: 若目标列表被改，数量会错
    """
    patch_k8s(lambda request: httpx.Response(200))
    body = client.post("/api/v1/console/oda/undeploy", headers=auth_headers).json()
    assert body["ok"] is True
    assert len(body["results"]) == 4
    assert all(r["ok"] for r in body["results"])


def test_undeploy_one_500_returns_ok_false(client, auth_headers, oda_configured, patch_k8s):
    """TC-ODA-044 | undeploy 某 500 时 ok=False（404 视为 ok）

    输入: DELETE secrets 返回 500，其余 200
    预期输出: ok=False，secrets result ok=False，components ok=True
    断言点: ok + 各 result ok
    防回归: 若 200/404 判定被改，500 会误判成功
    """
    def handler(request):
        if request.url.path.endswith("/secrets/openan-mockagent"):
            return httpx.Response(500)
        return httpx.Response(200)

    patch_k8s(handler)
    body = client.post("/api/v1/console/oda/undeploy", headers=auth_headers).json()
    assert body["ok"] is False
    by_kind = {r["kind"]: r for r in body["results"]}
    assert by_kind["secrets"]["ok"] is False
    assert by_kind["components"]["ok"] is True


def test_undeploy_missing_apiserver_returns_400(client, auth_headers, oda_config_path):
    """TC-ODA-045 | undeploy 在 apiServer 缺失时返回 400

    输入: 默认配置（apiServer=""）
    预期输出: 400，detail 含 "apiServer"
    断言点: 状态码 + detail 关键字
    防回归: 若 _require 未守卫，空 apiServer 会进入 HTTP 调用
    """
    resp = client.post("/api/v1/console/oda/undeploy", headers=auth_headers)
    assert resp.status_code == 400
    assert "apiServer" in resp.json()["detail"]


def test_undeploy_requires_auth(client):
    """TC-ODA-046 | 未认证访问 undeploy 返回 401

    输入: 无 Authorization 头
    预期输出: 401
    断言点: 状态码
    防回归: 若鉴权依赖被移除，未认证可卸载
    """
    assert client.post("/api/v1/console/oda/undeploy").status_code in (401, 403)


# ==================== scenarios_router 补测 ====================
def test_scenario_detail_agent_brief_fallback_on_typeerror(client, auth_headers, monkeypatch):
    """TC-ODA-047 | _agent_brief 在 load_agent_class 抛 TypeError 时回退 generic

    输入: monkeypatch load_agent_class 抛 TypeError；GET /scenarios/live-assurance-demo
    预期输出: 200，agents 中每个 agent agentType="generic" 且 name/port/endpoint=None
    断言点: 回退字段精确值
    防回归: 若 except 分支删除，TypeError 会冒泡为 500
    """
    def boom(_d):
        raise TypeError("no class")

    monkeypatch.setattr(scenarios_router.agent_registry, "load_agent_class", boom)
    resp = client.get("/api/v1/scenarios/live-assurance-demo", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    for a in resp.json()["agents"]:
        assert a["agent"]["agentType"] == "generic"
        assert a["agent"]["name"] is None
        assert a["agent"]["port"] is None
        assert a["agent"]["endpoint"] is None


def test_load_scenario_or_raise_value_error_returns_400(client, auth_headers, tmp_path, monkeypatch):
    """TC-ODA-048 | 场景 agents 为空时 _load_scenario_or_raise 返回 400

    输入: 临时场景目录，agents.json 的 agents 为空；GET /scenarios/bad/status
    预期输出: 400，detail 含 "不能为空"
    断言点: 状态码 + detail 关键字
    防回归: 若 ValueError 分支删除，空 agents 会以 500 冒泡
    """
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / scenario_registry.SCENARIO_FILENAME).write_text(
        json.dumps({"id": "bad"}, ensure_ascii=False), encoding="utf-8")
    (bad / scenario_registry.SCENARIO_WORKFLOW_FILENAME).write_text("{}", encoding="utf-8")
    (bad / scenario_registry.SCENARIO_AGENTS_FILENAME).write_text(
        json.dumps({"agents": []}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("MOCK_AGENT_SCENARIOS_DIR", str(tmp_path))
    resp = client.get("/api/v1/scenarios/bad/status", headers=auth_headers)
    assert resp.status_code == 400
    assert "不能为空" in resp.json()["detail"]


def test_workflow_target_paths_swallows_load_agent_error(monkeypatch):
    """TC-ODA-049 | 宿主 workDir 计算时 load_agent 失败被吞掉，仅保留全局注册表目标

    输入: 真实场景数据；monkeypatch load_agent 抛 KeyError；直接调用 _workflow_target_paths
    预期输出: targets 仅 1 项（全局注册表），host workDir 目标被 except 跳过
    断言点: targets 长度=1 + 目标文件名 + wf_id
    防回归: 若 except 分支删除，KeyError 会冒泡（load_define 不受影响因不经过此路径）
    """
    d = scenario_registry.resolve_scenario_dir("live-assurance-demo")
    data = scenario_registry.load_scenario(d)

    def boom(_d):
        raise KeyError("no workDir")

    monkeypatch.setattr(scenarios_router.agent_registry, "load_agent", boom)
    wf_id, targets = scenarios_router._workflow_target_paths(data, d)
    assert len(targets) == 1
    assert targets[0].name == "psop_live_event_assurance_en.json"
    assert wf_id == "psop_live_event_assurance_en"


def test_init_scenario_marks_undefined_instance_failed(client, auth_headers, monkeypatch):
    """TC-ODA-050 | 场景 agent 不在 define 实例中时 init 标记 failed

    输入: monkeypatch _load_define 返回空 instances + _write_workflow_files 空操作；POST init
    预期输出: 200，status="partial"，每个 agent status="failed" error 含 "未定义"
    断言点: 状态 + 错误消息关键字
    防回归: 若 instance is None 分支删除，会 KeyError 500
    """
    monkeypatch.setattr(scenarios_router, "_load_define", lambda: {"instances": []})
    monkeypatch.setattr(scenarios_router, "_write_workflow_files", lambda data, targets: None)
    resp = client.post("/api/v1/scenarios/live-assurance-demo/init", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "partial"
    assert all(a["status"] == "failed" for a in body["agents"])
    assert all("未定义" in a["error"] for a in body["agents"])


def test_scenario_status_marks_undefined_instance(client, auth_headers, monkeypatch):
    """TC-ODA-051 | 场景 agent 不在 define 实例中时 status 标记 undefined

    输入: monkeypatch _load_define 返回空 instances；GET status
    预期输出: 200，每个 agent status="undefined"，overall="stopped"
    断言点: 状态值 + 总体状态
    防回归: 若 instance is None 分支删除，会 KeyError 500
    """
    monkeypatch.setattr(scenarios_router, "_load_define", lambda: {"instances": []})
    resp = client.get("/api/v1/scenarios/live-assurance-demo/status", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert all(a["status"] == "undefined" for a in body["agents"])
    assert body["status"] == "stopped"


# ==================== scenario_registry 补测 ====================
def test_scenarios_dir_override_env(monkeypatch, tmp_path):
    """TC-ODA-052 | MOCK_AGENT_SCENARIOS_DIR 覆盖场景根目录

    输入: 设置 MOCK_AGENT_SCENARIOS_DIR=tmp_path
    预期输出: scenarios_dir() == tmp_path
    断言点: 返回值精确等于覆盖路径
    防回归: 若 override 分支删除，返回项目默认路径
    """
    monkeypatch.setenv("MOCK_AGENT_SCENARIOS_DIR", str(tmp_path))
    assert scenario_registry.scenarios_dir() == tmp_path


def test_list_scenario_dirs_empty_when_root_missing(monkeypatch, tmp_path):
    """TC-ODA-053 | 场景根不存在时 list_scenario_dirs 返回空列表

    输入: MOCK_AGENT_SCENARIOS_DIR 指向不存在的目录
    预期输出: list_scenario_dirs() == []
    断言点: 返回空列表（非异常）
    防回归: 若 root.is_dir() 守卫删除，iterdir 会抛异常
    """
    monkeypatch.setenv("MOCK_AGENT_SCENARIOS_DIR", str(tmp_path / "nope"))
    assert scenario_registry.list_scenario_dirs() == []


def test_list_scenarios_skips_dir_with_corrupt_storyline(monkeypatch, tmp_path):
    """TC-ODA-054 | 故事线 JSON 损坏的场景被 list_scenarios 跳过

    输入: 临时场景根，含一个 scenario.json 损坏的场景（3 文件齐备）
    预期输出: list_scenarios() == []（坏场景被 except 跳过）
    断言点: 返回空列表
    防回归: 若 except 分支删除，损坏 JSON 会以异常冒泡
    """
    bad = tmp_path / "broken"
    bad.mkdir()
    (bad / scenario_registry.SCENARIO_FILENAME).write_text("not-json{", encoding="utf-8")
    (bad / scenario_registry.SCENARIO_WORKFLOW_FILENAME).write_text("{}", encoding="utf-8")
    (bad / scenario_registry.SCENARIO_AGENTS_FILENAME).write_text(
        json.dumps({"agents": [{"id": "an-l4-ran-agent"}]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("MOCK_AGENT_SCENARIOS_DIR", str(tmp_path))
    assert scenario_registry.list_scenarios() == []


def test_scenarios_dir_returns_deployed_root_when_scenarios_dir_exists(monkeypatch):
    """TC-ODA-055 | mockagent/scenarios 存在时 scenarios_dir 返回 deployed_root

    输入: 临时创建 mockagent/scenarios 空目录
    预期输出: scenarios_dir() == mockagent/scenarios（deployed_root 分支）
    断言点: 返回 deployed_root（line 38 分支）
    防回归: 若 deployed_root.is_dir() 分支删除，部署态布局会错误回退到 project.parent
    """
    monkeypatch.delenv("MOCK_AGENT_SCENARIOS_DIR", raising=False)
    deployed = scenario_registry.Path(scenario_registry.__file__).resolve().parents[1] / "scenarios"
    created = False
    try:
        if not deployed.is_dir():
            deployed.mkdir()
            created = True
        result = scenario_registry.scenarios_dir()
        assert result == deployed
    finally:
        if created:
            try:
                deployed.rmdir()
            except OSError:
                pass
