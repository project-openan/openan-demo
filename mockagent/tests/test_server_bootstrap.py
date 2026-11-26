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

"""网关/启动入口覆盖测试：standalone_agent / gateway / main / portal_gateway。

补齐入口与 bootstrap 模块的语句覆盖：工厂函数、桩变体导入、Agent 行就绪、
单进程网关挂载、main 的 lifespan/_log_sink/_mount_agent/探针分支、portal 网关
的反代（stripPrefix / query string）与路由校验分支。uvicorn.run 仅以桩函数替换
（不真实拉起服务），`if __name__ == "__main__"` 守卫为不可达。
"""
import json
import socket
import sys
import threading
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from mockagent_engine import gateway as gw
from mockagent_engine import main as app_main
from mockagent_engine import portal_gateway as pg
from mockagent_engine import standalone_agent as sa
from mockagent_engine.agent.base import StubAgentBase
from mockagent_engine.agent.flow_env import FALLBACK_ENV
from mockagent_engine.agent_registry import agents_dir, load_agent, load_defaults, load_define
from mockagent_engine.config import load_settings
from mockagent_engine.db import init_db, make_engine
from mockagent_engine.models import Agent, RequestLog, Variant


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def iso_env(tmp_path, monkeypatch):
    """隔离运行环境：临时 SQLite + 固定密钥 + 关闭 autostart（避免拉起子进程）。"""
    monkeypatch.setenv("MOCK_AGENT_DB_PATH", str(tmp_path / "iso.db"))
    monkeypatch.setenv("MOCK_AGENT_JWT_SECRET", "fixture-only-64-byte-test-key-" * 3)
    monkeypatch.setenv("MOCK_AGENT_ADMIN_PASSWORD", "iso-admin")
    monkeypatch.setenv("MOCK_AGENT_AUTOSTART", "")


@pytest.fixture()
def isolated_settings(iso_env):
    return load_settings()


@pytest.fixture()
def engine(isolated_settings):
    eng = make_engine(isolated_settings)
    init_db(eng, isolated_settings)
    return eng


def _write_agents_dir(root: Path, work_root: Path):
    """构造受控的 agents/ 目录：两个无 agent.py 的纯配置打桩实例。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "_defaults.json").write_text(
        json.dumps(
            {
                "host": "0.0.0.0",
                "publicUrlBase": "http://127.0.0.1",
                "llm": {
                    "enabled": False,
                    "provider": "openai",
                    "baseUrl": "http://127.0.0.1:8000/v1",
                    "model": "m",
                    "apiKeyEnv": "MOCK_AGENT_LLM_API_KEY",
                    "maxAttempts": 1,
                    "language": "zh-CN",
                },
                "stubVariants": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    for aid, port in [("alpha-stub", 9301), ("beta-stub", 9302)]:
        d = root / aid
        d.mkdir(exist_ok=True)
        (d / "agent.json").write_text(
            json.dumps(
                {
                    "id": aid,
                    "name": f"{aid} Agent",
                    "organization": "TestOrg",
                    "description": aid,
                    "layer": "service",
                    "port": port,
                    "workDir": str(work_root / aid),
                    "llm": {"enabled": False},
                    "stubVariants": [],
                    "cardName": f"mockagent_{aid}",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


@pytest.fixture()
def agents_root(tmp_path, monkeypatch):
    root = tmp_path / "agents"
    work_root = tmp_path / "works"
    _write_agents_dir(root, work_root)
    monkeypatch.setenv("MOCK_AGENT_AGENTS_DIR", str(root))
    return root


class _CapturingAgent(StubAgentBase):
    """记录 build_runtime 收到的运行时字典，用于断言 workflow 分支落位。"""

    def build_runtime(self, runtime):
        self.captured = runtime
        return runtime


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def upstream_url():
    """临时上游（验证 portal 网关真实反代：回显收到的 path/query）。"""
    app = FastAPI()

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def echo(request: Request):
        return {"path": request.url.path, "query": request.url.query}

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    import time

    import httpx

    for _ in range(50):
        try:
            httpx.get(f"http://127.0.0.1:{port}/ping", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def _dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist"
    d.mkdir()
    (d / "index.html").write_text("<html>portal</html>", encoding="utf-8")
    return d


def _request_log_entry(**overrides):
    base = {
        "agent_id": None,
        "template_uri": "Task-T/network-layer/private-line-complaint/v1",
        "direction": "inbound",
        "feature": "a2at",
        "request_body": {"templateUri": "Task-T/x/y/v1"},
        "response_body": {"state": "COMPLETED"},
        "task_state": "TASK_STATE_COMPLETED",
        "negotiated": False,
        "latency_ms": 12,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# standalone_agent
# --------------------------------------------------------------------------- #
def test_merged_llm_instance_overrides_defaults():
    """TC-GW-001 | 实例 llm 覆盖 defaults 基线，缺失键由基线补齐

    输入: defaults.llm={model:base,enabled:True}, instance.llm={model:override,maxAttempts:5}
    预期输出: 合并结果 model=override(实例优先), enabled=True(基线补齐), maxAttempts=5(实例)
    断言点: model/enabled/maxAttempts 三个键的取值来源
    防回归: 若合并顺序写反（基线覆盖实例），model 变为 base，用例失败
    """
    define = {"defaults": {"llm": {"model": "base", "enabled": True}}}
    instance = {"llm": {"model": "override", "maxAttempts": 5}}
    merged = sa.merged_llm(instance, define)
    assert merged["model"] == "override"
    assert merged["enabled"] is True
    assert merged["maxAttempts"] == 5


def test_merged_llm_instance_without_llm_uses_defaults():
    """TC-GW-002 | 实例未声明 llm 时完全取 defaults

    输入: instance={}，defaults.llm={provider:x,enabled:False}
    预期输出: 合并结果 == defaults.llm
    断言点: provider/enabled 与基线一致
    防回归: 若 instance.get("llm") or {} 写成强取 instance["llm"]，无 llm 实例会 KeyError
    """
    define = {"defaults": {"llm": {"provider": "x", "enabled": False}}}
    merged = sa.merged_llm({}, define)
    assert merged == {"provider": "x", "enabled": False}


def test_merged_stub_variants_instance_first_baseline_fills():
    """TC-GW-003 | 实例桩在前、defaults 基线按模板去重补齐

    输入: defaults.stubVariants=[{T:A},{T:B},{T:C}], instance.stubVariants=[{T:B,own}]
    预期输出: [{T:B,own}, {T:A}, {T:C}]（实例优先，基线 B 被去重）
    断言点: 顺序与模板集合
    防回归: 若去重逻辑写反（基线在前），实例 own 会被基线 B 覆盖
    """
    define = {"defaults": {"stubVariants": [{"templateUri": "A"}, {"templateUri": "B"}, {"templateUri": "C"}]}}
    instance = {"stubVariants": [{"templateUri": "B", "variantJson": {"own": 1}}]}
    merged = sa.merged_stub_variants(instance, define)
    assert [m["templateUri"] for m in merged] == ["B", "A", "C"]
    assert merged[0]["variantJson"] == {"own": 1}


def test_write_llm_env_disabled_writes_fallback(tmp_path):
    """TC-GW-004 | llm.enabled=false 写入 FALLBACK_ENV（纯打桩模式）

    输入: instance.llm={enabled:False}, work_dir=tmp
    预期输出: work_dir/llm.env 内容 == FALLBACK_ENV
    断言点: 文件内容逐字等于 FALLBACK_ENV
    防回归: 若禁用分支改成写空文件，桩回落模式将失效
    """
    env = sa.write_llm_env({"llm": {"enabled": False}}, {"defaults": {}}, tmp_path)
    assert env.read_text(encoding="utf-8") == FALLBACK_ENV


def test_write_llm_env_enabled_writes_resolved_fields(tmp_path, monkeypatch):
    """TC-GW-005 | llm.enabled=true 写入 provider/model/apiKey/baseUrl/maxAttempts/language

    输入: instance.llm={enabled:True,provider,model,baseUrl,apiKeyEnv:MY_KEY,maxAttempts:3,language:en-US}
    预期输出: llm.env 含解析后的字段，apiKey 取自环境变量 MY_KEY
    断言点: 各字段值与 maxAttempts 转 int、apiKey 来自 env
    防回归: 若 apiKeyEnv 读 env 写错或 maxAttempts 未转 int，对应行内容错
    """
    monkeypatch.setenv("MY_KEY", "secret123")
    llm = {
        "enabled": True,
        "provider": "openai",
        "model": "qwen",
        "baseUrl": "http://llm:8000/v1",
        "apiKeyEnv": "MY_KEY",
        "maxAttempts": 3,
        "language": "en-US",
    }
    env = sa.write_llm_env({"llm": llm}, {"defaults": {}}, tmp_path)
    text = env.read_text(encoding="utf-8")
    assert "A2AT_LLM_PROVIDER=openai" in text
    assert "A2AT_LLM_MODEL=qwen" in text
    assert "A2AT_LLM_API_KEY=secret123" in text
    assert "A2AT_LLM_BASE_URL=http://llm:8000/v1" in text
    assert "A2AT_LLM_MAX_ATTEMPTS=3" in text
    assert "A2AT_LANGUAGE=en-US" in text


async def test_standalone_log_sink_persists_request_log(engine):
    """TC-GW-006 | standalone._log_sink 把请求日志落盘到 request_logs

    输入: 真实 engine + 一条 RequestLog entry
    预期输出: request_logs 表新增一行，字段与 entry 一致
    断言点: 行数 +1 且 template_uri/feature 与 entry 一致
    防回归: 若 _log_sink 漏 commit 或字段错位，落盘失败/字段错
    """
    entry = _request_log_entry(agent_id=None, template_uri="Task-T/a/b/v1")
    await sa._log_sink(engine, entry)
    with Session(engine) as session:
        rows = session.scalars(select(RequestLog).where(RequestLog.template_uri == "Task-T/a/b/v1")).all()
    assert len(rows) == 1
    assert rows[0].feature == "a2at"
    assert rows[0].task_state == "TASK_STATE_COMPLETED"


def test_ensure_agent_creates_new_row(engine):
    """TC-GW-007 | ensure_agent 在无对应 Agent 行时创建并返回 id

    输入: 全新 organization/agentName 的 instance
    预期输出: 创建 Agent 行，返回 int id，字段写入
    断言点: 返回值为 int 且库中可查到同 org/name 的行
    防回归: 若未 commit 或字段未写，查不到行
    """
    instance = {
        "organization": "NewOrg",
        "agentName": "NewAgent",
        "description": "desc",
        "layer": "network",
        "networkDomain": "ran",
    }
    with Session(engine) as session:
        new_id = sa.ensure_agent(session, instance)
        assert isinstance(new_id, int)
        row = session.scalar(select(Agent).where(Agent.organization == "NewOrg", Agent.name == "NewAgent"))
    assert row is not None
    assert row.enabled is True
    assert row.layer == "network"
    assert row.network_domain == "ran"


def test_ensure_agent_re_enables_disabled_row(engine):
    """TC-GW-008 | ensure_agent 命中已存在但禁用的 Agent 行时重新启用

    输入: 先建 enabled=False 的 Agent，再以同 org/name 调 ensure_agent
    预期输出: 返回同一 id，且 enabled 被改为 True
    断言点: id 不变 + enabled 由 False 变 True
    防回归: 若缺失 re-enable 分支，禁用 Agent 永远拉不起来
    """
    with Session(engine) as session:
        agent = Agent(organization="ROrg", name="RAgent", enabled=False, layer="service")
        session.add(agent)
        session.commit()
        session.refresh(agent)
        disabled_id = agent.id
        returned_id = sa.ensure_agent(session, {"organization": "ROrg", "agentName": "RAgent"})
        session.refresh(agent)
    assert returned_id == disabled_id
    assert agent.enabled is True


def test_ensure_agent_existing_enabled_unchanged(engine):
    """TC-GW-009 | ensure_agent 命中已启用 Agent 行时直接返回 id（不改状态）

    输入: 已存在 enabled=True 的 Agent 行
    预期输出: 返回同一 id，enabled 仍为 True
    断言点: id 相同 + enabled 不变
    防回归: 若误把已启用 Agent 也重置/重建，会产生重复行
    """
    with Session(engine) as session:
        agent = Agent(organization="EOrg", name="EAgent", enabled=True, layer="service")
        session.add(agent)
        session.commit()
        session.refresh(agent)
        existing_id = agent.id
        returned_id = sa.ensure_agent(session, {"organization": "EOrg", "agentName": "EAgent"})
    assert returned_id == existing_id


def test_ensure_stub_variants_empty_returns_zero(engine):
    """TC-GW-010 | ensure_stub_variants 收到空列表时返回 0 且不写

    输入: stub_variants=[]
    预期输出: 返回 0，variants 表无新增
    断言点: 返回值 0 + 表行数不变
    防回归: 若缺失空列表守卫，会进入循环并可能误查
    """
    with Session(engine) as session:
        agent_id = sa.ensure_agent(session, {"organization": "EOrg", "agentName": "Empty"})
        created = sa.ensure_stub_variants(session, agent_id, [])
        count = session.scalar(select(Variant).where(Variant.agent_id == agent_id))
    assert created == 0
    assert count is None


def test_ensure_stub_variants_inserts_then_skips_existing(engine):
    """TC-GW-011 | ensure_stub_variants 首次按模板插入（同模板自增 seq），再次调用全部跳过

    输入: 首次给 [T1,T1,T2] 三条；第二次给相同三条
    预期输出: 首次 created=3（T1 seq 0/1、T2 seq 0），第二次 created=0，表行数仍 3
    断言点: 首次返回 3、第二次返回 0、T1 两条 seq 分别为 0 与 1
    防回归: 若 seq 计数写错或 existing 集合每次重算导致重复插入，seq/行数错
    """
    variants = [
        {"templateUri": "T1", "variantJson": {"a": 1}},
        {"templateUri": "T1", "variantJson": {"a": 2}},
        {"templateUri": "T2", "variantJson": {"b": 1}},
    ]
    with Session(engine) as session:
        agent_id = sa.ensure_agent(session, {"organization": "VOrg", "agentName": "VAgent"})
        first = sa.ensure_stub_variants(session, agent_id, variants)
        second = sa.ensure_stub_variants(session, agent_id, variants)
        rows = session.scalars(select(Variant).where(Variant.agent_id == agent_id).order_by(Variant.id)).all()
    assert first == 3
    assert second == 0
    assert len(rows) == 3
    t1_seqs = sorted(r.seq for r in rows if r.template_uri == "T1")
    assert t1_seqs == [0, 1]
    assert [r.template_uri for r in rows if r.template_uri == "T2"] == ["T2"]


def test_build_runner_app_stub_fallback_builds_and_card_url(isolated_settings, tmp_path):
    """TC-GW-012 | build_runner_app(agent=None) 构建桩回落实例：卡片 URL 用 public_url，写 llm.env，落 Agent 行

    输入: 合成实例(llm 禁用)+ public_url 覆盖 + agent=None
    预期输出: /health 返回 llm=stub-fallback；卡片 supportedInterfaces.url==public_url；llm.env==FALLBACK_ENV；Agent 行已建
    断言点: health 字段 + 卡片 URL + llm.env 内容 + Agent 行存在
    防回归: 若 public_url 覆盖未生效，卡片 URL 变默认基线；若 agent=None 分支抛错，构建失败
    """
    instance = {
        "id": "sa-stub",
        "name": "SA Stub",
        "organization": "SAOrg",
        "description": "d",
        "port": 9301,
        "workDir": str(tmp_path / "w"),
        "llm": {"enabled": False},
        "stubVariants": [{"templateUri": "Task-T/a/b/v1", "variantJson": {"k": 1}}],
        "cardName": "mockagent_sa",
    }
    define = {"defaults": {"llm": {"enabled": False}, "stubVariants": [], "publicUrlBase": "http://127.0.0.1"}}
    public_url = "http://example.test:9301/agents/sa-stub"
    app = sa.build_runner_app(instance, define, isolated_settings, agent=None, public_url=public_url)

    assert app.state.mock_instance["id"] == "sa-stub"
    assert (tmp_path / "w" / "llm.env").read_text(encoding="utf-8") == FALLBACK_ENV
    client = TestClient(app, raise_server_exceptions=False)
    health = client.get("/health").json()
    assert health["llm"] == "stub-fallback"
    assert health["instance"] == "sa-stub"
    card = client.get("/.well-known/agent-card.json").json()
    assert card["supportedInterfaces"][0]["url"] == public_url
    with Session(make_engine(isolated_settings)) as session:
        row = session.scalar(select(Agent).where(Agent.organization == "SAOrg", Agent.name == "SA Stub"))
    assert row is not None and row.enabled is True


def test_build_runner_app_workflow_enabled_loads_cards(isolated_settings, tmp_path):
    """TC-GW-013 | build_runner_app 对 workflow.enabled 实例加载内置工作流并解析 agent 卡

    输入: 真实 an-l4-live-streaming-agent 实例(workDir 改 tmp) + 真实 define + _CapturingAgent
    预期输出: runtime.workflow_config.enabled=True 且 workflow_cards 非空；app.state.mock_instance 落位
    断言点: captured.workflow_config.enabled + workflow_cards 长度>0 + mock_instance.id
    防回归: 若 workflow 分支漏调 load_builtin/agent_cards_for，workflow_cards 为空
    """
    instance = dict(load_agent(agents_dir() / "an-l4-live-streaming-agent"))
    instance["workDir"] = str(tmp_path / "wf")
    instance["port"] = 9310
    define = load_define()
    agent = _CapturingAgent(instance, define["defaults"])
    app = sa.build_runner_app(instance, define, isolated_settings, agent=agent)

    assert app.state.mock_instance["id"] == "an-l4-live-streaming-agent"
    assert agent.captured["workflow_config"]["enabled"] is True
    assert len(agent.captured["workflow_cards"]) > 0


def test_standalone_main_unknown_agent_raises_systemexit(iso_env, agents_root, monkeypatch):
    """TC-GW-014 | standalone.main 对未知 agent id 抛 SystemExit（FileNotFoundError 转译）

    输入: --agent no-such-id（agents_root 中不存在）
    预期输出: 抛 SystemExit，消息含未找到提示
    断言点: SystemExit 且消息含 "未找到 Agent 目录"
    防回归: 若缺失 FileNotFoundError 捕获，会冒出原始异常而非 SystemExit
    """
    monkeypatch.setattr(sys, "argv", ["standalone_agent", "--agent", "no-such-id"])
    with pytest.raises(SystemExit, match="未找到 Agent 目录"):
        sa.main()


def test_standalone_main_builds_and_pid_lifecycle(iso_env, agents_root, tmp_path, monkeypatch):
    """TC-GW-015 | standalone.main 解析实例并构建 app，pid 文件先写后清（uvicorn.run 以桩替换）

    输入: --agent alpha-stub --port 9311，CWD 改到 tmp；uvicorn.run 替换为记录桩
    预期输出: 桩调用时 pid 文件已存在、port=9311、host=0.0.0.0；main 返回后 pid 文件被清理
    断言点: 桩记录的 port/host + pid 存在性 + 退出后 pid 不存在
    防回归: 若 pid 写入/清理逻辑丢失，或 port 覆盖未生效，断言失败
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["standalone_agent", "--agent", "alpha-stub", "--port", "9311"])
    recorded = {}

    def fake_run(app, host=None, port=None, log_level=None):
        pid_file = Path(app.state.mock_instance["workDir"]) / "instance.pid"
        recorded["host"] = host
        recorded["port"] = port
        recorded["pid_existed"] = pid_file.exists()
        recorded["pid_content"] = pid_file.read_text(encoding="utf-8")

    monkeypatch.setattr(sa.uvicorn, "run", fake_run)
    sa.main()

    assert recorded["port"] == 9311
    assert recorded["host"] == "0.0.0.0"
    assert recorded["pid_existed"] is True
    assert str(recorded["pid_content"]).isdigit()
    pid_after = tmp_path / "works" / "alpha-stub" / "instance.pid"
    assert not pid_after.exists()


# --------------------------------------------------------------------------- #
# gateway
# --------------------------------------------------------------------------- #
def test_select_instances_no_filter_returns_all(agents_root):
    """TC-GW-016 | select_instances 无过滤时按目录序返回全部实例

    输入: agents_root 含 alpha-stub/beta-stub，无过滤
    预期输出: 返回两个实例，id 集合 == {alpha-stub, beta-stub}
    断言点: 实例数量 + id 集合
    防回归: 若跳过目录或漏读 agent.json，数量/集合错
    """
    loaded = gw.select_instances(None)
    ids = {inst["id"] for _, inst in loaded}
    assert ids == {"alpha-stub", "beta-stub"}
    assert all(d.is_dir() for d, _ in loaded)


def test_select_instances_filter_restricts(agents_root):
    """TC-GW-017 | select_instances 按 id 过滤，仅返回命中的实例

    输入: filter=["alpha-stub"]
    预期输出: 仅返回 alpha-stub
    断言点: 返回长度 1 且 id == alpha-stub
    防回归: 若过滤条件写反，会返回错误实例
    """
    loaded = gw.select_instances(["alpha-stub"])
    assert [inst["id"] for _, inst in loaded] == ["alpha-stub"]


def test_select_instances_skips_non_dirs_and_missing_json(tmp_path, monkeypatch):
    """TC-GW-018 | select_instances 跳过非目录项与无 agent.json 的目录

    输入: agents 目录含一个普通文件、一个无 agent.json 的空目录、两个合法实例
    预期输出: 仅返回两个合法实例
    断言点: 返回 id 列表 == [alpha-stub, beta-stub]
    防回归: 若未判 is_dir 或 agent.json 存在性，会误纳入
    """
    root = tmp_path / "agents"
    work_root = tmp_path / "works"
    _write_agents_dir(root, work_root)
    (root / "not-a-dir.txt").write_text("x", encoding="utf-8")
    (root / "empty-dir").mkdir()
    monkeypatch.setenv("MOCK_AGENT_AGENTS_DIR", str(root))
    loaded = gw.select_instances(None)
    assert [inst["id"] for _, inst in loaded] == ["alpha-stub", "beta-stub"]


def test_build_gateway_app_mounts_instances_and_health(iso_env, agents_root, isolated_settings):
    """TC-GW-019 | build_gateway_app 把实例挂到 /agents/<id>/，health 汇总且 /agents 索引可用

    输入: agents_root 两个实例 + public_url_base
    预期输出: /health mode=gateway 且列出两个实例；/agents 返回两个 id；子应用 /agents/alpha-stub/health 可达
    断言点: health.mode/agents 路径 + /agents 索引 + 子应用 health.instance
    防回归: 若挂载前缀错或共享 engine 漏 init_db，子应用 health 不可达
    """
    loaded = gw.select_instances(None)
    app = gw.build_gateway_app(
        loaded, load_defaults(), public_url_base="http://gw.test:9300", settings=isolated_settings
    )
    assert app.state.mock_gateway["instances"] == ["alpha-stub", "beta-stub"]
    client = TestClient(app, raise_server_exceptions=False)
    health = client.get("/health").json()
    assert health["mode"] == "gateway"
    assert {a["id"] for a in health["agents"]} == {"alpha-stub", "beta-stub"}
    assert {a["path"] for a in health["agents"]} == {"/agents/alpha-stub/", "/agents/beta-stub/"}
    assert client.get("/agents").json()["instances"] == ["alpha-stub", "beta-stub"]
    sub = client.get("/agents/alpha-stub/health").json()
    assert sub["instance"] == "alpha-stub"


def test_gateway_main_no_instances_raises_systemexit(iso_env, agents_root, monkeypatch):
    """TC-GW-020 | gateway.main 在无可挂载实例时抛 SystemExit

    输入: --agents nonexistent-id（过滤掉全部）
    预期输出: 抛 SystemExit，消息含无可挂载提示
    断言点: SystemExit 且消息含 "没有可挂载的实例"
    防回归: 若缺失空实例守卫，会进入 build_gateway_app 并最终 uvicorn.run 挂死
    """
    monkeypatch.setattr(sys, "argv", ["gateway", "--port", "9399", "--agents", "nonexistent-id"])
    with pytest.raises(SystemExit, match="没有可挂载的实例"):
        gw.main()


def test_gateway_main_builds_and_manifest_lifecycle(iso_env, agents_root, tmp_path, monkeypatch):
    """TC-GW-021 | gateway.main 构建网关并写 manifest，退出后清理（uvicorn.run 以桩替换）

    输入: --port 9399 --public-url-base http://gw.test:9399，CWD 改 tmp；uvicorn.run 替换为记录桩
    预期输出: 桩调用时 manifest 已写且内容含 port=9399 与两实例；main 返回后 manifest 被清理
    断言点: 桩记录的 manifest 内容 + 退出后 manifest 不存在
    防回归: 若 manifest 写入/清理丢失，或 port 未透传，断言失败
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["gateway", "--port", "9399", "--public-url-base", "http://gw.test:9399"]
    )
    recorded = {}

    def fake_run(app, host=None, port=None, log_level=None):
        manifest = Path("data") / "gateway_manifest.json"
        recorded["manifest_existed"] = manifest.exists()
        recorded["manifest"] = json.loads(manifest.read_text(encoding="utf-8"))
        recorded["host"] = host

    monkeypatch.setattr(gw.uvicorn, "run", fake_run)
    gw.main()

    assert recorded["manifest_existed"] is True
    assert recorded["manifest"]["port"] == 9399
    assert recorded["manifest"]["publicUrlBase"] == "http://gw.test:9399"
    assert recorded["manifest"]["agents"] == ["alpha-stub", "beta-stub"]
    assert not (tmp_path / "data" / "gateway_manifest.json").exists()


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def test_lifespan_runs_autostart_and_dispose(iso_env, isolated_settings, monkeypatch):
    """TC-GW-022 | main.lifespan 启动时调 autostart_instances、退出时 dispose engine

    输入: 以桩替换 autostart_instances 记录调用、包装 engine.dispose；TestClient 进入/退出上下文
    预期输出: 上下文内 /api/v1/health 返回 200；autostart 被调用；退出后 dispose 被调用
    断言点: 200 + autostart 标志 + dispose 标志
    防回归: 若 lifespan 漏调 autostart 或漏 dispose，对应标志为 False
    """
    started = []
    monkeypatch.setattr(
        "mockagent_engine.routers.mock_instances_router.autostart_instances",
        lambda: started.append(True),
    )
    app = app_main.create_app(isolated_settings)
    disposed = []
    original = app.state.engine.dispose

    def _dispose():
        disposed.append(True)
        original()

    app.state.engine.dispose = _dispose
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
    assert started == [True]
    assert disposed == [True]


async def test_main_log_sink_engine_none_returns_without_write(engine):
    """TC-GW-023 | main._log_sink 在 runtime.engine 为 None 时直接返回不落盘

    输入: runtime={"engine": None} + entry
    预期输出: 返回 None，request_logs 表不新增
    断言点: 返回 None + 表行数不变
    防回归: 若缺失 None 守卫，Session(None) 会抛 TypeError
    """
    with Session(engine) as session:
        before = session.scalar(select(RequestLog.id))
    result = await app_main._log_sink({"engine": None}, _request_log_entry())
    with Session(engine) as session:
        after = session.scalar(select(RequestLog.id))
    assert result is None
    assert before == after


async def test_main_log_sink_persists_request_log(engine):
    """TC-GW-024 | main._log_sink 在 engine 存在时把请求日志落盘

    输入: runtime={"engine": engine} + entry
    预期输出: request_logs 表新增一行，字段与 entry 一致
    断言点: 行数 +1 且 template_uri/feature 与 entry 一致
    防回归: 若 _write 漏 commit，落盘失败
    """
    entry = _request_log_entry(template_uri="Task-T/main/sink/v1", latency_ms=7)
    await app_main._log_sink({"engine": engine}, entry)
    with Session(engine) as session:
        rows = session.scalars(select(RequestLog).where(RequestLog.template_uri == "Task-T/main/sink/v1")).all()
    assert len(rows) == 1
    assert rows[0].feature == "a2at"
    assert rows[0].latency_ms == 7


def test_public_base_strips_debug_suffix():
    """TC-GW-025 | _public_base 仅剥离 /debug/a2a 后缀，其它 URL 原样返回

    输入: "http://h:9/debug/a2a" 与 "http://h:9/other"
    预期输出: 分别 "http://h:9" 与 "http://h:9/other"
    断言点: 两个分支返回值
    防回归: 若 endswith 判定错或切片错，前缀计算错位
    """
    assert app_main._public_base("http://h:9/debug/a2a") == "http://h:9"
    assert app_main._public_base("http://h:9/other") == "http://h:9/other"


def test_create_app_mounts_non_default_agent(iso_env, engine, isolated_settings):
    """TC-GW-026 | create_app 对非默认启用 Agent 挂载到 /debug/a2a/agent/<id>（含路由重排）

    输入: 预置一个额外启用 Agent，再 create_app
    预期输出: agent_runtimes 含默认与非默认两键；存在 /debug/a2a/agent/<id> 与 /debug/a2a 挂载
    断言点: agent_runtimes 含两键 + 非默认挂载路径存在 + 默认挂载路径存在
    防回归: 若非默认挂载或路由重排丢失，非默认挂载路径缺失
    """
    with Session(engine) as session:
        session.add(Agent(name="NonDefault Agent", enabled=True, layer="service"))
        session.commit()
        second_id = session.scalar(select(Agent).where(Agent.name == "NonDefault Agent")).id
    app = app_main.create_app(isolated_settings)
    mount_paths = {getattr(r, "path", None) for r in app.router.routes}
    assert second_id in app.state.agent_runtimes
    assert app.state.default_agent_id in app.state.agent_runtimes
    assert f"/debug/a2a/agent/{second_id}" in mount_paths
    assert "/debug/a2a" in mount_paths


def test_create_app_skips_disabled_non_default_agent(iso_env, engine, isolated_settings):
    """TC-GW-027 | create_app 不挂载非默认但被禁用的 Agent

    输入: 预置一个 enabled=False 的非默认 Agent，再 create_app
    预期输出: agent_runtimes 仅含默认；无 /debug/a2a/agent/<id> 挂载
    断言点: agent_runtimes 不含禁用 Agent + 无对应挂载路径
    防回归: 若漏判 agent.enabled，禁用 Agent 会被误挂载
    """
    with Session(engine) as session:
        session.add(Agent(name="Disabled Agent", enabled=False, layer="service"))
        session.commit()
        disabled_id = session.scalar(select(Agent).where(Agent.name == "Disabled Agent")).id
    app = app_main.create_app(isolated_settings)
    mount_paths = {getattr(r, "path", None) for r in app.router.routes}
    assert disabled_id not in app.state.agent_runtimes
    assert f"/debug/a2a/agent/{disabled_id}" not in mount_paths


def test_healthz_returns_ok(client):
    """TC-GW-028 | /healthz 免鉴权返回 ok

    输入: GET /healthz
    预期输出: 200 {"status":"ok"}
    断言点: 状态码 + status 字段
    防回归: 若探针路由被删，404
    """
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_ok_when_db_up(client):
    """TC-GW-029 | /readyz 在 DB 可读时返回 ok

    输入: GET /readyz（DB 正常）
    预期输出: 200 {"status":"ok"}
    断言点: 状态码 + status
    防回归: 若就绪探针漏建表查询或抛错，返回 503
    """
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readyz_503_when_db_down(app, tmp_path):
    """TC-GW-030 | /readyz 在 DB 不可读时返回 503 unavailable

    输入: 把 app.state.engine 换成指向不存在目录的 engine，GET /readyz
    预期输出: 503，body status=unavailable 且 detail 非空
    断言点: 状态码 503 + status=unavailable + detail 含错误信息
    防回归: 若异常分支漏 return JSONResponse，会冒 500
    """
    bad_engine = create_engine(f"sqlite:///{tmp_path / 'no_such_dir' / 'x.db'}")
    app.state.engine = bad_engine
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["detail"]


# --------------------------------------------------------------------------- #
# portal_gateway
# --------------------------------------------------------------------------- #
def test_portal_route_missing_prefix_raises(tmp_path):
    """TC-GW-031 | portal 路由缺 prefix 时抛 RuntimeError

    输入: dist 合法 + routes=[{"upstream": "..."}]（缺 prefix）
    预期输出: 抛 RuntimeError，消息含 prefix/upstream
    断言点: 异常类型 + 消息关键字
    防回归: 若路由校验被删，缺前缀路由会在反代时才出错
    """
    with pytest.raises(RuntimeError, match="prefix/upstream"):
        pg.create_app(_dist(tmp_path), [{"upstream": "http://127.0.0.1:1"}])


def test_portal_route_missing_upstream_raises(tmp_path):
    """TC-GW-032 | portal 路由缺 upstream 时抛 RuntimeError

    输入: dist 合法 + routes=[{"prefix": "/x/"}]（缺 upstream）
    预期输出: 抛 RuntimeError，消息含 prefix/upstream
    断言点: 异常类型 + 消息关键字
    防回归: 若校验只查 prefix 不查 upstream，缺 upstream 路由会构造非法反代地址
    """
    with pytest.raises(RuntimeError, match="prefix/upstream"):
        pg.create_app(_dist(tmp_path), [{"prefix": "/x/"}])


def test_portal_strip_prefix_proxies_stripped_path(tmp_path, upstream_url):
    """TC-GW-033 | portal 路由 stripPrefix 在反代前剥离前缀

    输入: route prefix=/api/orchestrate/ + stripPrefix=/api/orchestrate，GET /api/orchestrate/ping
    预期输出: 上游收到 path=/ping（已剥离前缀）
    断言点: 上游回显的 path == "/ping"
    防回归: 若 stripPrefix 逻辑错，上游收到原始 /api/orchestrate/ping
    """
    app = pg.create_app(
        _dist(tmp_path),
        [{"prefix": "/api/orchestrate/", "upstream": upstream_url, "stripPrefix": "/api/orchestrate"}],
    )
    client = TestClient(app)
    resp = client.get("/api/orchestrate/ping")
    assert resp.status_code == 200
    assert resp.json()["path"] == "/ping"


def test_portal_proxy_forwards_query_string(tmp_path, upstream_url):
    """TC-GW-034 | portal 反代透传 query string

    输入: route prefix=/api/orchestrate/，GET /api/orchestrate/echo?intent=x
    预期输出: 上游收到 query=intent=x 且 path=/api/orchestrate/echo
    断言点: 上游回显的 query == "intent=x" + path 不变
    防回归: 若漏拼 query_string，上游 query 为空
    """
    app = pg.create_app(_dist(tmp_path), [{"prefix": "/api/orchestrate/", "upstream": upstream_url}])
    client = TestClient(app)
    resp = client.get("/api/orchestrate/echo?intent=x")
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "intent=x"
    assert body["path"] == "/api/orchestrate/echo"


def test_mount_agent_reorders_before_default_route(iso_env, engine, isolated_settings):
    """TC-GW-035 | _mount_agent 把非默认挂载重排到已有 /debug/a2a 路由之前

    输入: create_app 后默认 /debug/a2a 已挂载，直接 _mount_agent 一个新启用 Agent
    预期输出: 新挂载 /debug/a2a/agent/<id> 出现且其路由顺序位于 /debug/a2a 之前
    断言点: 新 Agent 进入 agent_runtimes + 新挂载路由索引 < /debug/a2a 索引
    防回归: 若重排 match 分支（找到 /debug/a2a 后 break）丢失，新挂载会落在 /debug/a2a 之后
    """
    app = app_main.create_app(isolated_settings)
    with Session(engine) as session:
        extra = Agent(name="Reorder Agent", enabled=True, layer="service")
        session.add(extra)
        session.commit()
        session.refresh(extra)
        extra_id = extra.id
    app_main._mount_agent(app, extra, isolated_settings, app.state.flow_env)

    paths = [getattr(r, "path", None) for r in app.router.routes]
    assert extra_id in app.state.agent_runtimes
    assert f"/debug/a2a/agent/{extra_id}" in paths
    assert paths.index(f"/debug/a2a/agent/{extra_id}") < paths.index("/debug/a2a")
