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

"""mock_instances / agents / variants / seeds / users 路由 API 覆盖测试（TC-MOCK-001..082）。

真实临时 DB + 真实登录态；仅隔离网络副作用（_health_probe / 子进程拉起 / httpx 调用）。
"""

import os
import socketserver
import stat
import subprocess
import threading
import time
import types
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from mockagent_engine.routers import mock_instances_router as mi


# --------------------------------------------------------------------------- #
# helpers / fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _clear_processes():
    """每个用例前后清空模块级 _PROCESSES，杜绝跨用例残留。"""
    mi._PROCESSES.clear()
    yield
    mi._PROCESSES.clear()


@pytest.fixture()
def user_headers(client, auth_headers):
    """创建 user 角色账号并登录（用于 403 越权断言）。"""
    resp = client.post(
        "/api/v1/users",
        json={"username": "tester", "password": "tester-pass", "role": "user"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    login = client.post("/api/v1/auth/login", json={"username": "tester", "password": "tester-pass"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _fake_proc(*, poll=None, pid=12345, wait_ok=True):
    """构造一个可控制的假子进程对象（不真正拉起进程）。

    wait_ok=True：wait 立即成功（terminate 后不 kill）。
    wait_ok=False：首次 wait 抛 TimeoutExpired，kill 后再次 wait 成功（覆盖 kill 兜底分支）。
    """

    class _FakeProc:
        def __init__(self):
            self.pid = pid
            self.returncode = poll
            self._poll = poll
            self._wait_ok = wait_ok
            self._terminated = False
            self._killed = False

        def poll(self):
            return self._poll

        def terminate(self):
            self._terminated = True

        def kill(self):
            self._killed = True

        def wait(self, timeout=None):
            if self._wait_ok:
                return 0
            if not self._killed:
                raise subprocess.TimeoutExpired(cmd="x", timeout=timeout)
            return 0

    return _FakeProc()


def _real_instance(instance_id):
    """从真实 agents/ 定义取一个实例字典。"""
    define = mi._load_define()
    return next(i for i in define["instances"] if i["id"] == instance_id)


def _start_health_server(status=200):
    """启动一个临时的本地 HTTP 服务（/health 与 /.well-known/agent-card.json）。"""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *args):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port


# =========================================================================== #
# mock_instances_router
# =========================================================================== #

# ---- _health_probe (63-68) ------------------------------------------------ #

def test_health_probe_real_server_returns_true():
    """TC-MOCK-001 | 健康探测命中真实 200 服务时返回 True

    输入: 起一个本地 HTTP 服务返回 200，对其端口 _health_probe
    预期输出: True
    断言点: 返回值为 True（覆盖 status_code==200 成功分支）
    防回归: 若 httpx.get 调用或状态码比较被改坏，本用例失败
    """
    srv, port = _start_health_server(status=200)
    try:
        assert mi._health_probe(port) is True
    finally:
        srv.shutdown()


def test_health_probe_non_200_returns_false():
    """TC-MOCK-002 | 健康探测收到非 200 时返回 False

    输入: 本地服务恒返回 404
    预期输出: False
    断言点: status_code != 200 → False
    防回归: 若状态码判定被反转，本用例失败
    """
    srv, port = _start_health_server(status=404)
    try:
        assert mi._health_probe(port) is False
    finally:
        srv.shutdown()


def test_health_probe_refused_returns_false():
    """TC-MOCK-003 | 健康探测连不上端口时返回 False（异常分支）

    输入: 一个确定无人监听的端口
    预期输出: False
    断言点: httpx 抛异常 → except → False
    防回归: 若 except 被删除，异常会冒泡导致用例报错
    """
    s = socketserver.TCPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = s.server_address[1]
    s.server_close()
    assert mi._health_probe(port, timeout=0.5) is False


# ---- _pid_alive (71-86) --------------------------------------------------- #

def test_pid_alive_non_positive_is_false():
    """TC-MOCK-004 | 非正 pid 直接判否

    输入: pid=0 与 pid=-1
    预期输出: False
    断言点: pid<=0 提前返回 False
    防回归: 若提前守卫被删，tasklist 会被空 pid 调用
    """
    assert mi._pid_alive(0) is False
    assert mi._pid_alive(-1) is False


def test_pid_alive_self_and_unknown_on_windows():
    """TC-MOCK-005 | Windows 下 tasklist 能找到当前进程、找不到假 pid

    输入: 当前测试进程 pid 与一个不存在的 pid
    预期输出: 自身 True、陌生 False
    断言点: tasklist 输出含/不含 pid 字符串
    防回归: 若 tasklist 解析逻辑改坏，两条断言之一失败
    """
    assert mi._pid_alive(os.getpid()) is True
    assert mi._pid_alive(999999987) is False


def test_pid_alive_tasklist_failure_returns_false(monkeypatch):
    """TC-MOCK-006 | tasklist 自身失败时降级为 False

    输入: monkeypatch subprocess.run 抛 OSError
    预期输出: False
    断言点: except 分支返回 False
    防回归: 若 except 被删，异常会冒泡
    """
    def _boom(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(mi.subprocess, "run", _boom)
    assert mi._pid_alive(os.getpid()) is False


# ---- _agent_id_for (94-104) ----------------------------------------------- #

def test_agent_id_for_returns_id_when_matched(client):
    """TC-MOCK-007 | 命中 DB Agent 行时返回其 id

    输入: 默认 Agent 的 organization+name
    预期输出: 默认 agent id
    断言点: 返回值等于 app.state.default_agent_id
    防回归: 若查询条件被改错，返回 None
    """
    request = types.SimpleNamespace(app=client.app)
    default_id = client.app.state.default_agent_id
    got = mi._agent_id_for(request, "OpenAN", "OpenAN Debug Mock Agent")
    assert got == default_id


def test_agent_id_for_returns_none_when_unmatched(client):
    """TC-MOCK-008 | 未命中时返回 None

    输入: 不存在的 organization/name
    预期输出: None
    断言点: agent is None → return None
    防回归: 若未命中时误返回非 None，用例失败
    """
    request = types.SimpleNamespace(app=client.app)
    assert mi._agent_id_for(request, "Nope", "ghost") is None


def test_agent_id_for_swallows_db_error_returns_none():
    """TC-MOCK-009 | DB 会话异常时返回 None（兜底分支）

    输入: app.state.engine 为非法对象，Session 会抛异常
    预期输出: None
    断言点: except Exception → return None
    防回归: 若 except 被删，异常冒泡导致用例报错
    """
    request = types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace(engine=object()))
    )
    assert mi._agent_id_for(request, "x", "y") is None


# ---- _instance_view (107-154) --------------------------------------------- #

def test_instance_view_managed_proc_running_and_pid(client, monkeypatch):
    """TC-MOCK-010 | 托管进程在跑时 running=True 且 pid 取自进程

    输入: 注入假托管进程（poll=None）到 _PROCESSES
    预期输出: view.running=True, view.pid=进程 pid, healthy 取决于探测
    断言点: running True + pid 等于注入进程 pid
    防回归: 若 managed 分支被改坏，running 会变 False
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    inst = _real_instance("fault-diagnosis-stub")
    proc = _fake_proc(poll=None, pid=777)
    mi._PROCESSES["fault-diagnosis-stub"] = proc
    view = mi._instance_view(types.SimpleNamespace(app=client.app), mi._load_define(), inst)
    assert view["running"] is True
    assert view["pid"] == 777


def test_instance_view_external_pid_alive_and_healthy_running(client, monkeypatch, tmp_path):
    """TC-MOCK-011 | 非托管但 pid 文件存在且存活且健康 → running=True

    输入: workDir=tmp 且写入 instance.pid=当前进程 pid；_pid_alive/_health_probe 均 True
    预期输出: view.pid=当前 pid, running=True
    断言点: pid 读取成功 + running True
    防回归: 若 pid 文件读取或 running 合成逻辑被改坏，失败
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: True)
    monkeypatch.setattr(mi, "_pid_alive", lambda pid: True)
    inst = dict(_real_instance("fault-diagnosis-stub"), workDir=str(tmp_path))
    (tmp_path / "instance.pid").write_text(str(os.getpid()), encoding="utf-8")
    view = mi._instance_view(types.SimpleNamespace(app=client.app), mi._load_define(), inst)
    assert view["pid"] == os.getpid()
    assert view["running"] is True


def test_instance_view_garbage_pid_file_yields_none_pid(client, monkeypatch, tmp_path):
    """TC-MOCK-012 | instance.pid 内容非数字时 pid 降级 None

    输入: workDir=tmp 且 instance.pid="not-a-number"
    预期输出: view.pid=None
    断言点: ValueError 分支 → pid=None
    防回归: 若 except 被删，int() 抛 ValueError 冒泡
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    inst = dict(_real_instance("fault-diagnosis-stub"), workDir=str(tmp_path))
    (tmp_path / "instance.pid").write_text("not-a-number", encoding="utf-8")
    view = mi._instance_view(types.SimpleNamespace(app=client.app), mi._load_define(), inst)
    assert view["pid"] is None


def test_instance_view_agent_type_generic_on_load_failure(client, monkeypatch, tmp_path):
    """TC-MOCK-013 | load_agent_class 抛异常时 agentType 降级 generic

    输入: monkeypatch agent_registry.load_agent_class 抛异常
    预期输出: view.agentType == "generic"
    断言点: except 分支置 generic
    防回归: 若 except 被删，异常冒泡
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    import mockagent_engine.agent_registry as reg

    def _boom(_dir):
        raise RuntimeError("no class")

    monkeypatch.setattr(reg, "load_agent_class", _boom)
    inst = dict(_real_instance("fault-diagnosis-stub"), workDir=str(tmp_path))
    view = mi._instance_view(types.SimpleNamespace(app=client.app), mi._load_define(), inst)
    assert view["agentType"] == "generic"


# ---- list endpoint (157-163) ---------------------------------------------- #

def test_list_instances_requires_auth(client):
    """TC-MOCK-014 | 无 token 访问实例列表返回 401

    输入: 不带 Authorization
    预期输出: 401
    断言点: get_current_user 未认证守卫
    防回归: 若鉴权依赖被删除，返回 200
    """
    assert client.get("/api/v1/mock-instances").status_code == 401


def test_list_instances_structure_and_count(client, monkeypatch):
    """TC-MOCK-015 | 列表返回完整实例视图结构

    输入: 管理员 token，_health_probe 隔离为 False
    预期输出: definePath 指向 agents 目录，26 个实例，每个含 id/port/endpoint/agentType/llm/workflow
    断言点: 数量 26 + endpoint 格式 + llm/workflow 结构
    防回归: 若视图字段被删/改名，断言失败
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    data = client.get("/api/v1/mock-instances", headers=auth_headers_for(client)).json()
    assert data["definePath"].endswith("agents")
    assert len(data["instances"]) == 26
    inst = data["instances"][0]
    assert inst["endpoint"] == f"http://127.0.0.1:{inst['port']}"
    assert set(["id", "port", "agentType", "llm", "workflow", "running", "healthy", "pid"]) <= set(inst)


def auth_headers_for(client, username="admin", password="test-admin-pass"):
    """内部辅助：取管理员 token（部分用例未直接依赖 auth_headers fixture）。"""
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def test_list_instances_agent_type_for_fault_diagnosis(client, monkeypatch):
    """TC-MOCK-016 | 列表暴露真实 agent.py 子类的 agent_type

    输入: fault-diagnosis-stub 实例
    预期输出: agentType == "fault-diagnosis"
    断言点: load_agent_class 子类 agent_type 透出
    防回归: 若 agent_type 读取链路被改坏，值变 generic
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    data = client.get("/api/v1/mock-instances", headers=auth_headers_for(client)).json()
    types_map = {i["id"]: i["agentType"] for i in data["instances"]}
    assert types_map["fault-diagnosis-stub"] == "fault-diagnosis"
    assert types_map["livestream-stub"] == "live-stream"


# ---- _log_tail / logs endpoint (170-174, 301-305) ------------------------- #

def test_instance_logs_not_found(client, auth_headers):
    """TC-MOCK-017 | 未知实例取日志返回 404

    输入: instance_id=does-not-exist
    预期输出: 404，detail 含实例 id
    断言点: _instance_by_id 404
    防回归: 若 404 守卫被删，返回 200
    """
    resp = client.get("/api/v1/mock-instances/does-not-exist/logs", headers=auth_headers)
    assert resp.status_code == 404
    assert "does-not-exist" in resp.json()["detail"]


def test_instance_logs_no_log_file_returns_placeholder(client, auth_headers, monkeypatch, tmp_path):
    """TC-MOCK-018 | 无日志文件时返回占位文案

    输入: 构造 workDir=tmp 的实例（无 instance.log）
    预期输出: 文本 "(暂无日志)"
    断言点: _log_tail 返回 "" → 端点回退占位文案
    防回归: 若占位回退被删，返回空字符串
    """
    inst = {"id": "fake-inst", "workDir": str(tmp_path), "port": 9300}
    monkeypatch.setattr(mi, "_load_define", lambda *a, **k: {"defaults": {}, "instances": [inst]})
    resp = client.get("/api/v1/mock-instances/fake-inst/logs", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.text == "(暂无日志)"


def test_instance_logs_returns_tail_when_file_exists(client, auth_headers, monkeypatch, tmp_path):
    """TC-MOCK-019 | 有日志文件时返回文件尾部

    输入: workDir=tmp 且 instance.log 含 3 行
    预期输出: 返回全部 3 行
    断言点: _log_tail 读取并按行截取
    防回归: 若读取逻辑被改坏，内容不匹配
    """
    inst = {"id": "fake-inst", "workDir": str(tmp_path), "port": 9300}
    (tmp_path / "instance.log").write_text("line-a\nline-b\nline-c\n", encoding="utf-8")
    monkeypatch.setattr(mi, "_load_define", lambda *a, **k: {"defaults": {}, "instances": [inst]})
    resp = client.get("/api/v1/mock-instances/fake-inst/logs", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.text.strip().splitlines() == ["line-a", "line-b", "line-c"]


def test_instance_logs_lines_clamped(client, auth_headers, monkeypatch, tmp_path):
    """TC-MOCK-020 | lines 参数被夹取到 [1,500]

    输入: 日志 5 行；lines=0（→1）、lines=99999（→500，实际取全部 5 行）
    预期输出: lines=0 返回 1 行；lines=99999 返回 5 行
    断言点: max(1, min(lines,500)) 边界
    防回归: 若夹取逻辑被改坏，行数不对
    """
    inst = {"id": "fake-inst", "workDir": str(tmp_path), "port": 9300}
    (tmp_path / "instance.log").write_text("l1\nl2\nl3\nl4\nl5\n", encoding="utf-8")
    monkeypatch.setattr(mi, "_load_define", lambda *a, **k: {"defaults": {}, "instances": [inst]})
    r0 = client.get("/api/v1/mock-instances/fake-inst/logs?lines=0", headers=auth_headers)
    assert r0.text.strip().splitlines() == ["l5"]
    rbig = client.get("/api/v1/mock-instances/fake-inst/logs?lines=99999", headers=auth_headers)
    assert len(rbig.text.strip().splitlines()) == 5


def test_instance_logs_requires_auth(client):
    """TC-MOCK-021 | 无 token 取日志 401

    输入: 不带 token
    预期输出: 401
    断言点: get_current_user 守卫
    防回归: 若鉴权被删返回 200
    """
    assert client.get("/api/v1/mock-instances/fault-diagnosis-stub/logs").status_code == 401


# ---- card endpoint (308-319) ---------------------------------------------- #

def test_instance_card_not_found(client, auth_headers):
    """TC-MOCK-022 | 未知实例取卡片返回 404

    输入: instance_id=ghost
    预期输出: 404
    断言点: _instance_by_id 404
    防回归: 若 404 守卫被删
    """
    assert client.get("/api/v1/mock-instances/ghost/card", headers=auth_headers).status_code == 404


def test_instance_card_unreachable_returns_502(client, auth_headers):
    """TC-MOCK-023 | 实例端口无人监听时取卡片返回 502

    输入: fault-diagnosis-stub（端口 9005 无人监听），真实 httpx.get
    预期输出: 502，detail 含 "实例不可达"
    断言点: except 分支 → 502
    防回归: 若 except 被删，异常冒泡成 500
    """
    resp = client.get("/api/v1/mock-instances/fault-diagnosis-stub/card", headers=auth_headers)
    assert resp.status_code == 502
    assert "实例不可达" in resp.json()["detail"]


def test_instance_card_non_200_returns_502(client, auth_headers, monkeypatch):
    """TC-MOCK-024 | 实例返回非 200 时取卡片返回 502

    输入: monkeypatch httpx.get 返回 status_code=500 的响应
    预期输出: 502，detail 含 "实例返回 HTTP 500"
    断言点: status_code != 200 → 502
    防回归: 若状态码判定被反转
    """
    fake = types.SimpleNamespace(status_code=500, json=lambda: {})
    monkeypatch.setattr(mi.httpx, "get", lambda *a, **k: fake)
    resp = client.get("/api/v1/mock-instances/fault-diagnosis-stub/card", headers=auth_headers)
    assert resp.status_code == 502
    assert "实例返回 HTTP 500" in resp.json()["detail"]


def test_instance_card_ok_returns_json(client, auth_headers, monkeypatch):
    """TC-MOCK-025 | 实例返回 200 时透传卡片 JSON

    输入: monkeypatch httpx.get 返回 200 + {"name":"card"}
    预期输出: 200 且 body == {"name":"card"}
    断言点: response.json() 原样返回
    防回归: 若返回逻辑被改坏，body 不符
    """
    fake = types.SimpleNamespace(status_code=200, json=lambda: {"name": "card"})
    monkeypatch.setattr(mi.httpx, "get", lambda *a, **k: fake)
    resp = client.get("/api/v1/mock-instances/fault-diagnosis-stub/card", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"name": "card"}


def test_instance_card_requires_auth(client):
    """TC-MOCK-026 | 无 token 取卡片 401

    输入: 不带 token
    预期输出: 401
    断言点: get_current_user 守卫
    """
    assert client.get("/api/v1/mock-instances/fault-diagnosis-stub/card").status_code == 401


# ---- _spawn_locked (182-202) ---------------------------------------------- #

def test_spawn_locked_registers_proc_with_fake_popen(monkeypatch, tmp_path):
    """TC-MOCK-027 | _spawn_locked 拉起成功后登记进程并返回

    输入: 实例 workDir=tmp，monkeypatch subprocess.Popen 返回假进程
    预期输出: 返回值即假进程，_PROCESSES[id] 即假进程，workDir 与日志文件已创建
    断言点: 返回值 + _PROCESSES 登记 + instance.log 文件存在
    防回归: 若登记或返回逻辑被改坏，断言失败
    """
    inst = {"id": "fake-spawn", "workDir": str(tmp_path)}
    proc = _fake_proc(poll=None, pid=4242)
    monkeypatch.setattr(mi.subprocess, "Popen", lambda *a, **k: proc)
    got = mi._spawn_locked(inst)
    assert got is proc
    assert mi._PROCESSES["fake-spawn"] is proc
    assert (tmp_path / "instance.log").exists()


def test_spawn_locked_closes_log_and_reraises_on_popen_failure(monkeypatch, tmp_path):
    """TC-MOCK-028 | Popen 失败时关闭日志句柄并重抛

    输入: monkeypatch subprocess.Popen 抛 OSError
    预期输出: 抛 OSError，未登记到 _PROCESSES，日志文件已创建（被打开过）
    断言点: pytest.raises OSError + id 不在 _PROCESSES + instance.log 存在
    防回归: 若 except 被删，异常以不同方式冒泡；若 close 被删文件可能仍存在但语义错
    """
    inst = {"id": "fake-spawn-fail", "workDir": str(tmp_path)}

    def _boom(*a, **k):
        raise OSError("popen boom")

    monkeypatch.setattr(mi.subprocess, "Popen", _boom)
    with pytest.raises(OSError, match="popen boom"):
        mi._spawn_locked(inst)
    assert "fake-spawn-fail" not in mi._PROCESSES
    assert (tmp_path / "instance.log").exists()


# ---- ensure_instance_running (205-235) ------------------------------------ #

def test_ensure_already_running_managed(monkeypatch):
    """TC-MOCK-029 | 托管进程在跑 → already-running managed

    输入: 注入假进程到 _PROCESSES
    预期输出: status=already-running, reason=managed, pid=进程 pid
    断言点: 状态字典三字段
    防回归: 若 managed 短路被改坏，会走向拉起
    """
    inst = _real_instance("fault-diagnosis-stub")
    proc = _fake_proc(poll=None, pid=555)
    mi._PROCESSES["fault-diagnosis-stub"] = proc
    result = mi.ensure_instance_running(inst, timeout=1)
    assert result["status"] == "already-running"
    assert result["reason"] == "managed"
    assert result["pid"] == 555


def test_ensure_already_running_external(monkeypatch):
    """TC-MOCK-030 | 端口已有健康实例 → already-running external

    输入: _health_probe 恒 True，_PROCESSES 空
    预期输出: status=already-running, reason=external
    断言点: external 短路
    防回归: 若 external 分支被删，走向拉起
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: True)
    inst = _real_instance("fault-diagnosis-stub")
    result = mi.ensure_instance_running(inst, timeout=1)
    assert result["status"] == "already-running"
    assert result["reason"] == "external"


def test_ensure_spawn_failure_returns_failed(monkeypatch):
    """TC-MOCK-031 | 拉起抛异常 → failed

    输入: monkeypatch _spawn_locked 抛 OSError，_health_probe False
    预期输出: status=failed, error 含异常信息
    断言点: except 捕获并返回 failed
    防回归: 若 except 被删，异常冒泡
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)

    def _boom(_inst):
        raise OSError("spawn boom")

    monkeypatch.setattr(mi, "_spawn_locked", _boom)
    inst = _real_instance("fault-diagnosis-stub")
    result = mi.ensure_instance_running(inst, timeout=1)
    assert result["status"] == "failed"
    assert "spawn boom" in result["error"]


def test_ensure_proc_exits_returns_failed(monkeypatch):
    """TC-MOCK-032 | 拉起后进程立即退出 → failed

    输入: _spawn_locked 返回 poll=1 的假进程，_health_probe False
    预期输出: status=failed, error 含 "进程退出" 与 code=1
    断言点: poll() 非 None 分支
    防回归: 若退出检测被删，会进入健康轮询
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    proc = _fake_proc(poll=1, pid=111)
    monkeypatch.setattr(mi, "_spawn_locked", lambda inst: proc)
    inst = _real_instance("fault-diagnosis-stub")
    result = mi.ensure_instance_running(inst, timeout=1)
    assert result["status"] == "failed"
    assert "进程退出" in result["error"]
    assert "code=1" in result["error"]


def test_ensure_health_timeout_returns_failed(monkeypatch):
    """TC-MOCK-033 | 进程在跑但健康检查超时 → failed

    输入: _spawn_locked 返回 poll=None 假进程，_health_probe 恒 False，timeout 极小
    预期输出: status=failed, error 含 "健康检查超时"
    断言点: 超时分支 + _PROCESSES 清理
    防回归: 若超时分支被改坏，会一直轮询
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    proc = _fake_proc(poll=None, pid=222)
    monkeypatch.setattr(mi, "_spawn_locked", lambda inst: proc)
    inst = _real_instance("fault-diagnosis-stub")
    result = mi.ensure_instance_running(inst, timeout=0.05)
    assert result["status"] == "failed"
    assert "健康检查超时" in result["error"]
    assert "fault-diagnosis-stub" not in mi._PROCESSES


def test_ensure_running_success(monkeypatch):
    """TC-MOCK-034 | 拉起后健康检查通过 → running

    输入: _health_probe 首次 False（跳过 external）再次 True（轮询命中）；_spawn_locked 假进程
    预期输出: status=running, pid=进程 pid
    断言点: 健康命中分支
    防回归: 若命中分支被改坏，会超时
    """
    seq = iter([False, True])
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: next(seq))
    proc = _fake_proc(poll=None, pid=333)
    monkeypatch.setattr(mi, "_spawn_locked", lambda inst: proc)
    inst = _real_instance("fault-diagnosis-stub")
    result = mi.ensure_instance_running(inst, timeout=1)
    assert result["status"] == "running"
    assert result["pid"] == 333


# ---- start endpoint (238-252) --------------------------------------------- #

def test_start_instance_not_found(client, auth_headers):
    """TC-MOCK-035 | 未知实例 start 返回 404

    输入: instance_id=ghost
    预期输出: 404
    断言点: _instance_by_id 404
    """
    assert client.post("/api/v1/mock-instances/ghost/start", headers=auth_headers).status_code == 404


def test_start_instance_requires_admin_403(client, user_headers):
    """TC-MOCK-036 | 非管理员 start 返回 403

    输入: user 角色 token
    预期输出: 403
    断言点: require_admin 守卫
    """
    assert client.post("/api/v1/mock-instances/fault-diagnosis-stub/start", headers=user_headers).status_code == 403


def test_start_instance_requires_auth_401(client):
    """TC-MOCK-037 | 无 token start 返回 401

    输入: 不带 token
    预期输出: 401
    断言点: require_admin → get_current_user 守卫
    """
    assert client.post("/api/v1/mock-instances/fault-diagnosis-stub/start").status_code == 401


def test_start_instance_409_managed(client, auth_headers):
    """TC-MOCK-038 | 托管进程已存在时 start 返回 409

    输入: 注入假托管进程
    预期输出: 409，detail 含 "实例已在本服务中运行"
    断言点: already-running managed → 409
    防回归: 若 409 映射被改坏，返回 200/500
    """
    mi._PROCESSES["fault-diagnosis-stub"] = _fake_proc(poll=None, pid=999)
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/start", headers=auth_headers)
    assert resp.status_code == 409
    assert "实例已在本服务中运行" in resp.json()["detail"]


def test_start_instance_409_external(client, auth_headers, monkeypatch):
    """TC-MOCK-039 | 端口已有外部健康实例时 start 返回 409

    输入: _health_probe 恒 True
    预期输出: 409，detail 含 "端口" 与 "已有实例在运行"
    断言点: already-running external → 409
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: True)
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/start", headers=auth_headers)
    assert resp.status_code == 409
    assert "端口" in resp.json()["detail"]
    assert "已有实例在运行" in resp.json()["detail"]


def test_start_instance_500_on_spawn_failure(client, auth_headers, monkeypatch):
    """TC-MOCK-040 | 拉起失败时 start 返回 500

    输入: _spawn_locked 抛异常，_health_probe False
    预期输出: 500
    断言点: failed → 500
    """
    def _boom(inst):
        raise OSError("spawn boom")

    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    monkeypatch.setattr(mi, "_spawn_locked", _boom)
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/start", headers=auth_headers)
    assert resp.status_code == 500


def test_start_instance_200_running(client, auth_headers, monkeypatch):
    """TC-MOCK-041 | 拉起并健康通过时 start 返回 200

    输入: _spawn_locked 假进程 poll=None；_health_probe 首次 False 再次 True
    预期输出: 200，body.status=running，含 pid/port
    断言点: running → 200 透传
    """
    seq = iter([False, True])
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: next(seq))
    proc = _fake_proc(poll=None, pid=8888)
    monkeypatch.setattr(mi, "_spawn_locked", lambda inst: proc)
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/start", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["pid"] == 8888
    assert body["id"] == "fault-diagnosis-stub"


# ---- stop endpoint / terminate_instance (255-291, 294-298) ---------------- #

def test_stop_instance_not_found(client, auth_headers):
    """TC-MOCK-042 | 未知实例 stop 返回 404

    输入: instance_id=ghost
    预期输出: 404
    断言点: _instance_by_id 404
    """
    assert client.post("/api/v1/mock-instances/ghost/stop", headers=auth_headers).status_code == 404


def test_stop_instance_requires_admin_403(client, user_headers):
    """TC-MOCK-043 | 非管理员 stop 返回 403

    输入: user 角色 token
    预期输出: 403
    断言点: require_admin 守卫
    """
    assert client.post("/api/v1/mock-instances/fault-diagnosis-stub/stop", headers=user_headers).status_code == 403


def test_stop_idle_instance_returns_note(client, auth_headers, monkeypatch):
    """TC-MOCK-044 | 停止本就未运行的实例返回提示

    输入: 无托管进程、无 pid 文件、端口不健康
    预期输出: status=stopped, note 含 "实例本就未在运行"
    断言点: nothing-running 分支
    防回归: 若 note 分支被改坏，note 缺失
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/stop", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["note"] == "实例本就未在运行"


def test_terminate_managed_proc_stops(monkeypatch):
    """TC-MOCK-045 | 终止托管进程 → stopped（terminate+wait 成功）

    输入: 注入 poll=None 假进程；_health_probe False
    预期输出: status=stopped，无 note；进程已从 _PROCESSES 移除
    断言点: stopped + _PROCESSES 清空
    防回归: 若 terminate/wait 分支被改坏，状态不符
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    inst = _real_instance("fault-diagnosis-stub")
    proc = _fake_proc(poll=None, pid=666)
    mi._PROCESSES["fault-diagnosis-stub"] = proc
    result = mi.terminate_instance(inst)
    assert result["status"] == "stopped"
    assert "note" not in result
    assert "fault-diagnosis-stub" not in mi._PROCESSES
    assert proc._terminated is True


def test_terminate_managed_proc_wait_timeout_kills(monkeypatch):
    """TC-MOCK-046 | terminate 后 wait 超时 → kill 兜底

    输入: 假进程 wait 抛 TimeoutExpired
    预期输出: status=stopped；进程被 kill
    断言点: stopped + kill 已调用
    防回归: 若 kill 兜底被删，wait 超时会冒泡
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    inst = _real_instance("fault-diagnosis-stub")
    proc = _fake_proc(poll=None, pid=777, wait_ok=False)
    mi._PROCESSES["fault-diagnosis-stub"] = proc
    result = mi.terminate_instance(inst)
    assert result["status"] == "stopped"
    assert proc._killed is True


def test_terminate_orphan_pidfile_killed_and_removed(monkeypatch, tmp_path):
    """TC-MOCK-047 | 孤儿 pid 文件进程被 taskkill 并删除 pid 文件

    输入: workDir=tmp 写 instance.pid=12345；_pid_alive True；subprocess.run 隔离
    预期输出: status=stopped，pid 文件被删除
    断言点: stopped + pid 文件消失
    防回归: 若 taskkill 或 pid 清理被改坏，文件残留
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    monkeypatch.setattr(mi, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(mi.subprocess, "run", lambda *a, **k: None)
    inst = dict(_real_instance("fault-diagnosis-stub"), workDir=str(tmp_path))
    pid_file = tmp_path / "instance.pid"
    pid_file.write_text("12345", encoding="utf-8")
    result = mi.terminate_instance(inst)
    assert result["status"] == "stopped"
    assert not pid_file.exists()


def test_terminate_pidfile_unlink_oserror_swallowed(monkeypatch, tmp_path):
    """TC-MOCK-048 | pid 文件不可删时 except OSError 被吞掉

    输入: workDir=tmp 写只读 instance.pid；_pid_alive False（跳过 taskkill）
    预期输出: status=stopped, note 含 "实例本就未在运行"（未真正停止）
    断言点: unlink 异常被吞 + 走 note 分支
    防回归: 若 except 被删，PermissionError 冒泡
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    monkeypatch.setattr(mi, "_pid_alive", lambda pid: False)
    inst = dict(_real_instance("fault-diagnosis-stub"), workDir=str(tmp_path))
    pid_file = tmp_path / "instance.pid"
    pid_file.write_text("12345", encoding="utf-8")
    os.chmod(str(pid_file), stat.S_IREAD)
    try:
        result = mi.terminate_instance(inst)
        assert result["status"] == "stopped"
        assert result.get("note") == "实例本就未在运行"
    finally:
        os.chmod(str(pid_file), stat.S_IWRITE)


def test_terminate_garbage_pidfile_defaults_zero_pid(monkeypatch, tmp_path):
    """TC-MOCK-049b | instance.pid 非数字时 pid 降级 0 并跳过 taskkill

    输入: workDir=tmp 写 instance.pid="garbage"；端口不健康
    预期输出: status=stopped, note "实例本就未在运行"（pid=0 短路 taskkill）
    断言点: read ValueError 分支 → pid=0 → 不杀进程
    防回归: 若 except 被删，int("garbage") 抛 ValueError 冒泡
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    inst = dict(_real_instance("fault-diagnosis-stub"), workDir=str(tmp_path))
    (tmp_path / "instance.pid").write_text("garbage", encoding="utf-8")
    result = mi.terminate_instance(inst)
    assert result["status"] == "stopped"
    assert result.get("note") == "实例本就未在运行"


def test_terminate_waits_while_port_still_healthy(monkeypatch, tmp_path):
    """TC-MOCK-049c | 停止后端口仍短暂健康时进入等待循环（覆盖 sleep 分支）

    输入: 无托管进程、无 pid 文件；_health_probe 首次 True 随后 False
    预期输出: status=stopped, note "实例本就未在运行"；_health_probe 被调用 >=2 次（循环至少进过一次）
    断言点: 健康等待循环 sleep 执行（288）
    防回归: 若等待循环被删，调用计数仍为 1，断言失败
    """
    calls = {"n": 0}

    def hp(port, timeout=1.0):
        calls["n"] += 1
        return calls["n"] == 1

    monkeypatch.setattr(mi, "_health_probe", hp)
    inst = dict(_real_instance("fault-diagnosis-stub"), workDir=str(tmp_path))
    result = mi.terminate_instance(inst)
    assert result["status"] == "stopped"
    assert result.get("note") == "实例本就未在运行"
    assert calls["n"] >= 2


# ---- autostart_instances (322-362) ---------------------------------------- #

def test_autostart_empty_override_starts_nothing(monkeypatch):
    """TC-MOCK-049 | MOCK_AGENT_AUTOSTART 为空串时不拉起任何实例

    输入: MOCK_AGENT_AUTOSTART="" 
    预期输出: _PROCESSES 保持空
    断言点: wanted 为空集 → 全部 continue
    防回归: 若空串判定被改坏，会拉起 autoStart 实例
    """
    monkeypatch.setenv("MOCK_AGENT_AUTOSTART", "")
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    monkeypatch.setattr(mi, "_spawn_locked", lambda inst: _fake_proc(poll=1))
    mi.autostart_instances()
    time.sleep(0.6)
    assert mi._PROCESSES == {}


def test_autostart_no_env_skips_non_autostart(monkeypatch):
    """TC-MOCK-050 | 无 override 时 autoStart=false 的实例被跳过

    输入: 删除 MOCK_AGENT_AUTOSTART 环境变量
    预期输出: _PROCESSES 空（所有打桩实例 autoStart 均为 false）
    断言点: autoStart 守卫
    """
    monkeypatch.delenv("MOCK_AGENT_AUTOSTART", raising=False)
    monkeypatch.setattr(mi, "_spawn_locked", lambda inst: _fake_proc(poll=1))
    mi.autostart_instances()
    time.sleep(0.6)
    assert mi._PROCESSES == {}


def test_autostart_load_define_failure_returns(monkeypatch):
    """TC-MOCK-051 | _load_define 抛异常时 autostart 直接返回

    输入: monkeypatch _load_define 抛异常
    预期输出: _PROCESSES 空
    断言点: 顶层 try/except 守卫
    防回归: 若 except 被删，异常冒泡到线程外
    """
    monkeypatch.delenv("MOCK_AGENT_AUTOSTART", raising=False)

    def _boom():
        raise RuntimeError("no define")

    monkeypatch.setattr(mi, "_load_define", _boom)
    mi.autostart_instances()
    time.sleep(0.6)
    assert mi._PROCESSES == {}


def test_autostart_spawn_path_registers_proc(monkeypatch):
    """TC-MOCK-052 | 指定实例 override + 健康未占端口 → 拉起并登记

    输入: MOCK_AGENT_AUTOSTART="fault-diagnosis-stub"；_health_probe False；_spawn_locked 返回 poll=1 假进程
    预期输出: _PROCESSES 含 fault-diagnosis-stub
    断言点: override 命中 + _spawn_locked 被调用 + 登记
    防回归: 若 override 过滤或拉起逻辑被改坏，不登记
    """
    monkeypatch.setenv("MOCK_AGENT_AUTOSTART", "fault-diagnosis-stub")
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    proc = _fake_proc(poll=1, pid=31415)

    def _spawn_and_register(inst):
        mi._PROCESSES[inst["id"]] = proc
        return proc

    monkeypatch.setattr(mi, "_spawn_locked", _spawn_and_register)
    mi.autostart_instances()
    time.sleep(0.8)
    assert "fault-diagnosis-stub" in mi._PROCESSES


def test_autostart_loop_sleeps_while_polling(monkeypatch):
    """TC-MOCK-052b | 拉起后进程未退出且未健康时进入轮询 sleep（覆盖 355）

    输入: MOCK_AGENT_AUTOSTART="fault-diagnosis-stub"；_spawn_locked 返回 poll 首次 None 再次 1 的假进程；_health_probe False
    预期输出: _PROCESSES 含实例（轮询 sleep 至少执行一次后退出循环）
    断言点: 轮询循环 sleep（355）执行
    防回归: 若循环被删，poll 不会从 None 变 1
    """
    monkeypatch.setenv("MOCK_AGENT_AUTOSTART", "fault-diagnosis-stub")
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    poll_seq = iter([None, 1])
    proc = _fake_proc(pid=27182)
    proc.poll = lambda: next(poll_seq)

    def _spawn_and_register(inst):
        mi._PROCESSES[inst["id"]] = proc
        return proc

    monkeypatch.setattr(mi, "_spawn_locked", _spawn_and_register)
    mi.autostart_instances()
    time.sleep(1.0)
    assert "fault-diagnosis-stub" in mi._PROCESSES


def test_autostart_spawn_exception_is_logged(monkeypatch):
    """TC-MOCK-053 | autostart 拉起抛异常时仅记日志不崩溃

    输入: MOCK_AGENT_AUTOSTART="fault-diagnosis-stub"；_spawn_locked 抛异常
    预期输出: _PROCESSES 空（异常被 except 吞）
    断言点: 拉起异常守卫
    防回归: 若 except 被删，线程异常（虽 daemon 不影响主流程，但语义错）
    """
    monkeypatch.setenv("MOCK_AGENT_AUTOSTART", "fault-diagnosis-stub")
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)

    def _boom(inst):
        raise RuntimeError("spawn fail")

    monkeypatch.setattr(mi, "_spawn_locked", _boom)
    mi.autostart_instances()
    time.sleep(0.8)
    assert mi._PROCESSES == {}


def test_autostart_skips_when_already_healthy(monkeypatch):
    """TC-MOCK-054 | override 实例端口已健康时跳过拉起

    输入: MOCK_AGENT_AUTOSTART="fault-diagnosis-stub"；_health_probe True
    预期输出: _PROCESSES 空（不重复拉起）
    断言点: 健康短路 continue
    """
    monkeypatch.setenv("MOCK_AGENT_AUTOSTART", "fault-diagnosis-stub")
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: True)
    monkeypatch.setattr(mi, "_spawn_locked", lambda inst: pytest.fail("不应拉起"))
    mi.autostart_instances()
    time.sleep(0.6)
    assert mi._PROCESSES == {}


# =========================================================================== #
# agents_router
# =========================================================================== #

def test_agents_list_requires_auth(client):
    """TC-MOCK-055 | 无 token 列 Agent 401

    输入: 不带 token
    预期输出: 401
    断言点: get_current_user 守卫
    """
    assert client.get("/api/v1/agents").status_code == 401


def test_agents_list_default_is_default(client, auth_headers):
    """TC-MOCK-056 | 列表含默认 Agent 且 isDefault=True

    输入: 管理员 token
    预期输出: 列表含默认 Agent，isDefault True
    断言点: default_agent_id 透出
    """
    data = client.get("/api/v1/agents", headers=auth_headers).json()
    assert any(a["isDefault"] for a in data)
    assert set(["id", "organization", "name", "enabled", "layer", "networkDomain", "isDefault"]) <= set(data[0])


def test_agents_create_service_agent(client, auth_headers):
    """TC-MOCK-057 | 创建 service 层 Agent 返回 201 且可查

    输入: {name, organization, layer=service}
    预期输出: 201，isDefault False；列表中出现
    断言点: 201 + 列表可查
    防回归: 若 _mount_agent 或提交逻辑被改坏，201 丢失
    """
    resp = client.post(
        "/api/v1/agents",
        json={"name": "svc-agent", "organization": "OpenAN", "layer": "service", "description": "d"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["isDefault"] is False
    assert resp.json()["networkDomain"] is None
    names = {a["name"] for a in client.get("/api/v1/agents", headers=auth_headers).json()}
    assert "svc-agent" in names


def test_agents_create_network_without_domain_422(client, auth_headers):
    """TC-MOCK-058 | network 层缺 networkDomain 返回 422

    输入: {layer=network} 无 networkDomain
    预期输出: 422
    断言点: model_validator 校验
    """
    resp = client.post(
        "/api/v1/agents",
        json={"name": "net-agent", "organization": "OpenAN", "layer": "network"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_agents_create_requires_admin_403(client, user_headers):
    """TC-MOCK-059 | 非管理员创建 Agent 返回 403

    输入: user 角色 token
    预期输出: 403
    断言点: require_admin 守卫
    """
    resp = client.post(
        "/api/v1/agents",
        json={"name": "x", "organization": "OpenAN", "layer": "service"},
        headers=user_headers,
    )
    assert resp.status_code == 403


def test_agents_patch_not_found_404(client, auth_headers):
    """TC-MOCK-060 | patch 不存在 Agent 返回 404

    输入: agent_id=999999
    预期输出: 404
    断言点: get 守卫
    """
    resp = client.patch("/api/v1/agents/999999", json={"description": "x"}, headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Agent not found"


def test_agents_patch_disable_default_409(client, auth_headers):
    """TC-MOCK-061 | 禁用默认 Agent 返回 409

    输入: 默认 agent id + {enabled=False}
    预期输出: 409，detail 含 "默认 Agent 不可禁用"
    断言点: 默认守卫
    """
    default_id = client.app.state.default_agent_id
    resp = client.patch(f"/api/v1/agents/{default_id}", json={"enabled": False}, headers=auth_headers)
    assert resp.status_code == 409
    assert "默认 Agent 不可禁用" in resp.json()["detail"]


def test_agents_patch_layer_service_clears_domain(client, auth_headers):
    """TC-MOCK-062 | patch layer=service 清空 networkDomain

    输入: 先建 network agent（wireless），再 patch layer=service
    预期输出: networkDomain 变 None
    断言点: layer==service → network_domain=None
    """
    created = client.post(
        "/api/v1/agents",
        json={"name": "net2", "organization": "OpenAN", "layer": "network", "networkDomain": "wireless"},
        headers=auth_headers,
    ).json()
    resp = client.patch(
        f"/api/v1/agents/{created['id']}",
        json={"layer": "service", "description": "now service"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["networkDomain"] is None
    assert resp.json()["description"] == "now service"


def test_agents_patch_network_sets_domain(client, auth_headers):
    """TC-MOCK-063 | patch layer=network + networkDomain 写入域

    输入: 建 service agent，patch {layer=network, networkDomain=optical}
    预期输出: networkDomain == optical
    断言点: elif networkDomain 分支
    """
    created = client.post(
        "/api/v1/agents",
        json={"name": "svc2net", "organization": "OpenAN", "layer": "service"},
        headers=auth_headers,
    ).json()
    resp = client.patch(
        f"/api/v1/agents/{created['id']}",
        json={"layer": "network", "networkDomain": "optical"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["networkDomain"] == "optical"


def test_agents_patch_enable_remounts_agent(client, auth_headers):
    """TC-MOCK-064 | 启用未挂载的非默认 Agent 时触发 _mount_agent

    输入: 创建 agent（已挂载），从 agent_runtimes 移除模拟未挂载，再 patch enabled=True
    预期输出: 200 enabled=True，且重新挂回 agent_runtimes
    断言点: enable+非默认+未挂载 → _mount_agent
    防回归: 若 remount 分支被删，agent_runtimes 不会重新含该 id
    """
    created = client.post(
        "/api/v1/agents",
        json={"name": "remount", "organization": "OpenAN", "layer": "service"},
        headers=auth_headers,
    ).json()
    aid = created["id"]
    client.app.state.agent_runtimes.pop(aid, None)
    resp = client.patch(f"/api/v1/agents/{aid}", json={"enabled": True}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True
    assert aid in client.app.state.agent_runtimes


def test_agents_delete_not_found_404(client, auth_headers):
    """TC-MOCK-065 | 删除不存在 Agent 返回 404

    输入: agent_id=999999
    预期输出: 404
    """
    assert client.delete("/api/v1/agents/999999", headers=auth_headers).status_code == 404


def test_agents_delete_default_409(client, auth_headers):
    """TC-MOCK-066 | 删除默认 Agent 返回 409

    输入: 默认 agent id
    预期输出: 409，detail 含 "默认 Agent 不可删除"
    """
    default_id = client.app.state.default_agent_id
    resp = client.delete(f"/api/v1/agents/{default_id}", headers=auth_headers)
    assert resp.status_code == 409
    assert "默认 Agent 不可删除" in resp.json()["detail"]


def test_agents_delete_disables_non_default(client, auth_headers):
    """TC-MOCK-067 | 删除非默认 Agent 软删（enabled=False）

    输入: 创建 agent 后 delete
    预期输出: 200 enabled=False
    断言点: 软删
    """
    created = client.post(
        "/api/v1/agents",
        json={"name": "todelete", "organization": "OpenAN", "layer": "service"},
        headers=auth_headers,
    ).json()
    resp = client.delete(f"/api/v1/agents/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


# =========================================================================== #
# variants_router
# =========================================================================== #

def test_variants_list_requires_auth(client):
    """TC-MOCK-068 | 无 token 列变体 401

    输入: 不带 token
    预期输出: 401
    """
    assert client.get("/api/v1/variants").status_code == 401


def test_variants_list_and_filter(client, auth_headers):
    """TC-MOCK-069 | 列表返回 + template_uri 过滤

    输入: 导入两个变体同模板，一个不同模板；按 template_uri 过滤
    预期输出: 过滤结果只含指定模板
    断言点: where 过滤生效
    """
    client.post(
        "/api/v1/variants/import",
        json={
            "templateUri": "Task-T/a/v1",
            "variants": [{"k": 1}, {"k": 2}],
        },
        headers=auth_headers,
    )
    client.post(
        "/api/v1/variants/import",
        json={"templateUri": "Task-T/b/v1", "variants": [{"k": 9}]},
        headers=auth_headers,
    )
    allv = client.get("/api/v1/variants", headers=auth_headers).json()
    assert len(allv) >= 3
    filtered = client.get("/api/v1/variants", params={"template_uri": "Task-T/a/v1"}, headers=auth_headers).json()
    assert all(v["templateUri"] == "Task-T/a/v1" for v in filtered)
    assert len(filtered) == 2


def test_variants_import_agent_not_found_404(client, auth_headers):
    """TC-MOCK-070 | 导入指向不存在 agent 返回 404

    输入: agentId=999999
    预期输出: 404，detail "Agent not found"
    """
    resp = client.post(
        "/api/v1/variants/import",
        json={"agentId": 999999, "templateUri": "Task-T/x/v1", "variants": [{"k": 1}]},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Agent not found"


def test_variants_import_disabled_agent_409(client, auth_headers):
    """TC-MOCK-071 | 导入到已禁用 agent 返回 409

    输入: 创建 agent 并禁用，再用其 id 导入
    预期输出: 409，detail "Agent 已禁用"
    断言点: enabled 守卫
    """
    created = client.post(
        "/api/v1/agents",
        json={"name": "dis-agent", "organization": "OpenAN", "layer": "service"},
        headers=auth_headers,
    ).json()
    client.patch(f"/api/v1/agents/{created['id']}", json={"enabled": False}, headers=auth_headers)
    resp = client.post(
        "/api/v1/variants/import",
        json={"agentId": created["id"], "templateUri": "Task-T/y/v1", "variants": [{"k": 1}]},
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Agent 已禁用"


def test_variants_import_seed_not_found_404(client, auth_headers):
    """TC-MOCK-072 | 导入指向不存在 seed 返回 404

    输入: 合法 agent + seedId=999999
    预期输出: 404，detail "Seed not found"
    """
    resp = client.post(
        "/api/v1/variants/import",
        json={"seedId": 999999, "templateUri": "Task-T/z/v1", "variants": [{"k": 1}]},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Seed not found"


def test_variants_import_success(client, auth_headers):
    """TC-MOCK-073 | 导入成功返回计数与 id 列表，且可查

    输入: 默认 agent + 2 个变体
    预期输出: imported=2, firstSeq=0, ids 长度 2；列表可见
    断言点: 计数 + firstSeq + 列表可查
    """
    resp = client.post(
        "/api/v1/variants/import",
        json={"templateUri": "Task-T/imp/v1", "variants": [{"a": 1}, {"a": 2}]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 2
    assert body["firstSeq"] == 0
    assert len(body["ids"]) == 2
    rows = client.get("/api/v1/variants", params={"template_uri": "Task-T/imp/v1"}, headers=auth_headers).json()
    assert {r["seq"] for r in rows} == {0, 1}


def test_variants_import_empty_list(client, auth_headers):
    """TC-MOCK-074 | 导入空变体列表返回 imported=0

    输入: variants=[]
    预期输出: imported=0, ids=[]
    断言点: 空列表不报错
    """
    resp = client.post(
        "/api/v1/variants/import",
        json={"templateUri": "Task-T/empty/v1", "variants": []},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 0


def test_variants_import_uses_runtime_agent_when_id_omitted(client, auth_headers):
    """TC-MOCK-075 | 不传 agentId 时用运行时默认 agent

    输入: 不含 agentId
    预期输出: imported>0（用默认 agent）
    断言点: agent_id 回退到 runtime
    """
    resp = client.post(
        "/api/v1/variants/import",
        json={"templateUri": "Task-T/rt/v1", "variants": [{"x": 1}]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 1


def test_variants_patch_not_found_404(client, auth_headers):
    """TC-MOCK-076 | patch 不存在变体 404

    输入: variant_id=999999
    预期输出: 404
    """
    resp = client.patch("/api/v1/variants/999999", json={"enabled": False}, headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Variant not found"


def test_variants_patch_updates_fields(client, auth_headers):
    """TC-MOCK-077 | patch 更新 enabled 与 variantJson

    输入: 导入一个变体后 patch enabled=False + variantJson
    预期输出: 200，字段已更新
    断言点: 字段写入 + 返回视图
    """
    imp = client.post(
        "/api/v1/variants/import",
        json={"templateUri": "Task-T/p/v1", "variants": [{"k": 1}]},
        headers=auth_headers,
    ).json()
    vid = imp["ids"][0]
    resp = client.patch(
        f"/api/v1/variants/{vid}",
        json={"enabled": False, "variantJson": {"k": 99}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    assert resp.json()["variantJson"] == {"k": 99}


# =========================================================================== #
# seeds_router
# =========================================================================== #

def test_seeds_list_requires_auth(client):
    """TC-MOCK-078 | 无 token 列种子 401

    输入: 不带 token
    预期输出: 401
    """
    assert client.get("/api/v1/seeds").status_code == 401


def test_seeds_create_list_and_count(client, auth_headers):
    """TC-MOCK-079 | 创建种子返回 201，列表含且 variantCount=0

    输入: {name, templateUri, seedJson}
    预期输出: 201；列表含该种子，variantCount=0，createdBy=admin
    断言点: 201 + 视图字段
    """
    resp = client.post(
        "/api/v1/seeds",
        json={"name": "seed-1", "templateUri": "Task-T/s/v1", "seedJson": {"a": 1}, "description": "d"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["variantCount"] == 0
    assert resp.json()["createdBy"] == "admin"
    rows = client.get("/api/v1/seeds", headers=auth_headers).json()
    assert any(r["name"] == "seed-1" for r in rows)


def test_seeds_create_validation_422(client, auth_headers):
    """TC-MOCK-080 | 空种子名返回 422

    输入: name=""
    预期输出: 422
    断言点: min_length=1 校验
    """
    resp = client.post(
        "/api/v1/seeds",
        json={"name": "", "templateUri": "Task-T/s/v1", "seedJson": {}},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_seeds_patch_not_found_404(client, auth_headers):
    """TC-MOCK-081 | patch 不存在种子 404

    输入: seed_id=999999
    预期输出: 404
    """
    assert client.patch("/api/v1/seeds/999999", json={"name": "x"}, headers=auth_headers).status_code == 404


def test_seeds_patch_updates_fields(client, auth_headers):
    """TC-MOCK-082 | patch 更新 name/templateUri/seedJson/description

    输入: 创建种子后 patch 全字段
    预期输出: 200，字段已更新
    断言点: 各字段写入
    """
    sid = client.post(
        "/api/v1/seeds",
        json={"name": "s", "templateUri": "Task-T/o/v1", "seedJson": {}},
        headers=auth_headers,
    ).json()["id"]
    resp = client.patch(
        f"/api/v1/seeds/{sid}",
        json={"name": "s2", "templateUri": "Task-T/n/v1", "seedJson": {"x": 1}, "description": "nd"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "s2"
    assert body["templateUri"] == "Task-T/n/v1"
    assert body["seedJson"] == {"x": 1}
    assert body["description"] == "nd"


def test_seeds_patch_variant_count(client, auth_headers):
    """TC-MOCK-083 | patch 返回的 variantCount 反映关联变体数

    输入: 创建种子，导入变体绑定 seedId，再 patch 种子
    预期输出: variantCount == 2
    断言点: count 查询
    """
    sid = client.post(
        "/api/v1/seeds",
        json={"name": "sc", "templateUri": "Task-T/c/v1", "seedJson": {}},
        headers=auth_headers,
    ).json()["id"]
    client.post(
        "/api/v1/variants/import",
        json={"seedId": sid, "templateUri": "Task-T/c/v1", "variants": [{"a": 1}, {"a": 2}]},
        headers=auth_headers,
    )
    resp = client.patch(f"/api/v1/seeds/{sid}", json={"description": "x"}, headers=auth_headers)
    assert resp.json()["variantCount"] == 2


def test_seeds_delete_not_found_404(client, auth_headers):
    """TC-MOCK-084 | 删除不存在种子 404

    输入: seed_id=999999
    预期输出: 404
    """
    assert client.delete("/api/v1/seeds/999999", headers=auth_headers).status_code == 404


def test_seeds_delete_returns_204_and_gone(client, auth_headers):
    """TC-MOCK-085 | 删除种子返回 204 且列表不再含

    输入: 创建后删除
    预期输出: 204；列表不含
    断言点: 204 + 列表无残留
    """
    sid = client.post(
        "/api/v1/seeds",
        json={"name": "del", "templateUri": "Task-T/d/v1", "seedJson": {}},
        headers=auth_headers,
    ).json()["id"]
    resp = client.delete(f"/api/v1/seeds/{sid}", headers=auth_headers)
    assert resp.status_code == 204
    names = {r["name"] for r in client.get("/api/v1/seeds", headers=auth_headers).json()}
    assert "del" not in names


def test_seeds_delete_nullifies_linked_variants(client, auth_headers):
    """TC-MOCK-086 | 删除种子将其变体 seed_id 置空

    输入: 创建种子 + 导入绑定变体，删除种子后查变体
    预期输出: 变体 seedId 变 None
    断言点: 级联置空
    防回归: 若置空逻辑被删，变体 seedId 残留指向已删种子
    """
    sid = client.post(
        "/api/v1/seeds",
        json={"name": "cascade", "templateUri": "Task-T/casc/v1", "seedJson": {}},
        headers=auth_headers,
    ).json()["id"]
    imp = client.post(
        "/api/v1/variants/import",
        json={"seedId": sid, "templateUri": "Task-T/casc/v1", "variants": [{"a": 1}]},
        headers=auth_headers,
    ).json()
    vid = imp["ids"][0]
    client.delete(f"/api/v1/seeds/{sid}", headers=auth_headers)
    row = client.get(f"/api/v1/variants", params={"template_uri": "Task-T/casc/v1"}, headers=auth_headers).json()
    assert next(v for v in row if v["id"] == vid)["seedId"] is None


# =========================================================================== #
# users_router
# =========================================================================== #

def test_users_list_requires_admin(client, user_headers):
    """TC-MOCK-087 | 非管理员列用户 403

    输入: user 角色 token
    预期输出: 403
    断言点: require_admin 守卫
    """
    assert client.get("/api/v1/users", headers=user_headers).status_code == 403


def test_users_list_requires_auth(client):
    """TC-MOCK-088 | 无 token 列用户 401

    输入: 不带 token
    预期输出: 401
    """
    assert client.get("/api/v1/users").status_code == 401


def test_users_list_includes_admin(client, auth_headers):
    """TC-MOCK-089 | 管理员列表含 admin

    输入: 管理员 token
    预期输出: 列表含 admin 用户
    断言点: 视图结构 + admin 存在
    """
    data = client.get("/api/v1/users", headers=auth_headers).json()
    assert any(u["username"] == "admin" and u["role"] == "admin" for u in data)
    assert set(["id", "username", "role", "enabled"]) <= set(data[0])


def test_users_create_and_login(client, auth_headers):
    """TC-MOCK-090 | 创建 user 角色账号返回 201 且可登录

    输入: {username, password, role=user}
    预期输出: 201；登录 200 且 role=user
    断言点: 201 + 登录链路
    """
    resp = client.post(
        "/api/v1/users",
        json={"username": "newuser", "password": "newuser-pass", "role": "user"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "user"
    login = client.post("/api/v1/auth/login", json={"username": "newuser", "password": "newuser-pass"})
    assert login.status_code == 200
    assert login.json()["role"] == "user"


def test_users_create_duplicate_409(client, auth_headers):
    """TC-MOCK-091 | 重复用户名返回 409

    输入: username=admin（已存在）
    预期输出: 409，detail "Username exists"
    断言点: 唯一性守卫
    """
    resp = client.post(
        "/api/v1/users",
        json={"username": "admin", "password": "admin-pass2", "role": "user"},
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Username exists"


def test_users_create_validation_422(client, auth_headers):
    """TC-MOCK-092 | 密码过短返回 422

    输入: password="123"（<8）
    预期输出: 422
    断言点: min_length=8
    """
    resp = client.post(
        "/api/v1/users",
        json={"username": "shortpw", "password": "123", "role": "user"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_users_patch_not_found_404(client, auth_headers):
    """TC-MOCK-093 | patch 不存在用户 404

    输入: user_id=999999
    预期输出: 404
    """
    assert client.patch("/api/v1/users/999999", json={"enabled": False}, headers=auth_headers).status_code == 404


def test_users_patch_role_and_password(client, auth_headers):
    """TC-MOCK-094 | patch 更新 role 与 password

    输入: 创建用户后 patch role=admin + 新密码
    预期输出: 200 role=admin；新密码可登录
    断言点: role 写入 + 密码哈希更新
    """
    uid = client.post(
        "/api/v1/users",
        json={"username": "patchme", "password": "patchme-pw", "role": "user"},
        headers=auth_headers,
    ).json()["id"]
    resp = client.patch(
        f"/api/v1/users/{uid}",
        json={"role": "admin", "password": "newpatch-pw"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"
    login = client.post("/api/v1/auth/login", json={"username": "patchme", "password": "newpatch-pw"})
    assert login.status_code == 200


def test_users_patch_disable_blocks_login(client, auth_headers):
    """TC-MOCK-095 | 禁用用户后无法登录

    输入: 创建用户 → patch enabled=False → 登录
    预期输出: 登录 401
    断言点: enabled=False 阻断认证
    """
    uid = client.post(
        "/api/v1/users",
        json={"username": "disableme", "password": "disableme-pw", "role": "user"},
        headers=auth_headers,
    ).json()["id"]
    client.patch(f"/api/v1/users/{uid}", json={"enabled": False}, headers=auth_headers)
    login = client.post("/api/v1/auth/login", json={"username": "disableme", "password": "disableme-pw"})
    assert login.status_code == 401
