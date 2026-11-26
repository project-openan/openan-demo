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

import asyncio
import json
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from openan_debug import standalone_agent, workflow_mode
from openan_debug.db import init_db, make_engine
from openan_debug.models import Agent, RequestLog, Variant


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_engine(settings):
    engine = make_engine(settings)
    init_db(engine, settings)
    return engine


@pytest.fixture(autouse=True)
def _clear_wf_cache():
    workflow_mode._WF_CACHE.clear()
    yield
    workflow_mode._WF_CACHE.clear()


# ---------------------------------------------------------------------------
# standalone_agent — resolve_define_path
# ---------------------------------------------------------------------------


def test_resolve_define_path_explicit(tmp_path):
    """TC-DGW-001 | 显式 --define 路径存在时直接返回该路径

    输入: explicit 指向一个已存在的文件
    预期输出: 返回该 Path 对象
    断言点: 返回值等于显式路径
    防回归: 若显式路径不再优先于环境变量/cwd 候选，本用例失败
    """
    f = tmp_path / "my_define.json"
    f.write_text("{}", encoding="utf-8")
    assert standalone_agent.resolve_define_path(str(f)) == f


def test_resolve_define_path_env_override(tmp_path, monkeypatch):
    """TC-DGW-002 | OPENAN_DEBUG_MOCK_DEFINE 环境变量作为候选路径

    输入: explicit=None，环境变量指向已存在文件
    预期输出: 返回环境变量指定路径
    断言点: 返回值等于环境变量路径
    防回归: 若环境变量候选被移除，本用例失败
    """
    env_file = tmp_path / "env_define.json"
    env_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("OPENAN_DEBUG_MOCK_DEFINE", str(env_file))
    assert standalone_agent.resolve_define_path(None) == env_file


def test_resolve_define_path_not_found(monkeypatch):
    """TC-DGW-003 | 所有候选路径均不存在时抛 SystemExit

    输入: explicit=None，无环境变量，DEFINE_FILENAME 改为不存在的名字使全部候选失效
    预期输出: 抛出 SystemExit，消息含 DEFINE_FILENAME
    断言点: 异常类型 + 消息关键字
    防回归: 若未找到时不再抛异常，本用例失败
    """
    monkeypatch.delenv("OPENAN_DEBUG_MOCK_DEFINE", raising=False)
    monkeypatch.setattr(standalone_agent, "DEFINE_FILENAME", "no_such_define_zzz.json")
    with pytest.raises(SystemExit, match="no_such_define_zzz"):
        standalone_agent.resolve_define_path(None)


# ---------------------------------------------------------------------------
# standalone_agent — merged_llm / merged_stub_variants
# ---------------------------------------------------------------------------


def test_merged_llm_instance_overrides_defaults():
    """TC-DGW-004 | instance.llm 覆盖 defaults.llm 同名字段

    输入: define.defaults.llm={provider, model}, instance.llm={model}
    预期输出: 合并后 provider 来自 defaults，model 来自 instance
    断言点: 返回 dict 的 provider 与 model 值
    防回归: 若合并方向反了（defaults 覆盖 instance），model 值不符
    """
    define = {"defaults": {"llm": {"provider": "openai", "model": "gpt-4"}}}
    instance = {"llm": {"model": "qwen"}}
    result = standalone_agent.merged_llm(instance, define)
    assert result == {"provider": "openai", "model": "qwen"}


def test_merged_llm_empty_when_no_keys():
    """TC-DGW-005 | 无 llm 配置时返回空 dict

    输入: define={}, instance={}
    预期输出: {}
    断言点: 返回值为空 dict
    防回归: 若默认 llm 被误注入非空值，本用例失败
    """
    assert standalone_agent.merged_llm({}, {}) == {}


def test_merged_stub_variants_own_then_baseline():
    """TC-DGW-006 | 实例桩在前、defaults 基线补齐去重

    输入: defaults.stubVariants 含模板 A/B，instance.stubVariants 含模板 A
    预期输出: 列表 = [instance A, baseline B]（baseline A 被去重）
    断言点: 长度=2，首元素为 instance A，次元素为 baseline B
    防回归: 若去重逻辑反了或顺序错了，本用例失败
    """
    define = {"defaults": {"stubVariants": [
        {"templateUri": "A/v1", "variantJson": {"b": 1}},
        {"templateUri": "B/v1", "variantJson": {"b": 2}},
    ]}}
    instance = {"stubVariants": [{"templateUri": "A/v1", "variantJson": {"o": 9}}]}
    result = standalone_agent.merged_stub_variants(instance, define)
    assert [r["templateUri"] for r in result] == ["A/v1", "B/v1"]
    assert result[0]["variantJson"] == {"o": 9}
    assert result[1]["variantJson"] == {"b": 2}


def test_merged_stub_variants_empty():
    """TC-DGW-007 | 无桩变体配置时返回空列表

    输入: define={}, instance={}
    预期输出: []
    断言点: 返回值为空列表
    防回归: 若 None 未被正确处理，本用例失败
    """
    assert standalone_agent.merged_stub_variants({}, {}) == []


# ---------------------------------------------------------------------------
# standalone_agent — write_llm_env
# ---------------------------------------------------------------------------


def test_write_llm_env_disabled_writes_fallback(tmp_path):
    """TC-DGW-008 | llm.enabled=false 时写入 FALLBACK_ENV

    输入: instance.llm.enabled=false, work_dir=tmp_path
    预期输出: work_dir/llm.env 内容等于 FALLBACK_ENV
    断言点: 文件内容完全匹配 FALLBACK_ENV
    防回归: 若 disabled 分支写入了非 fallback 内容，本用例失败
    """
    from openan_debug.agent.flow_env import FALLBACK_ENV

    instance = {"llm": {"enabled": False}}
    env_path = standalone_agent.write_llm_env(instance, {}, tmp_path)
    assert env_path == tmp_path / "llm.env"
    assert env_path.read_text(encoding="utf-8") == FALLBACK_ENV


def test_write_llm_env_enabled_writes_all_fields(tmp_path, monkeypatch):
    """TC-DGW-009 | llm.enabled=true 时写入完整环境变量

    输入: instance.llm 含 provider/model/apiKeyEnv/baseUrl/maxAttempts/language
    预期输出: llm.env 含全部 A2AT_LLM_* 字段，API key 取自环境变量
    断言点: 逐字段匹配（provider/model/api_key/base_url/max_attempts/language）
    防回归: 若任一字段缺失或取值错误，本用例失败
    """
    monkeypatch.setenv("MY_LLM_KEY", "secret-key-123")
    instance = {"llm": {
        "enabled": True, "provider": "azure", "model": "qwen-test",
        "apiKeyEnv": "MY_LLM_KEY", "baseUrl": "http://llm:8080/v1",
        "maxAttempts": "5", "language": "en",
    }}
    env_path = standalone_agent.write_llm_env(instance, {}, tmp_path)
    content = env_path.read_text(encoding="utf-8")
    assert "A2AT_LLM_PROVIDER=azure" in content
    assert "A2AT_LLM_MODEL=qwen-test" in content
    assert "A2AT_LLM_API_KEY=secret-key-123" in content
    assert "A2AT_LLM_BASE_URL=http://llm:8080/v1" in content
    assert "A2AT_LLM_MAX_ATTEMPTS=5" in content
    assert "A2AT_LANGUAGE=en" in content


# ---------------------------------------------------------------------------
# standalone_agent — _log_sink
# ---------------------------------------------------------------------------


def test_log_sink_persists_request_log(db_engine):
    """TC-DGW-010 | _log_sink 将 entry 写入 RequestLog 表

    输入: engine + entry dict（含 agent_id/template_uri/direction/task_state）
    预期输出: RequestLog 表新增一行，字段与 entry 一致
    断言点: 查询回读的 RequestLog 各字段值
    防回归: 若 _log_sink 未 commit 或字段映射错误，本用例失败
    """
    entry = {
        "agent_id": 1,
        "template_uri": "Task-T/test/v1",
        "direction": "inbound",
        "task_state": "TASK_STATE_COMPLETED",
        "latency_ms": 42,
    }
    asyncio.run(standalone_agent._log_sink(db_engine, entry))
    with Session(db_engine) as session:
        log = session.scalar(
            select(RequestLog).where(RequestLog.template_uri == "Task-T/test/v1")
        )
    assert log is not None
    assert log.direction == "inbound"
    assert log.task_state == "TASK_STATE_COMPLETED"
    assert log.latency_ms == 42


# ---------------------------------------------------------------------------
# standalone_agent — ensure_agent
# ---------------------------------------------------------------------------


def test_ensure_agent_creates_new(db_engine):
    """TC-DGW-011 | 新 Agent 行被创建并返回 id

    输入: instance 含新 organization/name，session 中无匹配
    预期输出: 返回新 agent id，DB 中存在该 Agent 行
    断言点: agent_id>0，回读 Agent 的 name/organization/description/layer/enabled
    防回归: 若创建逻辑被删或字段映射错，本用例失败
    """
    instance = {
        "organization": "TestOrg", "agentName": "NewAgent",
        "description": "desc", "layer": "network", "networkDomain": "wireless",
    }
    with Session(db_engine) as session:
        agent_id = standalone_agent.ensure_agent(session, instance)
        assert agent_id > 0
        agent = session.get(Agent, agent_id)
        assert agent.name == "NewAgent"
        assert agent.organization == "TestOrg"
        assert agent.description == "desc"
        assert agent.layer == "network"
        assert agent.network_domain == "wireless"
        assert agent.enabled is True


def test_ensure_agent_reenables_disabled(db_engine):
    """TC-DGW-012 | 已存在但 disabled 的 Agent 被重新启用

    输入: 先 disable 默认 Agent，再以同名调用 ensure_agent
    预期输出: 返回同一 id，Agent.enabled 变为 True
    断言点: agent_id 不变且 enabled=True
    防回归: 若 re-enable 分支被删，enabled 仍为 False
    """
    with Session(db_engine) as session:
        agent = session.scalar(select(Agent).where(Agent.organization == "OpenAN"))
        agent.enabled = False
        session.commit()
        disabled_id = agent.id
        instance = {"organization": "OpenAN", "name": "OpenAN Debug Mock Agent"}
        result_id = standalone_agent.ensure_agent(session, instance)
        session.refresh(agent)
    assert result_id == disabled_id
    assert agent.enabled is True


def test_ensure_agent_existing_enabled_returns_same_id(db_engine):
    """TC-DGW-013 | 已存在且 enabled 的 Agent 直接返回 id（不修改）

    输入: 以默认 Agent 同名调用 ensure_agent
    预期输出: 返回同一 id
    断言点: 返回 id 等于已有 Agent id
    防回归: 若已存在分支被误改为创建新行，id 不符
    """
    with Session(db_engine) as session:
        agent = session.scalar(select(Agent).where(Agent.organization == "OpenAN"))
        existing_id = agent.id
        instance = {"organization": "OpenAN", "name": "OpenAN Debug Mock Agent"}
        result_id = standalone_agent.ensure_agent(session, instance)
    assert result_id == existing_id


# ---------------------------------------------------------------------------
# standalone_agent — ensure_stub_variants
# ---------------------------------------------------------------------------


def test_ensure_stub_variants_empty_returns_zero(db_engine):
    """TC-DGW-014 | 空列表/None 时返回 0 且不写入

    输入: stub_variants=[] 或 None
    预期输出: 返回 0
    断言点: 返回值为 0
    防回归: 若空列表被误处理为创建变体，本用例失败
    """
    with Session(db_engine) as session:
        agent = session.scalar(select(Agent).limit(1))
        assert standalone_agent.ensure_stub_variants(session, agent.id, []) == 0
        assert standalone_agent.ensure_stub_variants(session, agent.id, None) == 0


def test_ensure_stub_variants_creates_new(db_engine):
    """TC-DGW-015 | 新模板变体被创建，source=mock_define，enabled=True

    输入: 两个不同模板的桩变体
    预期输出: 返回 2，DB 中有两条 Variant 行
    断言点: count=2，回读 Variant 的 template_uri/variant_json/source/enabled
    防回归: 若创建逻辑或字段映射错误，本用例失败
    """
    stubs = [
        {"templateUri": "Task-T/new-a/v1", "variantJson": {"a": 1}},
        {"templateUri": "Task-T/new-b/v1", "variantJson": {"b": 2}},
    ]
    with Session(db_engine) as session:
        agent = session.scalar(select(Agent).limit(1))
        count = standalone_agent.ensure_stub_variants(session, agent.id, stubs)
        assert count == 2
        variants = session.scalars(
            select(Variant).where(Variant.agent_id == agent.id)
        ).all()
        uris = {v.template_uri for v in variants}
        assert uris == {"Task-T/new-a/v1", "Task-T/new-b/v1"}
        va = next(v for v in variants if v.template_uri == "Task-T/new-a/v1")
        assert va.variant_json == {"a": 1}
        assert va.source == "mock_define"
        assert va.enabled is True


def test_ensure_stub_variants_skips_existing_template(db_engine):
    """TC-DGW-016 | 已有模板的变体被跳过（不重复创建）

    输入: 先创建模板 A 的变体，再以同一模板调用 ensure_stub_variants
    预期输出: 第二次返回 0，DB 中模板 A 仍只有一条
    断言点: 第二次 count=0，Variant 行数不变
    防回归: 若去重逻辑失效，会创建重复行
    """
    with Session(db_engine) as session:
        agent = session.scalar(select(Agent).limit(1))
        standalone_agent.ensure_stub_variants(session, agent.id, [
            {"templateUri": "Task-T/skip/v1", "variantJson": {"x": 1}},
        ])
        count = standalone_agent.ensure_stub_variants(session, agent.id, [
            {"templateUri": "Task-T/skip/v1", "variantJson": {"x": 999}},
        ])
        assert count == 0
        variants = session.scalars(
            select(Variant).where(
                Variant.agent_id == agent.id, Variant.template_uri == "Task-T/skip/v1"
            )
        ).all()
        assert len(variants) == 1
        assert variants[0].variant_json == {"x": 1}


def test_ensure_stub_variants_seq_increment_same_template(db_engine):
    """TC-DGW-017 | 同模板多条变体 seq 递增（0,1,...）

    输入: 同模板两个变体
    预期输出: 两条 Variant，seq 分别为 0 和 1
    断言点: seq 值依次为 0/1，variant_json 各自正确
    防回归: 若 seq 计数逻辑错误，seq 值不符
    """
    stubs = [
        {"templateUri": "Task-T/seq/v1", "variantJson": {"k": "first"}},
        {"templateUri": "Task-T/seq/v1", "variantJson": {"k": "second"}},
    ]
    with Session(db_engine) as session:
        agent = session.scalar(select(Agent).limit(1))
        count = standalone_agent.ensure_stub_variants(session, agent.id, stubs)
        assert count == 2
        variants = session.scalars(
            select(Variant).where(
                Variant.agent_id == agent.id, Variant.template_uri == "Task-T/seq/v1"
            ).order_by(Variant.seq)
        ).all()
        assert len(variants) == 2
        assert variants[0].seq == 0
        assert variants[1].seq == 1
        assert variants[0].variant_json == {"k": "first"}
        assert variants[1].variant_json == {"k": "second"}


# ---------------------------------------------------------------------------
# standalone_agent — build_runner_app
# ---------------------------------------------------------------------------


def test_build_runner_app_health_endpoint(settings, tmp_path):
    """TC-DGW-018 | build_runner_app 构建 FastAPI，/health 返回正确状态

    输入: instance(llm disabled) + define + settings
    预期输出: FastAPI app，/health 与 /api/v1/health 均返回 200 + ok
    断言点: HTTP 200，body.status=ok，body.llm=stub-fallback，body.instance=id
    防回归: 若 app 构建或 health 端点注册错误，本用例失败
    """
    work_dir = tmp_path / "runner-work"
    instance = {
        "id": "runner-1", "name": "Runner Agent", "description": "runner test",
        "workDir": str(work_dir), "port": 9399,
    }
    define = {"defaults": {"publicUrlBase": "http://127.0.0.1", "llm": {"enabled": False}}}
    app = standalone_agent.build_runner_app(instance, define, settings)
    assert app.title == "Mock Agent · Runner Agent"
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["instance"] == "runner-1"
        assert body["llm"] == "stub-fallback"
        assert body["agentId"] > 0
        resp2 = client.get("/api/v1/health")
        assert resp2.status_code == 200
    assert app.state.mock_instance["id"] == "runner-1"
    assert (work_dir / "llm.env").exists()


def test_build_runner_app_workflow_enabled(settings, tmp_path, monkeypatch):
    """TC-DGW-019 | workflow.enabled=true 时加载工作流并生成 agent cards

    输入: instance 含 workflow.enabled=true，monkeypatch load_builtin 返回 dict
    预期输出: app 构建成功，agent_cards_for 被调用
    断言点: app.title 正确，health 端点 200
    防回归: 若 workflow 分支未触发，本用例失败
    """
    work_dir = tmp_path / "wf-work"
    instance = {
        "id": "wf-1", "name": "WF Agent", "description": "wf test",
        "workDir": str(work_dir), "port": 9399,
        "workflow": {"enabled": True, "workflowId": "live-assurance-demo"},
    }
    define = {"defaults": {"publicUrlBase": "http://127.0.0.1", "llm": {"enabled": False}}}
    fake_wf = {"steps": [{"name": "s1", "subtasks": [{"agent": "A"}]}]}
    fake_cards = [{"name": "A", "description": "card"}]
    monkeypatch.setattr(standalone_agent.workflow_mode, "load_builtin", lambda wid: fake_wf)
    monkeypatch.setattr(standalone_agent.workflow_mode, "agent_cards_for", lambda wf, d: fake_cards)
    app = standalone_agent.build_runner_app(instance, define, settings)
    assert app.title == "Mock Agent · WF Agent"
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_build_runner_app_workflow_definition_not_found(settings, tmp_path, monkeypatch):
    """TC-DGW-020 | workflow.enabled=true 但 load_builtin 返回 None 时 cards 为空

    输入: instance 含 workflow.enabled=true，monkeypatch load_builtin 返回 None
    预期输出: app 构建成功（workflow_cards=[]）
    断言点: health 端点 200
    防回归: 若 workflow_dict 为 None 时未跳过 agent_cards_for，本用例失败
    """
    work_dir = tmp_path / "wf-none-work"
    instance = {
        "id": "wf-none", "name": "WF None Agent", "description": "test",
        "workDir": str(work_dir), "port": 9399,
        "workflow": {"enabled": True, "workflowId": "missing"},
    }
    define = {"defaults": {"publicUrlBase": "http://127.0.0.1", "llm": {"enabled": False}}}
    monkeypatch.setattr(standalone_agent.workflow_mode, "load_builtin", lambda wid: None)
    app = standalone_agent.build_runner_app(instance, define, settings)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# standalone_agent — main()
# ---------------------------------------------------------------------------


def test_main_orchestration_happy_path(settings, tmp_path, monkeypatch):
    """TC-DGW-021 | main() 完整编排：解析参数→加载 define→构建 app→uvicorn.run(stubbed)

    输入: 合法 define 文件 + --define/--instance，uvicorn.run 被 stub 为 no-op
    预期输出: main() 正常返回，pid 文件被清理
    断言点: work_dir/llm.env 存在，instance.pid 不存在（finally 清理）
    防回归: 若 main 编排逻辑或 finally 清理被破坏，本用例失败
    """
    work_dir = tmp_path / "main-work"
    define = {
        "defaults": {"host": "127.0.0.1", "publicUrlBase": "http://127.0.0.1", "llm": {"enabled": False}},
        "instances": [
            {"id": "main-1", "name": "Main Agent", "description": "main test",
             "workDir": str(work_dir), "port": 9399},
        ],
    }
    define_file = tmp_path / "define.json"
    define_file.write_text(json.dumps(define), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "standalone_agent", "--define", str(define_file),
        "--instance", "main-1", "--host", "127.0.0.1", "--port", "9399",
    ])
    monkeypatch.setattr(standalone_agent, "load_settings", lambda: settings)
    monkeypatch.setattr(standalone_agent.uvicorn, "run", lambda *a, **kw: None)
    standalone_agent.main()
    assert (work_dir / "llm.env").exists()
    assert not (work_dir / "instance.pid").exists()


def test_main_uses_instance_defaults(settings, tmp_path, monkeypatch):
    """TC-DGW-022 | main() 无 --host/--port 时回退到 instance/defaults

    输入: define 含 defaults.host 和 instance.port，不传 --host/--port
    预期输出: main() 正常返回（uvicorn.run stubbed）
    断言点: main() 不抛异常，pid 文件被清理
    防回归: 若 host/port 回退逻辑被破坏，本用例失败
    """
    work_dir = tmp_path / "main-defaults-work"
    define = {
        "defaults": {"host": "0.0.0.0", "publicUrlBase": "http://127.0.0.1", "llm": {"enabled": False}},
        "instances": [
            {"id": "main-2", "name": "Main Agent 2", "description": "test",
             "workDir": str(work_dir), "port": 9400, "host": "127.0.0.1"},
        ],
    }
    define_file = tmp_path / "define2.json"
    define_file.write_text(json.dumps(define), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "standalone_agent", "--define", str(define_file), "--instance", "main-2",
    ])
    monkeypatch.setattr(standalone_agent, "load_settings", lambda: settings)
    monkeypatch.setattr(standalone_agent.uvicorn, "run", lambda *a, **kw: None)
    standalone_agent.main()
    assert not (work_dir / "instance.pid").exists()


def test_main_instance_not_found_raises_systemexit(tmp_path, monkeypatch):
    """TC-DGW-023 | main() 中 instance id 不在 define 时抛 SystemExit

    输入: define 不含请求的 instance id
    预期输出: 抛出 SystemExit，消息含 instance id
    断言点: 异常类型 + 消息匹配 instance id
    防回归: 若未找到实例时不再抛异常，本用例失败
    """
    define = {"instances": [{"id": "other", "name": "Other"}]}
    define_file = tmp_path / "define_missing.json"
    define_file.write_text(json.dumps(define), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "standalone_agent", "--define", str(define_file), "--instance", "ghost",
    ])
    with pytest.raises(SystemExit, match="ghost"):
        standalone_agent.main()
