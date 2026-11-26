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

"""mock_instances_router 覆盖测试（TC-DMOCK-001..057）。

真实临时 DB + 真实登录态；仅隔离网络/进程副作用（_health_probe、subprocess.Popen、
httpx.get、_pid_alive）。define 文件通过 OPENAN_DEBUG_MOCK_DEFINE 指向临时文件，
autostart 通过 OPENAN_DEBUG_AUTOSTART 控制；真实 define 所有实例 autoStart=false，
故 client fixture 启动期 lifespan autostart 后台线程不会拉起真实进程。
"""

import json
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
from fastapi import HTTPException

from openan_debug.routers import mock_instances_router as mi
from tests.conftest import auth_header


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
def user_token(client, admin_token):
    """创建 user 角色账号并登录（用于 403 越权断言）。"""
    resp = client.post(
        "/api/v1/users",
        json={"username": "tester", "password": "tester-pass", "role": "user"},
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 201, resp.text
    login = client.post("/api/v1/auth/login", json={"username": "tester", "password": "tester-pass"})
    assert login.status_code == 200
    return login.json()["token"]


@pytest.fixture()
def define_env(tmp_path, monkeypatch):
    """写入受控临时 define 文件并把 OPENAN_DEBUG_MOCK_DEFINE 指向它。"""
    w1 = tmp_path / "w1"
    w2 = tmp_path / "w2"
    w3 = tmp_path / "w3"
    w1.mkdir()
    w2.mkdir()
    w3.mkdir()
    define = {
        "defaults": {
            "llm": {
                "enabled": False,
                "provider": "openai",
                "baseUrl": "http://d/v1",
                "model": "dm",
                "apiKeyEnv": "DK",
            }
        },
        "instances": [
            {
                "id": "fault-diagnosis-stub",
                "name": "故障诊断打桩 Agent",
                "organization": "OpenAN",
                "agentName": "OpenAN Debug Mock Agent",
                "description": "d1",
                "layer": "service",
                "port": 9005,
                "workDir": str(w1),
                "autoStart": False,
                "llm": {"enabled": False},
                "stubVariants": [{}, {}],
                "workflow": {"enabled": False},
            },
            {
                "id": "recovery-stub",
                "name": "业务抢通打桩 Agent",
                "organization": "OpenAN",
                "description": "d2",
                "layer": "network",
                "networkDomain": "transmission",
                "port": 9006,
                "workDir": str(w2),
                "autoStart": False,
                "llm": {
                    "enabled": True,
                    "provider": "openai",
                    "baseUrl": "http://x/v1",
                    "model": "m",
                    "apiKeyEnv": "K",
                },
                "stubVariants": [{}],
                "workflow": {"enabled": True, "workflowId": "wf-1"},
            },
            {"id": "minimal-stub", "port": 9007, "workDir": str(w3)},
        ],
    }
    define_path = tmp_path / "mock_agent_define.json"
    define_path.write_text(json.dumps(define, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("OPENAN_DEBUG_MOCK_DEFINE", str(define_path))
    return define


def _fake_proc(*, poll=None, pid=12345, wait_ok=True):
    """构造可控制的假子进程对象（不真正拉起进程）。"""

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


def _start_health_server(status=200):
    """启动一个临时本地 HTTP 服务（/health）。"""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *args):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


# =========================================================================== #
# resolve_define_path / _load_define / _instance_by_id
# =========================================================================== #

def test_resolve_define_path_override_returns_temp(define_env):
    """TC-DMOCK-001 | OPENAN_DEBUG_MOCK_DEFINE 指向的临时文件被优先返回

    输入: define_env 设置 OPENAN_DEBUG_MOCK_DEFINE 指向临时 define
    预期输出: resolve_define_path 返回该临时文件路径
    断言点: 返回路径等于环境变量指向的路径（覆盖 override 候选分支）
    防回归: 若 override 候选分支被删除，会返回 cwd/server_dir 下的其它文件
    """
    returned = mi.resolve_define_path()
    assert returned == Path(os.environ["OPENAN_DEBUG_MOCK_DEFINE"])


def test_resolve_define_path_404_when_no_candidate(monkeypatch):
    """TC-DMOCK-002 | 无任何候选 define 文件时抛 404

    输入: OPENAN_DEBUG_MOCK_DEFINE 指向不存在路径，且所有候选 exists() 均被桩为 False
    预期输出: 抛 HTTPException 404，detail 含 "未找到"
    断言点: 异常类型 + 状态码 + 消息关键字
    防回归: 若 404 抛出被删除，本用例失败
    """
    monkeypatch.setenv("OPENAN_DEBUG_MOCK_DEFINE", str(Path("/nonexistent/xx/define.json")))
    monkeypatch.setattr(Path, "exists", lambda self: False)
    with pytest.raises(HTTPException, match="未找到") as exc:
        mi.resolve_define_path()
    assert exc.value.status_code == 404


def test_load_define_invalid_json_500(tmp_path):
    """TC-DMOCK-003 | define 文件 JSON 非法时 _load_define 抛 500

    输入: 临时文件内容为非法 JSON
    预期输出: 抛 HTTPException 500，detail 含 "解析失败"
    断言点: 异常类型 + 状态码 + 消息关键字
    防回归: 若 except 被删除，JSONDecodeError 以 500 之外方式冒泡
    """
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(HTTPException, match="解析失败") as exc:
        mi._load_define(bad)
    assert exc.value.status_code == 500


def test_instance_by_id_not_found_404():
    """TC-DMOCK-004 | 未知实例 id 抛 404

    输入: define 中仅有 id=a，查询 ghost
    预期输出: 抛 HTTPException 404，detail 含 "ghost" 与 "未定义"
    断言点: 异常类型 + 状态码 + 消息关键字
    防回归: 若 404 守卫被删除，返回 None 而非抛异常
    """
    with pytest.raises(HTTPException, match="未定义") as exc:
        mi._instance_by_id({"instances": [{"id": "a"}]}, "ghost")
    assert exc.value.status_code == 404
    assert "ghost" in exc.value.detail


def test_instance_by_id_returns_instance():
    """TC-DMOCK-005 | 命中实例 id 时返回该实例字典

    输入: define 中含 id=a 的实例
    预期输出: 返回该实例字典（同一对象）
    断言点: 返回值即输入实例对象
    防回归: 若查询逻辑被改错，返回 None 或其它对象
    """
    inst = {"id": "a", "port": 9}
    assert mi._instance_by_id({"instances": [inst]}, "a") is inst


# =========================================================================== #
# _health_probe (85-89)
# =========================================================================== #

def test_health_probe_real_server_200_true():
    """TC-DMOCK-006 | 命中真实 200 服务时 _health_probe 返回 True

    输入: 本地 HTTP 服务恒返回 200
    预期输出: True
    断言点: status_code==200 成功分支
    防回归: 若 httpx.get 调用或状态码比较被改坏，本用例失败
    """
    srv, port = _start_health_server(200)
    try:
        assert mi._health_probe(port) is True
    finally:
        srv.shutdown()
        srv.server_close()


def test_health_probe_non_200_false():
    """TC-DMOCK-007 | 收到非 200 时 _health_probe 返回 False

    输入: 本地 HTTP 服务恒返回 404
    预期输出: False
    断言点: status_code != 200 → False
    防回归: 若状态码判定被反转，本用例失败
    """
    srv, port = _start_health_server(404)
    try:
        assert mi._health_probe(port) is False
    finally:
        srv.shutdown()
        srv.server_close()


def test_health_probe_exception_false(monkeypatch):
    """TC-DMOCK-008 | httpx.get 抛异常时 _health_probe 返回 False

    输入: monkeypatch httpx.get 抛 OSError
    预期输出: False
    断言点: except Exception → False
    防回归: 若 except 被删除，异常冒泡导致用例报错
    """
    def _boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(mi.httpx, "get", _boom)
    assert mi._health_probe(9) is False


# =========================================================================== #
# _pid_alive (93-107)
# =========================================================================== #

def test_pid_alive_non_positive_is_false():
    """TC-DMOCK-009 | 非正 pid 直接判否

    输入: pid=0 与 pid=-1
    预期输出: False
    断言点: pid<=0 提前返回 False
    防回归: 若提前守卫被删，tasklist 会被空 pid 调用
    """
    assert mi._pid_alive(0) is False
    assert mi._pid_alive(-1) is False


@pytest.mark.skipif(os.name != "nt", reason="tasklist 分支仅 Windows 可达")
def test_pid_alive_self_true_unknown_false_windows():
    """TC-DMOCK-010 | Windows 下 tasklist 能找到当前进程、找不到假 pid

    输入: 当前测试进程 pid 与一个不存在的大 pid
    预期输出: 自身 True、陌生 False
    断言点: tasklist 输出含/不含 pid 字符串
    防回归: 若 tasklist 解析逻辑改坏，两条断言之一失败
    """
    assert mi._pid_alive(os.getpid()) is True
    assert mi._pid_alive(999999987) is False


@pytest.mark.skipif(os.name != "nt", reason="tasklist 分支仅 Windows 可达")
def test_pid_alive_tasklist_failure_returns_false(monkeypatch):
    """TC-DMOCK-011 | tasklist 自身失败时降级为 False

    输入: monkeypatch subprocess.run 抛 OSError
    预期输出: False
    断言点: except 分支返回 False
    防回归: 若 except 被删，异常冒泡
    """
    def _boom(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(mi.subprocess, "run", _boom)
    assert mi._pid_alive(os.getpid()) is False


# 注: _pid_alive 中 os.kill(pid, 0) / os.kill(pid, 9) 的 posix 分支（103-107、263-264）
# 在 win32 上因 os.name == "nt" 永远不可达，列为平台不可达行。


# =========================================================================== #
# _managed_running (111-112)
# =========================================================================== #

def test_managed_running_states():
    """TC-DMOCK-012 | _managed_running 区分未登记/在跑/已退出

    输入: 未登记 id、poll=None 的进程、poll=1 的进程
    预期输出: False / True / False
    断言点: proc is None 与 proc.poll() 双重判定
    防回归: 若 poll 判定被改坏，已退出进程会被误判在跑
    """
    assert mi._managed_running("none") is False
    mi._PROCESSES["alive"] = _fake_proc(poll=None, pid=1)
    assert mi._managed_running("alive") is True
    mi._PROCESSES["dead"] = _fake_proc(poll=1, pid=2)
    assert mi._managed_running("dead") is False


# =========================================================================== #
# _agent_id_for (116-125)
# =========================================================================== #

def test_agent_id_for_returns_id_when_matched(client):
    """TC-DMOCK-013 | 命中 DB Agent 行时返回其 id

    输入: 默认 Agent 的 organization+name（OpenAN / OpenAN Debug Mock Agent）
    预期输出: 默认 agent id
    断言点: 返回值等于 app.state.default_agent_id
    防回归: 若查询条件被改错，返回 None
    """
    request = types.SimpleNamespace(app=client.app)
    assert mi._agent_id_for(request, "OpenAN", "OpenAN Debug Mock Agent") == client.app.state.default_agent_id


def test_agent_id_for_returns_none_when_unmatched(client):
    """TC-DMOCK-014 | 未命中时返回 None

    输入: 不存在的 organization/name
    预期输出: None
    断言点: agent is None → return None
    防回归: 若未命中时误返回非 None，用例失败
    """
    request = types.SimpleNamespace(app=client.app)
    assert mi._agent_id_for(request, "Nope", "ghost") is None


def test_agent_id_for_swallows_db_error_returns_none():
    """TC-DMOCK-015 | DB 会话异常时返回 None（兜底分支）

    输入: app.state.engine 为非法对象，Session 构造抛异常
    预期输出: None
    断言点: except Exception → return None
    防回归: 若 except 被删，异常冒泡导致用例报错
    """
    request = types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace(engine=object()))
    )
    assert mi._agent_id_for(request, "x", "y") is None


# =========================================================================== #
# _instance_view (129-143, 166)
# =========================================================================== #

_VIEW_DEFINE = {
    "defaults": {"llm": {"enabled": False, "provider": "openai", "baseUrl": "http://d/v1", "model": "dm", "apiKeyEnv": "DK"}},
    "instances": [],
}


def test_instance_view_managed_proc_running(client, monkeypatch):
    """TC-DMOCK-016 | 托管进程在跑时 running=True 且 pid 取自进程

    输入: 注入 poll=None 假进程到 _PROCESSES；_health_probe 桩 False
    预期输出: running=True, pid=进程 pid, agentId=default
    断言点: running True + pid 等于注入进程 pid + managed 分支
    防回归: 若 managed 分支被改坏，running 变 False
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    inst = {"id": "x", "workDir": "ignored", "port": 9005, "organization": "OpenAN", "agentName": "OpenAN Debug Mock Agent"}
    proc = _fake_proc(poll=None, pid=777)
    mi._PROCESSES["x"] = proc
    view = mi._instance_view(types.SimpleNamespace(app=client.app), _VIEW_DEFINE, inst)
    assert view["running"] is True
    assert view["pid"] == 777
    assert view["agentId"] == client.app.state.default_agent_id


def test_instance_view_external_pid_alive_and_healthy(client, monkeypatch, tmp_path):
    """TC-DMOCK-017 | 非托管但 pid 文件存在且存活且健康 → running=True

    输入: workDir=tmp 写 instance.pid=当前进程 pid；_pid_alive/_health_probe 均 True
    预期输出: pid=当前 pid, running=True
    断言点: pid 文件读取成功 + running 合成 True
    防回归: 若 pid 文件读取或 running 合成逻辑被改坏，失败
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: True)
    monkeypatch.setattr(mi, "_pid_alive", lambda pid: True)
    inst = {"id": "x", "workDir": str(tmp_path), "port": 9005}
    (tmp_path / "instance.pid").write_text(str(os.getpid()), encoding="utf-8")
    view = mi._instance_view(types.SimpleNamespace(app=client.app), _VIEW_DEFINE, inst)
    assert view["pid"] == os.getpid()
    assert view["running"] is True


def test_instance_view_garbage_pid_file_yields_none(client, monkeypatch, tmp_path):
    """TC-DMOCK-018 | instance.pid 内容非数字时 pid 降级 None

    输入: workDir=tmp 且 instance.pid="not-a-number"；_health_probe 桩 False
    预期输出: pid=None, running=False
    断言点: ValueError 分支 → pid=None
    防回归: 若 except 被删，int() 抛 ValueError 冒泡
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    inst = {"id": "x", "workDir": str(tmp_path), "port": 9005}
    (tmp_path / "instance.pid").write_text("not-a-number", encoding="utf-8")
    view = mi._instance_view(types.SimpleNamespace(app=client.app), _VIEW_DEFINE, inst)
    assert view["pid"] is None
    assert view["running"] is False


def test_instance_view_no_workdir_pid_none(client, monkeypatch):
    """TC-DMOCK-019 | 无 workDir 时 pid_file 为 None、pid 为 None

    输入: 实例无 workDir 字段；_health_probe 桩 False
    预期输出: pid=None, workDir=""
    断言点: else 分支 pid_file 为 None
    防回归: 若无 workDir 守卫被删，Path("")/"instance.pid" 行为改变
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    inst = {"id": "x", "port": 9005}
    view = mi._instance_view(types.SimpleNamespace(app=client.app), _VIEW_DEFINE, inst)
    assert view["pid"] is None
    assert view["workDir"] == ""


# =========================================================================== #
# list endpoint (173-180)
# =========================================================================== #

def test_list_instances_requires_auth_401(client):
    """TC-DMOCK-020 | 无 token 访问实例列表返回 401

    输入: 不带 Authorization
    预期输出: 401
    断言点: get_current_user 未认证守卫
    防回归: 若鉴权依赖被删除，返回 200
    """
    assert client.get("/api/v1/mock-instances").status_code == 401


def test_list_instances_structure_and_count(client, admin_token, define_env, monkeypatch):
    """TC-DMOCK-021 | 列表返回完整实例视图结构与字段合并

    输入: 管理员 token + 受控 define（3 个实例），_health_probe 桩 False
    预期输出: 3 个实例，含 id/name/port/endpoint/llm/workflow/stubVariantCount/agentId 等
    断言点: 数量 + endpoint 格式 + llm 默认/实例合并 + workflow + agentId 映射
    防回归: 若视图字段被删/改名或 llm 合并被改坏，断言失败
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    resp = client.get("/api/v1/mock-instances", headers=auth_header(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert Path(data["definePath"]) == Path(os.environ["OPENAN_DEBUG_MOCK_DEFINE"])
    insts = {i["id"]: i for i in data["instances"]}
    assert set(insts) == {"fault-diagnosis-stub", "recovery-stub", "minimal-stub"}

    i1 = insts["fault-diagnosis-stub"]
    assert i1["name"] == "OpenAN Debug Mock Agent"
    assert i1["organization"] == "OpenAN"
    assert i1["port"] == 9005
    assert i1["endpoint"] == "http://127.0.0.1:9005"
    assert i1["layer"] == "service"
    assert i1["networkDomain"] is None
    assert i1["autoStart"] is False
    assert i1["llm"]["enabled"] is False
    assert i1["llm"]["provider"] == "openai"
    assert i1["stubVariantCount"] == 2
    assert i1["workflow"]["enabled"] is False
    assert i1["workflow"]["workflowId"] is None
    assert i1["running"] is False
    assert i1["healthy"] is False
    assert i1["pid"] is None
    assert i1["agentId"] == client.app.state.default_agent_id

    i2 = insts["recovery-stub"]
    assert i2["name"] == "业务抢通打桩 Agent"
    assert i2["layer"] == "network"
    assert i2["networkDomain"] == "transmission"
    assert i2["llm"]["enabled"] is True
    assert i2["llm"]["model"] == "m"
    assert i2["stubVariantCount"] == 1
    assert i2["workflow"]["enabled"] is True
    assert i2["workflow"]["workflowId"] == "wf-1"
    assert i2["agentId"] is None

    i3 = insts["minimal-stub"]
    assert i3["name"] is None
    assert i3["port"] == 9007
    assert i3["layer"] == "service"
    assert i3["stubVariantCount"] == 0
    assert i3["llm"]["enabled"] is False
    assert i3["agentId"] is None


# =========================================================================== #
# logs endpoint / _log_tail (184, 187-191, 278-282)
# =========================================================================== #

def test_instance_logs_not_found_404(client, admin_token, define_env):
    """TC-DMOCK-022 | 未知实例取日志返回 404

    输入: instance_id=ghost
    预期输出: 404，detail 含 ghost
    断言点: _instance_by_id 404
    防回归: 若 404 守卫被删，返回 200
    """
    resp = client.get("/api/v1/mock-instances/ghost/logs", headers=auth_header(admin_token))
    assert resp.status_code == 404
    assert "ghost" in resp.json()["detail"]


def test_instance_logs_no_log_file_placeholder(client, admin_token, define_env):
    """TC-DMOCK-023 | 无日志文件时返回占位文案

    输入: workDir 存在但无 instance.log
    预期输出: 文本 "(暂无日志)"
    断言点: _log_tail 返回 "" → 端点回退占位文案
    防回归: 若占位回退被删，返回空字符串
    """
    resp = client.get("/api/v1/mock-instances/fault-diagnosis-stub/logs", headers=auth_header(admin_token))
    assert resp.status_code == 200
    assert resp.text == "(暂无日志)"


def test_instance_logs_returns_tail(client, admin_token, define_env, tmp_path):
    """TC-DMOCK-024 | 有日志文件时返回文件尾部

    输入: instance.log 含 3 行
    预期输出: 返回全部 3 行
    断言点: _log_tail 读取并按行截取
    防回归: 若读取逻辑被改坏，内容不匹配
    """
    (tmp_path / "w1" / "instance.log").write_text("line-a\nline-b\nline-c\n", encoding="utf-8")
    resp = client.get("/api/v1/mock-instances/fault-diagnosis-stub/logs", headers=auth_header(admin_token))
    assert resp.status_code == 200
    assert resp.text.strip().splitlines() == ["line-a", "line-b", "line-c"]


def test_instance_logs_lines_clamped(client, admin_token, define_env, tmp_path):
    """TC-DMOCK-025 | lines 参数被夹取到 [1,500]

    输入: 日志 5 行；lines=0（→1）、lines=99999（→500，实际取全部 5 行）
    预期输出: lines=0 返回 1 行；lines=99999 返回 5 行
    断言点: max(1, min(lines,500)) 边界
    防回归: 若夹取逻辑被改坏，行数不对
    """
    (tmp_path / "w1" / "instance.log").write_text("l1\nl2\nl3\nl4\nl5\n", encoding="utf-8")
    r0 = client.get("/api/v1/mock-instances/fault-diagnosis-stub/logs?lines=0", headers=auth_header(admin_token))
    assert r0.text.strip().splitlines() == ["l5"]
    rbig = client.get("/api/v1/mock-instances/fault-diagnosis-stub/logs?lines=99999", headers=auth_header(admin_token))
    assert len(rbig.text.strip().splitlines()) == 5


def test_instance_logs_requires_auth_401(client, define_env):
    """TC-DMOCK-026 | 无 token 取日志 401

    输入: 不带 token
    预期输出: 401
    断言点: get_current_user 守卫
    防回归: 若鉴权被删返回 200
    """
    assert client.get("/api/v1/mock-instances/fault-diagnosis-stub/logs").status_code == 401


# =========================================================================== #
# card endpoint (285-296)
# =========================================================================== #

def test_instance_card_not_found_404(client, admin_token, define_env):
    """TC-DMOCK-027 | 未知实例取卡片返回 404

    输入: instance_id=ghost
    预期输出: 404
    断言点: _instance_by_id 404
    防回归: 若 404 守卫被删
    """
    resp = client.get("/api/v1/mock-instances/ghost/card", headers=auth_header(admin_token))
    assert resp.status_code == 404


def test_instance_card_unreachable_502(client, admin_token, define_env, monkeypatch):
    """TC-DMOCK-028 | httpx 抛异常时取卡片返回 502

    输入: monkeypatch httpx.get 抛 OSError
    预期输出: 502，detail 含 "实例不可达"
    断言点: except 分支 → 502
    防回归: 若 except 被删，异常冒泡成 500
    """
    monkeypatch.setattr(mi.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("refused")))
    resp = client.get("/api/v1/mock-instances/fault-diagnosis-stub/card", headers=auth_header(admin_token))
    assert resp.status_code == 502
    assert "实例不可达" in resp.json()["detail"]


def test_instance_card_non_200_returns_502(client, admin_token, define_env, monkeypatch):
    """TC-DMOCK-029 | 实例返回非 200 时取卡片返回 502

    输入: monkeypatch httpx.get 返回 status_code=500 的响应
    预期输出: 502，detail 含 "实例返回 HTTP 500"
    断言点: status_code != 200 → 502
    防回归: 若状态码判定被反转
    """
    fake = types.SimpleNamespace(status_code=500, json=lambda: {})
    monkeypatch.setattr(mi.httpx, "get", lambda *a, **k: fake)
    resp = client.get("/api/v1/mock-instances/fault-diagnosis-stub/card", headers=auth_header(admin_token))
    assert resp.status_code == 502
    assert "实例返回 HTTP 500" in resp.json()["detail"]


def test_instance_card_ok_returns_json(client, admin_token, define_env, monkeypatch):
    """TC-DMOCK-030 | 实例返回 200 时透传卡片 JSON

    输入: monkeypatch httpx.get 返回 200 + {"name":"card"}
    预期输出: 200 且 body == {"name":"card"}
    断言点: response.json() 原样返回
    防回归: 若返回逻辑被改坏，body 不符
    """
    fake = types.SimpleNamespace(status_code=200, json=lambda: {"name": "card"})
    monkeypatch.setattr(mi.httpx, "get", lambda *a, **k: fake)
    resp = client.get("/api/v1/mock-instances/fault-diagnosis-stub/card", headers=auth_header(admin_token))
    assert resp.status_code == 200
    assert resp.json() == {"name": "card"}


def test_instance_card_requires_auth_401(client, define_env):
    """TC-DMOCK-031 | 无 token 取卡片 401

    输入: 不带 token
    预期输出: 401
    断言点: get_current_user 守卫
    """
    assert client.get("/api/v1/mock-instances/fault-diagnosis-stub/card").status_code == 401


# =========================================================================== #
# start endpoint (194-234)
# =========================================================================== #

def test_start_instance_not_found_404(client, admin_token, define_env):
    """TC-DMOCK-032 | 未知实例 start 返回 404

    输入: instance_id=ghost
    预期输出: 404
    断言点: _instance_by_id 404
    """
    assert client.post("/api/v1/mock-instances/ghost/start", headers=auth_header(admin_token)).status_code == 404


def test_start_instance_requires_auth_401(client, define_env):
    """TC-DMOCK-033 | 无 token start 返回 401

    输入: 不带 token
    预期输出: 401
    断言点: require_admin → get_current_user 守卫
    """
    assert client.post("/api/v1/mock-instances/fault-diagnosis-stub/start").status_code == 401


def test_start_instance_requires_admin_403(client, user_token, define_env):
    """TC-DMOCK-034 | 非管理员 start 返回 403

    输入: user 角色 token
    预期输出: 403
    断言点: require_admin 守卫
    """
    assert client.post("/api/v1/mock-instances/fault-diagnosis-stub/start", headers=auth_header(user_token)).status_code == 403


def test_start_instance_409_managed(client, admin_token, define_env):
    """TC-DMOCK-035 | 托管进程已存在时 start 返回 409

    输入: 注入 poll=None 假托管进程到 _PROCESSES
    预期输出: 409，detail 含 "实例已在本服务中运行"
    断言点: already-running managed → 409
    防回归: 若 409 映射被改坏，返回 200/500
    """
    mi._PROCESSES["fault-diagnosis-stub"] = _fake_proc(poll=None, pid=999)
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/start", headers=auth_header(admin_token))
    assert resp.status_code == 409
    assert "实例已在本服务中运行" in resp.json()["detail"]


def test_start_instance_409_external(client, admin_token, define_env, monkeypatch):
    """TC-DMOCK-036 | 端口已有外部健康实例时 start 返回 409

    输入: _health_probe 桩恒 True
    预期输出: 409，detail 含 "端口" 与 "已有实例在运行"
    断言点: already-running external → 409
    防回归: 若 external 409 分支被删，会走向拉起
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: True)
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/start", headers=auth_header(admin_token))
    assert resp.status_code == 409
    assert "端口" in resp.json()["detail"]
    assert "已有实例在运行" in resp.json()["detail"]


def test_start_instance_500_spawn_failure(client, admin_token, define_env, monkeypatch):
    """TC-DMOCK-037 | Popen 抛异常时 start 返回 500 并关闭日志句柄

    输入: _health_probe 桩 False；subprocess.Popen 抛 OSError
    预期输出: 500，detail 含 "进程拉起失败"；未登记到 _PROCESSES
    断言点: except 分支 → 500 + 未登记
    防回归: 若 except 被删或未关闭日志，行为改变
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    monkeypatch.setattr(mi.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("popen boom")))
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/start", headers=auth_header(admin_token))
    assert resp.status_code == 500
    assert "进程拉起失败" in resp.json()["detail"]
    assert "fault-diagnosis-stub" not in mi._PROCESSES


def test_start_instance_500_proc_exit(client, admin_token, define_env, monkeypatch):
    """TC-DMOCK-038 | 拉起后进程立即退出时 start 返回 500 并清理登记

    输入: _health_probe 桩 False；Popen 返回 poll=1 假进程
    预期输出: 500，detail 含 "实例进程退出" 与 "code=1"；已从 _PROCESSES 移除
    断言点: poll() 非 None 分支 + _PROCESSES 清理
    防回归: 若退出检测被删，会进入健康轮询
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    proc = _fake_proc(poll=1, pid=111)
    monkeypatch.setattr(mi.subprocess, "Popen", lambda *a, **k: proc)
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/start", headers=auth_header(admin_token))
    assert resp.status_code == 500
    assert "实例进程退出" in resp.json()["detail"]
    assert "code=1" in resp.json()["detail"]
    assert "fault-diagnosis-stub" not in mi._PROCESSES


def test_start_instance_504_timeout(client, admin_token, define_env, monkeypatch):
    """TC-DMOCK-039 | 进程在跑但健康检查超时 → 504（桩 time 加速）

    输入: _health_probe 桩 False；Popen 返回 poll=None 假进程；time.time/sleep 桩加速循环
    预期输出: 504，detail 含 "健康检查超时"；进程仍登记（超时不清理）
    断言点: 超时分支 + 进程仍登记
    防回归: 若超时分支被改坏，会一直轮询
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    proc = _fake_proc(poll=None, pid=222)
    monkeypatch.setattr(mi.subprocess, "Popen", lambda *a, **k: proc)
    times = iter([1000.0, 1010.0, 1030.0])
    monkeypatch.setattr(mi.time, "time", lambda: next(times, 1030.0))
    monkeypatch.setattr(mi.time, "sleep", lambda *a, **k: None)
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/start", headers=auth_header(admin_token))
    assert resp.status_code == 504
    assert "健康检查超时" in resp.json()["detail"]
    assert "fault-diagnosis-stub" in mi._PROCESSES


def test_start_instance_200_running(client, admin_token, define_env, monkeypatch):
    """TC-DMOCK-040 | 拉起并健康通过时 start 返回 200

    输入: _health_probe 首次 False（通过 external 检查）再次 True（轮询命中）；Popen 假进程
    预期输出: 200，body.status=running，含 pid/port/id
    断言点: running → 200 透传 + 进程登记
    防回归: 若命中分支被改坏，会超时
    """
    seq = iter([False, True])
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: next(seq))
    proc = _fake_proc(poll=None, pid=8888)
    monkeypatch.setattr(mi.subprocess, "Popen", lambda *a, **k: proc)
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/start", headers=auth_header(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["pid"] == 8888
    assert body["id"] == "fault-diagnosis-stub"
    assert body["port"] == 9005
    assert "fault-diagnosis-stub" in mi._PROCESSES


# =========================================================================== #
# stop endpoint (237-275)
# =========================================================================== #

def test_stop_instance_not_found_404(client, admin_token, define_env):
    """TC-DMOCK-041 | 未知实例 stop 返回 404

    输入: instance_id=ghost
    预期输出: 404
    断言点: _instance_by_id 404
    """
    assert client.post("/api/v1/mock-instances/ghost/stop", headers=auth_header(admin_token)).status_code == 404


def test_stop_instance_requires_auth_401(client, define_env):
    """TC-DMOCK-042 | 无 token stop 返回 401

    输入: 不带 token
    预期输出: 401
    断言点: require_admin → get_current_user 守卫
    """
    assert client.post("/api/v1/mock-instances/fault-diagnosis-stub/stop").status_code == 401


def test_stop_instance_requires_admin_403(client, user_token, define_env):
    """TC-DMOCK-043 | 非管理员 stop 返回 403

    输入: user 角色 token
    预期输出: 403
    断言点: require_admin 守卫
    """
    assert client.post("/api/v1/mock-instances/fault-diagnosis-stub/stop", headers=auth_header(user_token)).status_code == 403


def test_stop_managed_proc_wait_ok(client, admin_token, define_env, monkeypatch):
    """TC-DMOCK-044 | 终止托管进程 → stopped（terminate+wait 成功）

    输入: 注入 poll=None 假进程；_health_probe 桩 False
    预期输出: status=stopped，无 note；进程已从 _PROCESSES 移除且 terminate 已调用
    断言点: stopped + _PROCESSES 清空 + terminate
    防回归: 若 terminate/wait 分支被改坏，状态不符
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    proc = _fake_proc(poll=None, pid=666)
    mi._PROCESSES["fault-diagnosis-stub"] = proc
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/stop", headers=auth_header(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "stopped"
    assert "note" not in body
    assert "fault-diagnosis-stub" not in mi._PROCESSES
    assert proc._terminated is True


def test_stop_managed_proc_wait_timeout_kills(client, admin_token, define_env, monkeypatch):
    """TC-DMOCK-045 | terminate 后 wait 超时 → kill 兜底

    输入: 假进程 wait 抛 TimeoutExpired；_health_probe 桩 False
    预期输出: status=stopped；进程被 kill
    断言点: stopped + kill 已调用
    防回归: 若 kill 兜底被删，wait 超时会冒泡
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    proc = _fake_proc(poll=None, pid=777, wait_ok=False)
    mi._PROCESSES["fault-diagnosis-stub"] = proc
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/stop", headers=auth_header(admin_token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
    assert proc._killed is True


def test_stop_orphan_pidfile_taskkilled_and_removed(client, admin_token, define_env, monkeypatch, tmp_path):
    """TC-DMOCK-046 | 孤儿 pid 文件进程被 taskkill 并删除 pid 文件

    输入: workDir 写 instance.pid=12345；_pid_alive 桩 True；subprocess.run 桩 no-op
    预期输出: status=stopped，pid 文件被删除
    断言点: stopped + pid 文件消失
    防回归: 若 taskkill 或 pid 清理被改坏，文件残留
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    monkeypatch.setattr(mi, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(mi.subprocess, "run", lambda *a, **k: None)
    pid_file = tmp_path / "w1" / "instance.pid"
    pid_file.write_text("12345", encoding="utf-8")
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/stop", headers=auth_header(admin_token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
    assert "note" not in resp.json()
    assert not pid_file.exists()


def test_stop_orphan_garbage_pidfile_note(client, admin_token, define_env, monkeypatch, tmp_path):
    """TC-DMOCK-047 | instance.pid 非数字时 pid 降级 0 并跳过 taskkill

    输入: workDir 写 instance.pid="garbage"；_health_probe 桩 False
    预期输出: status=stopped, note "实例本就未在运行"；pid 文件被删除
    断言点: read ValueError 分支 → pid=0 → 不杀进程 → note
    防回归: 若 except 被删，int("garbage") 抛 ValueError 冒泡
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    pid_file = tmp_path / "w1" / "instance.pid"
    pid_file.write_text("garbage", encoding="utf-8")
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/stop", headers=auth_header(admin_token))
    assert resp.status_code == 200
    assert resp.json()["note"] == "实例本就未在运行"
    assert not pid_file.exists()


def test_stop_pidfile_unlink_oserror_swallowed(client, admin_token, define_env, monkeypatch, tmp_path):
    """TC-DMOCK-048 | pid 文件不可删时 except OSError 被吞掉

    输入: workDir 写 instance.pid=12345；_pid_alive 桩 False（跳过 taskkill）；Path.unlink 桩抛 OSError
    预期输出: status=stopped, note "实例本就未在运行"（未真正停止）
    断言点: unlink 异常被吞 + 走 note 分支
    防回归: 若 except 被删，OSError 冒泡
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    monkeypatch.setattr(mi, "_pid_alive", lambda pid: False)

    def _raise(self):
        raise OSError("locked")

    monkeypatch.setattr(mi.Path, "unlink", _raise)
    (tmp_path / "w1" / "instance.pid").write_text("12345", encoding="utf-8")
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/stop", headers=auth_header(admin_token))
    assert resp.status_code == 200
    assert resp.json().get("note") == "实例本就未在运行"


def test_stop_nothing_running_note(client, admin_token, define_env, monkeypatch):
    """TC-DMOCK-049 | 停止本就未运行的实例返回提示

    输入: 无托管进程、无 pid 文件、端口不健康
    预期输出: status=stopped, note 含 "实例本就未在运行"
    断言点: nothing-running 分支 + 不存在 pid 文件的 unlink 被吞
    防回归: 若 note 分支被改坏，note 缺失
    """
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/stop", headers=auth_header(admin_token))
    assert resp.status_code == 200
    assert resp.json()["note"] == "实例本就未在运行"


def test_stop_waits_while_port_still_healthy(client, admin_token, define_env, monkeypatch):
    """TC-DMOCK-050 | 停止后端口仍短暂健康时进入等待循环

    输入: 无托管进程、无 pid 文件；_health_probe 首次 True 随后 False
    预期输出: status=stopped, note "实例本就未在运行"；_health_probe 被调用 >=2 次
    断言点: 健康等待循环 sleep 执行
    防回归: 若等待循环被删，调用计数仍为 1，断言失败
    """
    calls = {"n": 0}

    def hp(port, timeout=1.0):
        calls["n"] += 1
        return calls["n"] == 1

    monkeypatch.setattr(mi, "_health_probe", hp)
    resp = client.post("/api/v1/mock-instances/fault-diagnosis-stub/stop", headers=auth_header(admin_token))
    assert resp.status_code == 200
    assert resp.json()["note"] == "实例本就未在运行"
    assert calls["n"] >= 2


# =========================================================================== #
# autostart_instances (305-353)
# =========================================================================== #

def test_autostart_load_define_failure_returns(monkeypatch):
    """TC-DMOCK-051 | resolve_define_path 抛异常时 autostart 直接返回

    输入: monkeypatch resolve_define_path 抛 RuntimeError
    预期输出: _PROCESSES 空
    断言点: 顶层 try/except 守卫
    防回归: 若 except 被删，异常冒泡到线程外
    """
    monkeypatch.setattr(mi, "resolve_define_path", lambda: (_ for _ in ()).throw(RuntimeError("no define")))
    mi.autostart_instances()
    time.sleep(0.6)
    assert mi._PROCESSES == {}


def test_autostart_empty_override_starts_nothing(define_env, monkeypatch):
    """TC-DMOCK-052 | OPENAN_DEBUG_AUTOSTART 为空串时不拉起任何实例

    输入: OPENAN_DEBUG_AUTOSTART=""
    预期输出: _PROCESSES 保持空
    断言点: wanted 为空集 → 全部 continue
    防回归: 若空串判定被改坏，会拉起 autoStart 实例
    """
    monkeypatch.setenv("OPENAN_DEBUG_AUTOSTART", "")
    monkeypatch.setattr(mi.subprocess, "Popen", lambda *a, **k: pytest.fail("不应拉起"))
    mi.autostart_instances()
    time.sleep(0.6)
    assert mi._PROCESSES == {}


def test_autostart_no_env_skips_non_autostart(define_env, monkeypatch):
    """TC-DMOCK-053 | 无 override 时 autoStart=false 的实例被跳过

    输入: 删除 OPENAN_DEBUG_AUTOSTART 环境变量
    预期输出: _PROCESSES 空（受控 define 所有实例 autoStart 均为 false）
    断言点: autoStart 守卫
    防回归: 若 autoStart 守卫被删，会拉起实例
    """
    monkeypatch.delenv("OPENAN_DEBUG_AUTOSTART", raising=False)
    monkeypatch.setattr(mi.subprocess, "Popen", lambda *a, **k: pytest.fail("不应拉起"))
    mi.autostart_instances()
    time.sleep(0.6)
    assert mi._PROCESSES == {}


def test_autostart_override_spawn_registers(define_env, monkeypatch):
    """TC-DMOCK-054 | 指定实例 override + 健康未占端口 → 拉起并登记

    输入: OPENAN_DEBUG_AUTOSTART="fault-diagnosis-stub"；_health_probe 桩 False；Popen 返回 poll=1 假进程
    预期输出: _PROCESSES 含 fault-diagnosis-stub
    断言点: override 命中 + 拉起 + 登记
    防回归: 若 override 过滤或拉起逻辑被改坏，不登记
    """
    monkeypatch.setenv("OPENAN_DEBUG_AUTOSTART", "fault-diagnosis-stub")
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    proc = _fake_proc(poll=1, pid=31415)
    monkeypatch.setattr(mi.subprocess, "Popen", lambda *a, **k: proc)
    mi.autostart_instances()
    time.sleep(1.0)
    assert "fault-diagnosis-stub" in mi._PROCESSES


def test_autostart_loop_sleeps(define_env, monkeypatch):
    """TC-DMOCK-055 | 拉起后进程未退出且未健康时进入轮询 sleep

    输入: OPENAN_DEBUG_AUTOSTART="fault-diagnosis-stub"；Popen 返回 poll 首 None 再次 1 的假进程；_health_probe 桩 False
    预期输出: _PROCESSES 含实例（轮询 sleep 至少执行一次后退出循环）
    断言点: 轮询循环 sleep 执行
    防回归: 若循环被删，poll 不会从 None 变 1
    """
    monkeypatch.setenv("OPENAN_DEBUG_AUTOSTART", "fault-diagnosis-stub")
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    poll_seq = iter([None, 1])
    proc = _fake_proc(pid=27182)
    proc.poll = lambda: next(poll_seq)
    monkeypatch.setattr(mi.subprocess, "Popen", lambda *a, **k: proc)
    mi.autostart_instances()
    time.sleep(1.0)
    assert "fault-diagnosis-stub" in mi._PROCESSES


def test_autostart_skips_when_already_healthy(define_env, monkeypatch):
    """TC-DMOCK-056 | override 实例端口已健康时跳过拉起

    输入: OPENAN_DEBUG_AUTOSTART="fault-diagnosis-stub"；_health_probe 桩 True
    预期输出: _PROCESSES 空（不重复拉起）
    断言点: 健康短路 continue
    防回归: 若健康短路被删，会重复拉起
    """
    monkeypatch.setenv("OPENAN_DEBUG_AUTOSTART", "fault-diagnosis-stub")
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: True)
    monkeypatch.setattr(mi.subprocess, "Popen", lambda *a, **k: pytest.fail("不应拉起"))
    mi.autostart_instances()
    time.sleep(0.6)
    assert mi._PROCESSES == {}


def test_autostart_spawn_exception_is_logged(define_env, monkeypatch):
    """TC-DMOCK-057 | autostart 拉起抛异常时仅记日志不崩溃

    输入: OPENAN_DEBUG_AUTOSTART="fault-diagnosis-stub"；_health_probe 桩 False；Popen 抛 RuntimeError
    预期输出: _PROCESSES 空（异常被 except 吞）
    断言点: 拉起异常守卫
    防回归: 若 except 被删，线程异常
    """
    monkeypatch.setenv("OPENAN_DEBUG_AUTOSTART", "fault-diagnosis-stub")
    monkeypatch.setattr(mi, "_health_probe", lambda port, timeout=1.0: False)
    monkeypatch.setattr(mi.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("spawn fail")))
    mi.autostart_instances()
    time.sleep(0.8)
    assert mi._PROCESSES == {}
