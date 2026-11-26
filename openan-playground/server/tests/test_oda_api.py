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
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from openan_debug.routers import oda_router
from tests.conftest import auth_header

_REAL_CLIENT = httpx.Client


@pytest.fixture()
def oda_config_path(tmp_path, monkeypatch):
    p = tmp_path / "oda_canvas.json"
    monkeypatch.setattr(oda_router, "_config_path", lambda: p)
    return p


def _write_config(path, **overrides):
    defaults = {"apiServer": "http://k8s.test", "token": "tok", "image": "img:1"}
    defaults.update(overrides)
    cfg = oda_router.OdaConfig(**defaults)
    path.write_text(json.dumps(cfg.model_dump(), ensure_ascii=False), encoding="utf-8")
    return cfg


def _install_mock_k8s(monkeypatch, handler):
    def fake_client_factory(**kwargs):
        kwargs.pop("verify", None)
        return _REAL_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(oda_router.httpx, "Client", fake_client_factory)


def _env_map(deployment):
    env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    return {e["name"]: e for e in env}


# ---------- /config endpoints ----------
def test_get_config_returns_defaults_when_unconfigured(client, admin_token, oda_config_path):
    """TC-DODA-001 | 未配置时 GET /config 返回默认值且不回显 token

    输入: 配置文件不存在，带 admin token GET /config
    预期输出: 200，config 为默认值，hasToken=False，jwtSecret/adminPassword 为空串，不含 token 字段
    断言点: 状态码 + hasToken=False + jwtSecret=="" + "token" 不在 config 中
    防回归: 若 get_config 未弹出 token 或未对空 secret 做空串处理，本用例失败
    """
    resp = client.get("/api/v1/console/oda/config", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hasToken"] is False
    cfg = body["config"]
    assert cfg["jwtSecret"] == ""
    assert cfg["adminPassword"] == ""
    assert cfg["namespace"] == "components"
    assert "token" not in cfg


def test_put_then_get_config_roundtrip_redacts_secrets(client, admin_token, oda_config_path):
    """TC-DODA-002 | PUT /config 持久化后 GET 回读，token 只写不回显，secret 字段脱敏

    输入: PUT 完整配置(token/jwtSecret/adminPassword 均非空) → GET /config
    预期输出: PUT 200 {ok:True}；GET 200 hasToken=True，jwtSecret/adminPassword 显示 "***"，无 token 字段
    断言点: PUT ok + hasToken=True + 脱敏值 "***" + config 无 token
    防回归: 若 token 回显或 secret 未脱敏，本用例失败
    """
    put = client.put(
        "/api/v1/console/oda/config",
        json={"apiServer": "http://k8s.test", "token": "tok", "image": "img:1",
              "jwtSecret": "js", "adminPassword": "ap"},
        headers=auth_header(admin_token),
    )
    assert put.status_code == 200, put.text
    assert put.json() == {"ok": True}
    resp = client.get("/api/v1/console/oda/config", headers=auth_header(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["hasToken"] is True
    cfg = body["config"]
    assert cfg["jwtSecret"] == "***"
    assert cfg["adminPassword"] == "***"
    assert "token" not in cfg


def test_put_config_preserves_secrets_on_placeholder(client, admin_token, oda_config_path):
    """TC-DODA-003 | PUT 配置时 token/jwtSecret/adminPassword 为占位 "***" 则保留旧值

    输入: 先 PUT(token=tok1,jwtSecret=js1,adminPassword=ap1,apiServer=http://a)；再 PUT(token=***,jwtSecret=***,adminPassword=***,apiServer=http://b)
    预期输出: 落盘文件 token=tok1、jwtSecret=js1、adminPassword=ap1、apiServer=http://b；GET hasToken=True 且 secret 脱敏
    断言点: 落盘旧密钥保留 + apiServer 更新 + GET 脱敏
    防回归: 若占位保留分支被删除，旧 token/secret 会被覆盖为 "***"
    """
    h = auth_header(admin_token)
    client.put("/api/v1/console/oda/config",
               json={"apiServer": "http://a", "token": "tok1", "jwtSecret": "js1", "adminPassword": "ap1"}, headers=h)
    client.put("/api/v1/console/oda/config",
               json={"apiServer": "http://b", "token": "***", "jwtSecret": "***", "adminPassword": "***"}, headers=h)
    saved = json.loads(oda_config_path.read_text(encoding="utf-8"))
    assert saved["token"] == "tok1"
    assert saved["jwtSecret"] == "js1"
    assert saved["adminPassword"] == "ap1"
    assert saved["apiServer"] == "http://b"
    resp = client.get("/api/v1/console/oda/config", headers=h)
    assert resp.json()["hasToken"] is True
    assert resp.json()["config"]["jwtSecret"] == "***"


def test_get_config_requires_auth(client):
    """TC-DODA-004 | 无 token 访问 GET /config 返回 401

    输入: 不带 Authorization 头 GET /config
    预期输出: 401
    断言点: 状态码 401
    防回归: 若鉴权依赖被移除，本用例失败
    """
    assert client.get("/api/v1/console/oda/config").status_code == 401


# ---------- private helpers: config ----------
def test_load_config_returns_default_on_corrupt_file(tmp_path, monkeypatch):
    """TC-DODA-005 | _load_config 读取损坏 JSON 时静默回退默认配置

    输入: 配置文件内容为非法 JSON
    预期输出: 返回默认 OdaConfig（apiServer="", namespace="components", token=""）
    断言点: apiServer=="" + namespace=="components" + token==""
    防回归: 若异常处理被改为抛出，本用例失败
    """
    p = tmp_path / "oda_canvas.json"
    p.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(oda_router, "_config_path", lambda: p)
    cfg = oda_router._load_config()
    assert cfg.apiServer == ""
    assert cfg.namespace == "components"
    assert cfg.token == ""


def test_config_path_returns_data_canvas_file():
    """TC-DODA-036 | _config_path 返回固定的 data/oda_canvas.json 路径

    输入: 直接调用未被替换的 _config_path()
    预期输出: 返回 Path("data/oda_canvas.json")
    断言点: 返回值等于 Path("data/oda_canvas.json")
    防回归: 若配置文件路径常量被改坏，依赖该路径的持久化逻辑会错位
    """
    assert oda_router._config_path() == Path("data/oda_canvas.json")


def test_agents_returns_stripped_names_and_ports():
    """TC-DODA-006 | _agents 返回实例清单，name 去除 -stub 后缀，port 为 int

    输入: 默认 mock_agent_define.json
    预期输出: 6 个实例，首项 id=fault-diagnosis-stub/name=fault-diagnosis/port=9005
    断言点: 数量 6 + 首项 id/name/port + name 不含 -stub + port 为 int
    防回归: 若去后缀逻辑或端口转换被改坏，本用例失败
    """
    agents = oda_router._agents()
    assert len(agents) == 6
    first = agents[0]
    assert first["id"] == "fault-diagnosis-stub"
    assert first["name"] == "fault-diagnosis"
    assert first["port"] == 9005
    assert all("-stub" not in a["name"] for a in agents)
    assert all(isinstance(a["port"], int) for a in agents)


def test_selected_agents_filters_by_config():
    """TC-DODA-007 | _selected_agents 空 selectedAgents 返回全部，指定则过滤

    输入: cfg.selectedAgents=[] 与 cfg.selectedAgents=["recovery-stub"]
    预期输出: 空=6 个；指定=1 个且 id==recovery-stub
    断言点: 空列表返回全部 + 指定返回子集 id
    防回归: 若过滤逻辑被反转或忽略，本用例失败
    """
    all_agents = oda_router._selected_agents(oda_router.OdaConfig())
    assert len(all_agents) == 6
    subset = oda_router._selected_agents(oda_router.OdaConfig(selectedAgents=["recovery-stub"]))
    assert [a["id"] for a in subset] == ["recovery-stub"]


def test_require_raises_when_field_missing():
    """TC-DODA-008 | _require 字段缺失抛 HTTPException(400) 含字段名，存在则返回 None

    输入: apiServer="" 与 apiServer="x" 的 OdaConfig
    预期输出: 缺失抛 400(detail 含 "apiServer")；存在正常返回 None
    断言点: 异常类型+状态码+detail 关键字 + 存在不抛
    防回归: 若校验被删除，本用例失败
    """
    with pytest.raises(HTTPException) as exc:
        oda_router._require("apiServer", oda_router.OdaConfig(apiServer=""))
    assert exc.value.status_code == 400
    assert "apiServer" in exc.value.detail
    assert oda_router._require("apiServer", oda_router.OdaConfig(apiServer="x")) is None


def test_client_sets_base_url_and_auth_header():
    """TC-DODA-009 | _client 带 token 注入 Authorization，无 token 不注入，base_url 取自 apiServer

    输入: apiServer=http://k8s.test,token=tok 与 apiServer=http://k8s.test,token=""
    预期输出: 带 token→base_url.host==k8s.test 且 Authorization==Bearer tok；无 token→无 Authorization
    断言点: base_url host + Authorization 头有无
    防回归: 若 Authorization 注入或 base_url 设置被改坏，本用例失败
    """
    with oda_router._client(oda_router.OdaConfig(apiServer="http://k8s.test", token="tok")) as c:
        assert c.base_url.host == "k8s.test"
        assert c.headers["authorization"] == "Bearer tok"
    with oda_router._client(oda_router.OdaConfig(apiServer="http://k8s.test")) as c:
        assert "authorization" not in c.headers


def test_apply_reports_ok_and_failure_detail():
    """TC-DODA-010 | _apply 200/201 返回 ok=True/detail=None，其它状态返回 ok=False/detail 含响应体

    输入: MockTransport 分别返回 201 与 500(text=boom)
    预期输出: 201→{ok:True,status:201,detail:None}；500→{ok:False,status:500,detail 含 boom}
    断言点: ok/status/detail 三字段
    防回归: 若 ok 判定或 detail 截取被改坏，本用例失败
    """
    cfg = oda_router.OdaConfig(namespace="components")
    obj = {"kind": "Secret", "metadata": {"name": "rel"}, "stringData": {}}
    with _REAL_CLIENT(transport=httpx.MockTransport(lambda r: httpx.Response(201, json={})), base_url="http://k8s") as c:
        res = oda_router._apply(c, cfg, "", "v1", "secrets", "rel", obj)
    assert res == {"kind": "Secret", "name": "rel", "ok": True, "status": 201, "detail": None}
    with _REAL_CLIENT(transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom")), base_url="http://k8s") as c:
        res = oda_router._apply(c, cfg, "", "v1", "secrets", "rel", obj)
    assert res["ok"] is False
    assert res["status"] == 500
    assert "boom" in res["detail"]


def test_labels_contains_release_and_component_name():
    """TC-DODA-011 | _labels 返回含 instance 与 componentName 的标签集

    输入: release="rel-1"
    预期输出: instance==rel-1, componentName==rel-1, managed-by==openan-debug, name==openan-mockagent
    断言点: 标签键值
    防回归: 若标签键名或值被改坏，本用例失败
    """
    labels = oda_router._labels("rel-1")
    assert labels["app.kubernetes.io/instance"] == "rel-1"
    assert labels["oda.tmforum.org/componentName"] == "rel-1"
    assert labels["app.kubernetes.io/managed-by"] == "openan-debug"
    assert labels["app.kubernetes.io/name"] == "openan-mockagent"


def test_manifests_default_generates_five_objects_with_dev_secret():
    """TC-DODA-012 | _manifests 默认配置生成 5 类对象，secret 用 dev 兜底，env 无 admin/autostart

    输入: 默认 OdaConfig（无 adminPassword/autoStart/publicUrl，selectedAgents 空）
    预期输出: 5 对象(Secret/PVC/Deployment/Service/Component)；Secret jwt-secret==dev-secret-change-me 且无 admin-password；env 无 ADMIN_PASSWORD/AUTOSTART；container_ports 7；exposedAPIs 7
    断言点: kinds 顺序 + secret 兜底 + env 缺省分支 + 端口/exposed 数量
    防回归: 若默认兜底或缺省分支被改坏，本用例失败
    """
    objs = oda_router._manifests(oda_router.OdaConfig())
    assert [o["kind"] for o in objs] == ["Secret", "PersistentVolumeClaim", "Deployment", "Service", "Component"]
    secret = objs[0]
    assert secret["stringData"] == {"jwt-secret": "dev-secret-change-me"}
    deploy = next(o for o in objs if o["kind"] == "Deployment")
    env = _env_map(deploy)
    assert "OPENAN_DEBUG_ADMIN_PASSWORD" not in env
    assert "OPENAN_DEBUG_AUTOSTART" not in env
    assert env["OPENAN_DEBUG_DATASET_SEARCH"]["value"] == "on"
    assert env["OPENAN_DEBUG_STUB_FALLBACK"]["value"] == "on"
    ports = deploy["spec"]["template"]["spec"]["containers"][0]["ports"]
    assert ports[0] == {"name": "http", "containerPort": 9000}
    assert {"name": "agent-recovery", "containerPort": 9006} in ports
    assert len(ports) == 7
    component = next(o for o in objs if o["kind"] == "Component")
    assert component["apiVersion"] == "oda.tmforum.org/v1beta3"
    exposed = component["spec"]["coreFunction"]["exposedAPIs"]
    assert len(exposed) == 7
    assert exposed[0]["specification"] == ["http://openan-mockagent-core:9000/openapi.json"]


def test_manifests_feature_branches_admin_autostart_publicurl_selected():
    """TC-DODA-013 | _manifests adminPassword/autoStart/publicUrl/selectedAgents/release 各分支生效

    输入: OdaConfig(adminPassword=ap,autoStart=True,publicUrl=...,selectedAgents=[recovery-stub],release=rel-1,image=img:1,componentId=CID,apiVersion=v1beta2,storageSize=5Gi,jwtSecret=js,datasetSearch=False,stubFallback=False)
    预期输出: Secret 含 admin-password；env 含 ADMIN_PASSWORD 与 AUTOSTART=recovery-stub；container_ports 2；exposed 2 且用 publicUrl；Component apiVersion v1beta2/id CID；PVC 5Gi；image img:1；开关 off
    断言点: secret + env + 端口 + exposed URL + apiVersion/id + storage + image + 开关
    防回归: 若任一分支被改坏，本用例失败
    """
    cfg = oda_router.OdaConfig(
        apiServer="http://k", image="img:1", jwtSecret="js", adminPassword="ap", autoStart=True,
        publicUrl="https://pub.example.com/base", selectedAgents=["recovery-stub"], release="rel-1",
        componentId="CID", apiVersion="v1beta2", storageSize="5Gi", datasetSearch=False, stubFallback=False,
    )
    objs = oda_router._manifests(cfg)
    secret = objs[0]
    assert secret["stringData"] == {"jwt-secret": "js", "admin-password": "ap"}
    deploy = next(o for o in objs if o["kind"] == "Deployment")
    env = _env_map(deploy)
    assert env["OPENAN_DEBUG_ADMIN_PASSWORD"]["valueFrom"]["secretKeyRef"]["key"] == "admin-password"
    assert env["OPENAN_DEBUG_AUTOSTART"]["value"] == "recovery-stub"
    assert env["OPENAN_DEBUG_DATASET_SEARCH"]["value"] == "off"
    assert env["OPENAN_DEBUG_STUB_FALLBACK"]["value"] == "off"
    assert deploy["spec"]["template"]["spec"]["containers"][0]["image"] == "img:1"
    ports = deploy["spec"]["template"]["spec"]["containers"][0]["ports"]
    assert ports == [{"name": "http", "containerPort": 9000}, {"name": "agent-recovery", "containerPort": 9006}]
    pvc = next(o for o in objs if o["kind"] == "PersistentVolumeClaim")
    assert pvc["spec"]["resources"]["requests"]["storage"] == "5Gi"
    service = next(o for o in objs if o["kind"] == "Service")
    assert service["metadata"]["name"] == "rel-1-core"
    component = next(o for o in objs if o["kind"] == "Component")
    assert component["apiVersion"] == "oda.tmforum.org/v1beta2"
    assert component["spec"]["id"] == "CID"
    exposed = component["spec"]["coreFunction"]["exposedAPIs"]
    assert len(exposed) == 2
    assert exposed[0]["specification"] == ["https://pub.example.com/base/openapi.json"]
    assert exposed[0]["developerUI"] == "https://pub.example.com/base/docs"
    assert exposed[1]["name"] == "mockagent-recovery"


def test_plural_maps_kinds_and_raises_unknown():
    """TC-DODA-014 | _plural 映射 5 类 kind 到复数，未知 kind 抛 KeyError

    输入: Secret/PersistentVolumeClaim/Deployment/Service/Component 与 "Pod"
    预期输出: secrets/persistentvolumeclaims/deployments/services/components；Pod→KeyError
    断言点: 5 个映射值 + 未知抛 KeyError
    防回归: 若映射表被改坏，本用例失败
    """
    assert oda_router._plural("Secret") == "secrets"
    assert oda_router._plural("PersistentVolumeClaim") == "persistentvolumeclaims"
    assert oda_router._plural("Deployment") == "deployments"
    assert oda_router._plural("Service") == "services"
    assert oda_router._plural("Component") == "components"
    with pytest.raises(KeyError):
        oda_router._plural("Pod")


# ---------- /agents endpoint ----------
def test_list_agents_returns_define_instances(client, admin_token):
    """TC-DODA-015 | GET /agents 返回 define 中的实例，running 恒为 False

    输入: admin token GET /agents
    预期输出: 200，agents 6 项，首项 id=fault-diagnosis-stub/name=故障诊断打桩 Agent/port=9005/running=False
    断言点: 数量 + 首项字段 + running False
    防回归: 若字段映射或 running 被改为真实探测，本用例失败
    """
    resp = client.get("/api/v1/console/oda/agents", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    agents = resp.json()["agents"]
    assert len(agents) == 6
    first = agents[0]
    assert first["id"] == "fault-diagnosis-stub"
    assert first["name"] == "故障诊断打桩 Agent"
    assert first["port"] == 9005
    assert first["running"] is False


def test_list_agents_requires_auth(client):
    """TC-DODA-016 | 无 token GET /agents 返回 401

    输入: 不带 Authorization
    预期输出: 401
    断言点: 状态码
    防回归: 鉴权依赖被移除则失败
    """
    assert client.get("/api/v1/console/oda/agents").status_code == 401


# ---------- /test-connection endpoint ----------
def test_test_connection_success(client, admin_token, oda_config_path, monkeypatch):
    """TC-DODA-017 | POST /test-connection 成功：返回 k8sVersion/componentCrd/versions/namespaceReachable

    输入: 配置 apiServer，mock /version 200、/apis/oda.tmforum.org 200(versions)、namespace 200
    预期输出: 200，k8sVersion==v1.30.0，componentCrd True，versions==[v1beta3,v1beta2]，namespaceReachable True，无 namespaceError
    断言点: 各字段值 + 无 namespaceError
    防回归: 若字段映射或可达性判定被改坏，本用例失败
    """
    def handler(request):
        p = request.url.path
        if p == "/version":
            return httpx.Response(200, json={"gitVersion": "v1.30.0"})
        if p == "/apis/oda.tmforum.org":
            return httpx.Response(200, json={"versions": [{"version": "v1beta3"}, {"version": "v1beta2"}]})
        if p == "/api/v1/namespaces/components":
            return httpx.Response(200, json={"kind": "Namespace"})
        return httpx.Response(404, text="nope")

    _install_mock_k8s(monkeypatch, handler)
    _write_config(oda_config_path)
    resp = client.post("/api/v1/console/oda/test-connection", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["k8sVersion"] == "v1.30.0"
    assert out["componentCrd"] is True
    assert out["versions"] == ["v1beta3", "v1beta2"]
    assert out["namespaceReachable"] is True
    assert "namespaceError" not in out


def test_test_connection_version_unreachable_502(client, admin_token, oda_config_path, monkeypatch):
    """TC-DODA-018 | POST /test-connection /version 非 200 返回 502

    输入: mock /version 返回 500
    预期输出: 502，detail 含 "API Server 不可达" 与 "500"
    断言点: 状态码 502 + detail 关键字
    防回归: 若 502 分支被改为其它状态或文案，本用例失败
    """
    def handler(request):
        if request.url.path == "/version":
            return httpx.Response(500, text="down")
        return httpx.Response(200, json={})

    _install_mock_k8s(monkeypatch, handler)
    _write_config(oda_config_path)
    resp = client.post("/api/v1/console/oda/test-connection", headers=auth_header(admin_token))
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "API Server 不可达" in detail
    assert "500" in detail


def test_test_connection_namespace_404_sets_error(client, admin_token, oda_config_path, monkeypatch):
    """TC-DODA-019 | POST /test-connection 命名空间 404 → namespaceReachable=False 且 namespaceError 含 "不存在"

    输入: mock /version 200、/apis 200、namespace 404
    预期输出: namespaceReachable False，namespaceError 含 "不存在"，componentCrd True，versions 非空
    断言点: namespaceReachable + namespaceError + componentCrd
    防回归: 若 404 分支被删除，本用例失败
    """
    def handler(request):
        p = request.url.path
        if p == "/version":
            return httpx.Response(200, json={"gitVersion": "v1.30.0"})
        if p == "/apis/oda.tmforum.org":
            return httpx.Response(200, json={"versions": [{"version": "v1beta3"}]})
        if p == "/api/v1/namespaces/components":
            return httpx.Response(404, json={})
        return httpx.Response(404, text="nope")

    _install_mock_k8s(monkeypatch, handler)
    _write_config(oda_config_path)
    resp = client.post("/api/v1/console/oda/test-connection", headers=auth_header(admin_token))
    assert resp.status_code == 200
    out = resp.json()
    assert out["namespaceReachable"] is False
    assert "不存在" in out["namespaceError"]
    assert out["componentCrd"] is True
    assert out["versions"] == ["v1beta3"]


def test_test_connection_crd_absent_returns_false_empty_versions(client, admin_token, oda_config_path, monkeypatch):
    """TC-DODA-020 | POST /test-connection CRD 组不存在 → componentCrd=False，versions=[]

    输入: mock /version 200、/apis/oda.tmforum.org 404、namespace 200
    预期输出: componentCrd False，versions==[]，namespaceReachable True
    断言点: componentCrd + versions 空列表 + namespaceReachable
    防回归: 若 else 分支被改坏，本用例失败
    """
    def handler(request):
        p = request.url.path
        if p == "/version":
            return httpx.Response(200, json={"gitVersion": "v1.30.0"})
        if p == "/apis/oda.tmforum.org":
            return httpx.Response(404, json={})
        if p == "/api/v1/namespaces/components":
            return httpx.Response(200, json={"kind": "Namespace"})
        return httpx.Response(404, text="nope")

    _install_mock_k8s(monkeypatch, handler)
    _write_config(oda_config_path)
    resp = client.post("/api/v1/console/oda/test-connection", headers=auth_header(admin_token))
    assert resp.status_code == 200
    out = resp.json()
    assert out["componentCrd"] is False
    assert out["versions"] == []
    assert out["namespaceReachable"] is True


def test_test_connection_requires_auth(client):
    """TC-DODA-021 | 无 token POST /test-connection 返回 401

    输入: 不带 Authorization
    预期输出: 401
    断言点: 状态码
    防回归: 鉴权依赖被移除则失败
    """
    assert client.post("/api/v1/console/oda/test-connection").status_code == 401


def test_test_connection_no_api_server_400(client, admin_token, oda_config_path):
    """TC-DODA-022 | POST /test-connection 未配置 apiServer 返回 400

    输入: 配置文件为空(默认 apiServer="")，POST /test-connection
    预期输出: 400，detail 含 "请先配置 apiServer"
    断言点: 状态码 400 + detail 关键字
    防回归: 若 _require 缺失或字段名错误，本用例失败
    """
    resp = client.post("/api/v1/console/oda/test-connection", headers=auth_header(admin_token))
    assert resp.status_code == 400
    assert "请先配置 apiServer" in resp.json()["detail"]


# ---------- /deploy endpoint ----------
def test_deploy_success_namespace_exists(client, admin_token, oda_config_path, monkeypatch):
    """TC-DODA-023 | POST /deploy 命名空间已存在时仅 apply 5 对象，全部成功 ok=True

    输入: 配置含 apiServer/image，mock namespace GET 200、所有 PATCH 201
    预期输出: 200，ok=True，results 5 项，kinds 顺序正确且全部 ok
    断言点: ok + results 数量 + kinds + 各项 ok
    防回归: 若 apply 顺序或 ok 聚合被改坏，本用例失败
    """
    def handler(request):
        p = request.url.path
        m = request.method
        if m == "GET" and p == "/api/v1/namespaces/components":
            return httpx.Response(200, json={"kind": "Namespace"})
        if m == "PATCH":
            return httpx.Response(201, json={})
        return httpx.Response(404, text="nope")

    _install_mock_k8s(monkeypatch, handler)
    _write_config(oda_config_path)
    resp = client.post("/api/v1/console/oda/deploy", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    results = body["results"]
    assert len(results) == 5
    assert [r["kind"] for r in results] == ["Secret", "PersistentVolumeClaim", "Deployment", "Service", "Component"]
    assert all(r["ok"] is True for r in results)
    assert all(r["status"] == 201 for r in results)


def test_deploy_creates_namespace_when_missing(client, admin_token, oda_config_path, monkeypatch):
    """TC-DODA-024 | POST /deploy 命名空间 404 时自动创建，Namespace 结果 ok=True

    输入: mock namespace GET 404、POST 201、所有 PATCH 201
    预期输出: ok=True，results 6 项，首项 kind=Namespace/status=201/ok=True
    断言点: ok + results 数量 6 + Namespace 项状态
    防回归: 若命名空间创建分支被删除，本用例失败
    """
    def handler(request):
        p = request.url.path
        m = request.method
        if m == "GET" and p == "/api/v1/namespaces/components":
            return httpx.Response(404, json={})
        if m == "POST" and p == "/api/v1/namespaces":
            return httpx.Response(201, json={"kind": "Namespace"})
        if m == "PATCH":
            return httpx.Response(201, json={})
        return httpx.Response(404, text="nope")

    _install_mock_k8s(monkeypatch, handler)
    _write_config(oda_config_path)
    resp = client.post("/api/v1/console/oda/deploy", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    results = body["results"]
    assert len(results) == 6
    assert results[0]["kind"] == "Namespace"
    assert results[0]["name"] == "components"
    assert results[0]["ok"] is True
    assert results[0]["status"] == 201


def test_deploy_no_image_400(client, admin_token, oda_config_path):
    """TC-DODA-025 | POST /deploy 未配置 image 返回 400

    输入: 配置 apiServer 已设但 image=""
    预期输出: 400，detail 含 "请先配置 image"
    断言点: 状态码 400 + detail 关键字
    防回归: 若 image 校验被移除或顺序错误(先查 apiServer)，本用例失败
    """
    _write_config(oda_config_path, image="")
    resp = client.post("/api/v1/console/oda/deploy", headers=auth_header(admin_token))
    assert resp.status_code == 400
    assert "请先配置 image" in resp.json()["detail"]


def test_deploy_partial_apply_failure_ok_false(client, admin_token, oda_config_path, monkeypatch):
    """TC-DODA-026 | POST /deploy 某 apply 失败(500) → ok=False，失败项 detail 含响应体

    输入: mock namespace 200，Deployment PATCH 500(deploy-failed)，其余 PATCH 201
    预期输出: ok=False，Deployment 项 ok=False/status=500/detail 含 deploy-failed，其余 ok
    断言点: ok False + 失败项 detail + 其余项 ok
    防回归: 若失败聚合或 detail 截取被改坏，本用例失败
    """
    def handler(request):
        p = request.url.path
        m = request.method
        if m == "GET" and p == "/api/v1/namespaces/components":
            return httpx.Response(200, json={})
        if m == "PATCH" and "/deployments/" in p:
            return httpx.Response(500, text="deploy-failed")
        if m == "PATCH":
            return httpx.Response(201, json={})
        return httpx.Response(404, text="nope")

    _install_mock_k8s(monkeypatch, handler)
    _write_config(oda_config_path)
    resp = client.post("/api/v1/console/oda/deploy", headers=auth_header(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    results = body["results"]
    dep = next(r for r in results if r["kind"] == "Deployment")
    assert dep["ok"] is False
    assert dep["status"] == 500
    assert "deploy-failed" in dep["detail"]
    assert all(r["ok"] is True for r in results if r["kind"] != "Deployment")


def test_deploy_requires_auth(client):
    """TC-DODA-027 | 无 token POST /deploy 返回 401

    输入: 不带 Authorization
    预期输出: 401
    断言点: 状态码
    防回归: 鉴权依赖被移除则失败
    """
    assert client.post("/api/v1/console/oda/deploy").status_code == 401


# ---------- /status endpoint ----------
def test_status_deployed_returns_component_pods_service(client, admin_token, oda_config_path, monkeypatch):
    """TC-DODA-028 | GET /status 组件已部署 → 返回 deploymentStatus/exposedAPIs/pods/service

    输入: 配置 apiServer，mock 组件 200(summary.deployment_status=deployed, exposedAPIs 2)、pods 200(1 项)、service 200(clusterIP)
    预期输出: release/namespace 正确，deploymentStatus==deployed，exposedAPIs==2，pods 1 项字段正确，service.exists True/clusterIP，selectedAgents 6
    断言点: 组件状态 + pods 字段 + service + selectedAgents 数量
    防回归: 若 status 解析或 pods/service 字段映射被改坏，本用例失败
    """
    def handler(request):
        p = request.url.path
        if "/oda.tmforum.org/" in p and p.endswith("/components/openan-mockagent"):
            return httpx.Response(200, json={
                "status": {"summary": {"status": {"deployment_status": "deployed"}}},
                "spec": {"coreFunction": {"exposedAPIs": [{"name": "a"}, {"name": "b"}]}},
            })
        if p.endswith("/namespaces/components/pods"):
            return httpx.Response(200, json={"items": [
                {"metadata": {"name": "pod-1"},
                 "status": {"phase": "Running",
                            "containerStatuses": [{"ready": True, "restartCount": 2, "image": "img:1"}]}}]})
        if p.endswith("/services/openan-mockagent-core"):
            return httpx.Response(200, json={"spec": {"clusterIP": "10.0.0.1"}})
        return httpx.Response(404, text="nope")

    _install_mock_k8s(monkeypatch, handler)
    _write_config(oda_config_path)
    resp = client.get("/api/v1/console/oda/status", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["release"] == "openan-mockagent"
    assert out["namespace"] == "components"
    assert out["component"]["deploymentStatus"] == "deployed"
    assert out["component"]["exposedAPIs"] == 2
    assert len(out["selectedAgents"]) == 6
    pods = out["pods"]
    assert len(pods) == 1
    assert pods[0]["name"] == "pod-1"
    assert pods[0]["phase"] == "Running"
    assert pods[0]["ready"] is True
    assert pods[0]["restarts"] == 2
    assert pods[0]["image"] == "img:1"
    assert out["service"]["exists"] is True
    assert out["service"]["clusterIP"] == "10.0.0.1"
    assert out["service"]["name"] == "openan-mockagent-core"


def test_status_undeployed_component_404(client, admin_token, oda_config_path, monkeypatch):
    """TC-DODA-029 | GET /status 组件 404 → 未部署状态，pods/service 不可达时空值

    输入: mock 组件 404、pods 500、service 404
    预期输出: component.deploymentStatus 含 "未部署(HTTP 404)"，pods==[]，service.exists False/clusterIP None
    断言点: 未部署文案 + pods 空 + service.exists False + clusterIP None
    防回归: 若 404 分支或 pods/service 缺省处理被改坏，本用例失败
    """
    def handler(request):
        p = request.url.path
        if "/oda.tmforum.org/" in p and p.endswith("/components/openan-mockagent"):
            return httpx.Response(404, json={})
        if p.endswith("/namespaces/components/pods"):
            return httpx.Response(500, text="err")
        if p.endswith("/services/openan-mockagent-core"):
            return httpx.Response(404, json={})
        return httpx.Response(404, text="nope")

    _install_mock_k8s(monkeypatch, handler)
    _write_config(oda_config_path)
    resp = client.get("/api/v1/console/oda/status", headers=auth_header(admin_token))
    assert resp.status_code == 200
    out = resp.json()
    assert "未部署(HTTP 404)" in out["component"]["deploymentStatus"]
    assert out["pods"] == []
    assert out["service"]["exists"] is False
    assert out["service"]["clusterIP"] is None


def test_status_requires_auth(client):
    """TC-DODA-030 | 无 token GET /status 返回 401

    输入: 不带 Authorization
    预期输出: 401
    断言点: 状态码
    防回归: 鉴权依赖被移除则失败
    """
    assert client.get("/api/v1/console/oda/status").status_code == 401


def test_status_no_api_server_400(client, admin_token, oda_config_path):
    """TC-DODA-031 | GET /status 未配置 apiServer 返回 400

    输入: 配置文件为空(默认 apiServer="")
    预期输出: 400，detail 含 "请先配置 apiServer"
    断言点: 状态码 400 + detail 关键字
    防回归: 若 apiServer 校验被移除，本用例失败
    """
    resp = client.get("/api/v1/console/oda/status", headers=auth_header(admin_token))
    assert resp.status_code == 400
    assert "请先配置 apiServer" in resp.json()["detail"]


# ---------- /undeploy endpoint ----------
def test_undeploy_success_all_deleted(client, admin_token, oda_config_path, monkeypatch):
    """TC-DODA-032 | POST /undeploy 全部删除 200 → ok=True，4 项结果

    输入: 配置 apiServer，mock 所有 DELETE 200
    预期输出: ok=True，results 4 项，kinds==[components,deployments,services,secrets]，全部 ok/status 200
    断言点: ok + results 数量 + kinds + 各项 ok/status
    防回归: 若删除目标列表或 ok 聚合被改坏，本用例失败
    """
    _install_mock_k8s(monkeypatch, lambda r: httpx.Response(200, json={}))
    _write_config(oda_config_path)
    resp = client.post("/api/v1/console/oda/undeploy", headers=auth_header(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    results = body["results"]
    assert len(results) == 4
    assert [r["kind"] for r in results] == ["components", "deployments", "services", "secrets"]
    assert all(r["ok"] is True for r in results)
    assert all(r["status"] == 200 for r in results)


def test_undeploy_partial_failure_ok_false(client, admin_token, oda_config_path, monkeypatch):
    """TC-DODA-033 | POST /undeploy component 删除 500 → 该项 ok=False，整体 ok=False

    输入: mock component DELETE 500，其余 DELETE 200
    预期输出: ok=False，components 项 ok=False/status=500，其余 ok
    断言点: ok False + components 项状态 + 其余 ok
    防回归: 若 500 不计为失败或目标顺序改变，本用例失败
    """
    def handler(request):
        if request.url.path.endswith("/components/openan-mockagent"):
            return httpx.Response(500, text="del-fail")
        return httpx.Response(200, json={})

    _install_mock_k8s(monkeypatch, handler)
    _write_config(oda_config_path)
    resp = client.post("/api/v1/console/oda/undeploy", headers=auth_header(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    results = body["results"]
    assert results[0]["kind"] == "components"
    assert results[0]["ok"] is False
    assert results[0]["status"] == 500
    assert all(r["ok"] is True for r in results[1:])


def test_undeploy_requires_auth(client):
    """TC-DODA-034 | 无 token POST /undeploy 返回 401

    输入: 不带 Authorization
    预期输出: 401
    断言点: 状态码
    防回归: 鉴权依赖被移除则失败
    """
    assert client.post("/api/v1/console/oda/undeploy").status_code == 401


def test_undeploy_no_api_server_400(client, admin_token, oda_config_path):
    """TC-DODA-035 | POST /undeploy 未配置 apiServer 返回 400

    输入: 配置文件为空(默认 apiServer="")
    预期输出: 400，detail 含 "请先配置 apiServer"
    断言点: 状态码 400 + detail 关键字
    防回归: 若 apiServer 校验被移除，本用例失败
    """
    resp = client.post("/api/v1/console/oda/undeploy", headers=auth_header(admin_token))
    assert resp.status_code == 400
    assert "请先配置 apiServer" in resp.json()["detail"]
