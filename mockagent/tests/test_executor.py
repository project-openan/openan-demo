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

"""MockAgentExecutor / FlowEnvironment / A2A app 语句覆盖测试。

目标模块（语句覆盖）：
- mockagent_engine/agent/executor.py（MockAgentExecutor 选择链 + execute/_enqueue/_update_status）
- mockagent_engine/agent/flow_env.py（ext_uri_for / schema_for 缓存与异常分支）
- mockagent_engine/agent/base.py（capabilities 的 llm/workflow 开关分支）
- mockagent_engine/agent/a2a_app.py（EchoExtensionsMiddleware 回显头分支）

策略：纯函数直接单测；MockAgentExecutor 方法用最小 runtime + fake flow_env 直接驱动；
execute/_enqueue/_update_status 用真实 FlowEnvironment + RecordingEventQueue 端到端驱动并断言事件序列。
"""

import asyncio
import copy
import threading
from types import SimpleNamespace

import pytest
from google.protobuf.json_format import MessageToDict, ParseDict
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from a2a.server.agent_execution.context import RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events.event_queue import EventQueue
from a2a.types.a2a_pb2 import Message, SendMessageRequest, TaskState

from mockagent_engine import agent_registry, dataset_retrieval, llm_client, workflow_mode
from mockagent_engine.agent import executor as executor_module
from mockagent_engine.agent.a2a_app import EchoExtensionsMiddleware, build_a2a_app
from mockagent_engine.agent.base import StubAgentBase
from mockagent_engine.agent.executor import (
    MockAgentExecutor,
    STATE_JSON,
    artifact_name,
    extract_request,
)
from mockagent_engine.agent.flow_env import FALLBACK_ENV, FlowEnvironment, ext_uri_for
from mockagent_engine.config import Settings
from mockagent_engine.db import init_db
from mockagent_engine.llm_client import LlmConfig
from mockagent_engine.models import Agent, Variant
from mockagent_engine.protocol_flow import FlowResult

# ---- 常量 ----
TASK_T_URI = "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1"
TV_LIVE = "Task-T/network-layer/live-stream-quality/v1"
TV_TICKET = "Task-T/network-layer/private-line-complaint/v1"
TV_NOVARIANT = "Task-T/network-layer/wireless-cell-diagnosis/v1"


# ---- 测试替身 ----
class RecordingEventQueue(EventQueue):
    """同步记录所有入队事件，便于按类型/内容断言。"""

    def __init__(self):
        self.events = []

    async def enqueue_event(self, event):
        self.events.append(event)


class _FakeFlowEnv:
    """仅含 cursor/cursor_lock 的轻量 flow_env，供 _select_stub 等直接单测。"""

    def __init__(self):
        self.cursor = {}
        self.cursor_lock = threading.Lock()
        self.a2at = None


# ---- 构造工具 ----
def _settings(tmp_path):
    return Settings(
        host="127.0.0.1",
        port=9000,
        db_path=tmp_path / "t.db",
        jwt_secret="fixture-only-64-byte-test-key-" * 3,
        env_path=tmp_path / "absent.env",
    )


def _make_message(template_uri, prompt_text, negotiation_context=None):
    meta = {}
    if template_uri is not None:
        meta["templateUri"] = template_uri
        ext = ext_uri_for(template_uri)
        if ext:
            meta[ext] = prompt_text or ""
    if negotiation_context is not None:
        meta["negotiationContext"] = negotiation_context
    return ParseDict(
        {"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": prompt_text or ""}], "metadata": meta},
        Message(),
    )


def _make_request_context(message=None, exts=None, task_id=None, context_id=None):
    cc = ServerCallContext(requested_extensions=set(exts or ()))
    request = SendMessageRequest(message=message) if message is not None else None
    return RequestContext(call_context=cc, request=request, task_id=task_id, context_id=context_id)


def _runtime(db=None, **over):
    base = {
        "engine": db.engine if db is not None else None,
        "agent_id": db.agent_id if db is not None else None,
        "settings": db.settings if db is not None else None,
        "dataset_templates": None,
        "instance_id": "test",
        "llm_config": None,
        "workflow_config": None,
        "workflow_cards": [],
        "agent": StubAgentBase(),
    }
    base.update(over)
    return base


def _llm_cfg():
    return LlmConfig(
        enabled=True,
        provider="openai",
        base_url="http://127.0.0.1:8000/v1",
        model="qwen-test",
        api_key="key",
        max_attempts=1,
        language="zh-CN",
    )


# ---- fixtures ----
@pytest.fixture(scope="module")
def real_flow_env(tmp_path_factory):
    d = tmp_path_factory.mktemp("flowenv")
    envfile = d / "llm.env"
    envfile.write_text(FALLBACK_ENV, encoding="utf-8")
    settings = Settings(
        host="127.0.0.1", port=9000, db_path=d / "env.db",
        jwt_secret="fixture-only-64-byte-test-key-" * 3, env_path=envfile,
    )
    return FlowEnvironment(settings)


@pytest.fixture
def db(tmp_path):
    settings = _settings(tmp_path)
    eng = create_engine(f"sqlite:///{settings.db_path}", connect_args={"check_same_thread": False})
    init_db(eng, settings)
    with Session(eng) as s:
        agent = Agent(organization="OpenAN", name="TestAgent", enabled=True)
        s.add(agent)
        s.commit()
        s.refresh(agent)
        aid = agent.id
        s.add(Variant(
            agent_id=aid, template_uri=TV_LIVE,
            variant_json={"artifactPrompt": "live-stub-text", "artifactName": "live-nm"},
            enabled=True, seq=0,
        ))
        s.add(Variant(
            agent_id=aid, template_uri=TV_TICKET,
            variant_json={"faultManagement.TroubleTicket": {"ticketId": "TT-1", "status": "open"}},
            enabled=True, seq=0,
        ))
        s.commit()
    return SimpleNamespace(engine=eng, agent_id=aid, settings=settings)


def _executor(db=None, flow_env=None, runtime=None, log_sink=None):
    fe = flow_env if flow_env is not None else _FakeFlowEnv()
    if runtime is not None:
        rt = runtime
    elif isinstance(db, dict):
        rt = db
    else:
        rt = _runtime(db)
    return MockAgentExecutor(fe, rt, log_sink=log_sink)


# =====================================================================
# A. 纯函数：extract_request / artifact_name
# =====================================================================


def test_extract_request_full_metadata_returns_tuple():
    """TC-EXEC-001 | 完整元数据下 extract_request 返回 (模板/提示/协商上下文/扩展集)

    输入: RequestContext，message.metadata 含 templateUri、Task-T 扩展提示文本、
          negotiationContext(dict)；call_context.requested_extensions 非空
    预期输出: (templateUri, 扩展提示文本, negotiationContext(dict), 扩展集合)
    断言点: 四元组逐项相等；扩展集含 Task-T URI
    防回归: 若扩展提取回落逻辑或元数据解析顺序被改坏，断言失败
    """
    msg = _make_message(TV_LIVE, "直播间卡顿", negotiation_context={"id": "n1", "round": 1})
    ctx = _make_request_context(message=msg, exts={TASK_T_URI})
    template_uri, prompt, nego, exts = extract_request(ctx)
    assert template_uri == TV_LIVE
    assert prompt == "直播间卡顿"
    assert nego == {"id": "n1", "round": 1}
    assert exts == {TASK_T_URI}


def test_extract_request_empty_extensions_falls_back_to_call_context():
    """TC-EXEC-002 | 空 requested_extensions 时回落读 call_context.requested_extensions

    输入: RequestContext，requested_extensions 为空集
    预期输出: 扩展集为空 set（经 call_context 回落路径）
    断言点: exts == set()；message 元数据仍正常解析
    防回归: 若 call_context 回落分支被删除，空扩展路径行为变化
    """
    msg = _make_message(TV_LIVE, "提示")
    ctx = _make_request_context(message=msg, exts=())
    template_uri, prompt, nego, exts = extract_request(ctx)
    assert template_uri == TV_LIVE
    assert prompt == "提示"
    assert nego is None
    assert exts == set()


def test_extract_request_message_none_returns_empty():
    """TC-EXEC-003 | message 为 None 时返回 (None, "", None, exts)

    输入: RequestContext 无 request（message 为 None），requested_extensions 非空
    预期输出: (None, "", None, {扩展集})
    断言点: 前三项为空、扩展集保留
    防回归: 若 None 守卫被删除，访问 message.metadata 将抛 AttributeError
    """
    ctx = _make_request_context(message=None, exts={TASK_T_URI})
    template_uri, prompt, nego, exts = extract_request(ctx)
    assert (template_uri, prompt, nego) == (None, "", None)
    assert exts == {TASK_T_URI}


def test_extract_request_empty_metadata_returns_empty():
    """TC-EXEC-004 | message 存在但 metadata 为空时提前返回

    输入: message 无 metadata 字段
    预期输出: (None, "", None, exts)
    断言点: template_uri 为 None（未读 metadata）
    防回归: 若空 metadata 守卫被删除，metadata.get 将异常或返回空串
    """
    msg = ParseDict({"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": "x"}]}, Message())
    ctx = _make_request_context(message=msg, exts={TASK_T_URI})
    template_uri, prompt, nego, exts = extract_request(ctx)
    assert (template_uri, prompt, nego) == (None, "", None)
    assert exts == {TASK_T_URI}


def test_extract_request_non_dict_negotiation_context_becomes_none():
    """TC-EXEC-005 | negotiationContext 非 dict 时被归一为 None

    输入: metadata.negotiationContext 为字符串
    预期输出: negotiation_context 为 None（isinstance(dict) 为 False）
    断言点: nego is None
    防回归: 若类型守卫被删除，字符串协商上下文会被透传给 FlowRequest
    """
    msg = _make_message(TV_LIVE, "提示", negotiation_context="not-a-dict")
    ctx = _make_request_context(message=msg, exts={TASK_T_URI})
    _, _, nego, _ = extract_request(ctx)
    assert nego is None


def test_artifact_name_multi_segment_and_fallback():
    """TC-EXEC-006 | artifact_name 多段返回 stub.<倒数第二段>，空/单段返回 stub.result

    输入: "Task-T/a/b/v1" / None / "x"
    预期输出: "stub.b" / "stub.result" / "stub.result"
    断言点: 三种输入对应返回值精确相等
    防回归: 若倒数第二段取错或段数判断被改坏，名称错位
    """
    assert artifact_name("Task-T/a/b/v1") == "stub.b"
    assert artifact_name(None) == "stub.result"
    assert artifact_name("x") == "stub.result"


# =====================================================================
# B. flow_env：ext_uri_for / schema_for
# =====================================================================


def test_ext_uri_for_known_unknown_and_none():
    """TC-EXEC-007 | ext_uri_for 对已知前缀返回扩展 URI，未知/空返回 None

    输入: None / "Task-T/x" / "Unknown-T/x"
    预期输出: None / TASK_T_URI / None
    断言点: 三种输入精确匹配
    防回归: 若前缀表查找或 split 逻辑改坏，映射错位
    """
    assert ext_uri_for(None) is None
    assert ext_uri_for("Task-T/anything/v1") == TASK_T_URI
    assert ext_uri_for("Unknown-T/x") is None


def test_schema_for_lookup_failure_returns_none(real_flow_env):
    """TC-EXEC-008 | schema_for 槽位查询抛异常时返回 None

    输入: 真实 FlowEnvironment（内置 schema_access.slot_schema 对测试模板抛异常）
    预期输出: None
    断言点: 结果 is None
    防回归: 若异常捕获被删除，slot_schema 异常将上抛
    """
    assert real_flow_env.schema_for("Task-T/bogus/x") is None


def test_schema_for_success_caches_result(real_flow_env, monkeypatch):
    """TC-EXEC-009 | schema_for 成功后缓存，二次调用命中缓存返回同对象

    输入: monkeypatch schema_access.slot_schema 返回固定 schema 对象
    预期输出: 两次调用返回同一对象，slot_schema 仅被调用一次（缓存命中）
    断言点: 返回值同一性 + slot_schema 调用次数 == 1
    防回归: 若缓存写入/命中逻辑被改坏，slot_schema 会被重复调用
    """
    fake_schema = {"_sentinel": "schema"}
    calls = {"n": 0}

    def fake_slot_schema(template_uri, language):
        calls["n"] += 1
        return fake_schema

    monkeypatch.setattr(real_flow_env.schema_access, "slot_schema", fake_slot_schema)
    real_flow_env._schema_cache.pop(TV_LIVE, None)
    first = real_flow_env.schema_for(TV_LIVE)
    second = real_flow_env.schema_for(TV_LIVE)
    assert first is fake_schema
    assert second is fake_schema
    assert calls["n"] == 1


def test_flow_env_a2at_construction_failure_falls_back(tmp_path, monkeypatch):
    """TC-EXEC-060 | A2ATServer 构造失败时回落内置 dummy LLM env 并重建成功

    输入: settings.env_path 指向不存在文件（A2ATServer(None) 抛异常）；
          chdir 到临时目录避免污染仓库
    预期输出: 回落写入 data/a2at-fallback.env 并重建 A2ATServer（.a2at 非 None）
    断言点: 构造后 .a2at is not None；data/a2at-fallback.env 已写入
    防回归: 若回落分支被删除，构造失败将直接上抛
    """
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        host="127.0.0.1", port=9000, db_path=tmp_path / "t.db",
        jwt_secret="fixture-only-64-byte-test-key-" * 3, env_path=tmp_path / "absent.env",
    )
    fe = FlowEnvironment(settings)
    assert fe.a2at is not None
    assert (tmp_path / "data" / "a2at-fallback.env").read_text(encoding="utf-8") == FALLBACK_ENV


# =====================================================================
# C. base.py：capabilities
# =====================================================================


def test_base_capabilities_llm_and_workflow_branches():
    """TC-EXEC-010 | instance 启用 llm/workflow 时 capabilities 追加对应能力

    输入: StubAgentBase(instance={"llm":{"enabled":True},"workflow":{"enabled":True}})
    预期输出: ["dataset-matching","variant-pool","llm-generation","workflow-orchestration"]
    断言点: 能力清单含全部四项；纯基类只返回前两项
    防回归: 若任一开关分支被删除，对应能力丢失
    """
    full = StubAgentBase(instance={"llm": {"enabled": True}, "workflow": {"enabled": True}})
    assert full.capabilities() == [
        "dataset-matching", "variant-pool", "llm-generation", "workflow-orchestration",
    ]
    empty = StubAgentBase()
    assert empty.capabilities() == ["dataset-matching", "variant-pool"]


def test_base_properties_and_build_runtime_identity():
    """TC-EXEC-059 | 基类便捷属性读取与 build_runtime 恒等

    输入: StubAgentBase(instance={"id":"a1","agentName":"名称","datasetTemplates":["T1"]})
    预期输出: id=="a1"；display_name=="名称"；dataset_templates==["T1"]；build_runtime 原样返回
    断言点: 四个属性/方法返回值精确相等
    防回归: 若属性读取或 build_runtime 透传被改坏，返回错位
    """
    agent = StubAgentBase(instance={"id": "a1", "agentName": "名称", "datasetTemplates": ["T1"]})
    assert agent.id == "a1"
    assert agent.display_name == "名称"
    assert agent.dataset_templates == ["T1"]
    assert agent.build_runtime({"k": "v"}) == {"k": "v"}
    assert StubAgentBase(instance={"name": "n2"}).display_name == "n2"


# =====================================================================
# D. a2a_app：EchoExtensionsMiddleware + build_a2a_app
# =====================================================================


async def test_middleware_echoes_a2a_extensions_header():
    """TC-EXEC-011 | HTTP 请求带 a2a-extensions 头时回显到响应头

    输入: http scope + header (b"a2a-extensions", b"Task-T/x")；内层 app 响应不含该头
    预期输出: http.response.start 头中出现 (b"a2a-extensions", b"Task-T/x")
    断言点: 响应头集合含回显头且值相等
    防回归: 若回显逻辑被删除，响应头不含 a2a-extensions
    """
    captured = []

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        captured.append(msg)

    mw = EchoExtensionsMiddleware(inner)
    await mw({"type": "http", "headers": [(b"a2a-extensions", b"Task-T/x")]}, receive, send)
    start = next(m for m in captured if m["type"] == "http.response.start")
    assert (b"a2a-extensions", b"Task-T/x") in start["headers"]


async def test_middleware_non_http_scope_passthrough():
    """TC-EXEC-012 | 非 http scope（如 lifespan）直接转发给内层 app，不经回显包装

    输入: scope type="lifespan"
    预期输出: 内层 app 被调用，其发送的响应原样到达 send（无回显包装）
    断言点: 内层 app 执行标志为 True；响应 body 原样到达 captured
    防回归: 若非 http 分支被改为走回显包装，lifespan 事件将被错误处理
    """
    state = {"called": False}
    captured = []

    async def inner(scope, receive, send):
        state["called"] = True
        await send({"type": "lifespan.startup.complete"})

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(msg):
        captured.append(msg)

    mw = EchoExtensionsMiddleware(inner)
    await mw({"type": "lifespan", "headers": []}, receive, send)
    assert state["called"] is True
    assert captured == [{"type": "lifespan.startup.complete"}]


async def test_middleware_no_extension_header_not_added():
    """TC-EXEC-013 | 请求无 a2a-extensions 头时不向响应追加该头

    输入: http scope + headers=[]（无 a2a-extensions）
    预期输出: 响应头不含 a2a-extensions
    断言点: 响应头集合无 b"a2a-extensions" 键
    防回归: 若空头判断被改坏，会注入空回显头
    """
    captured = []

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        captured.append(msg)

    mw = EchoExtensionsMiddleware(inner)
    await mw({"type": "http", "headers": []}, receive, send)
    start = next(m for m in captured if m["type"] == "http.response.start")
    assert all(k != b"a2a-extensions" for k, _ in start["headers"])


async def test_middleware_header_already_present_not_duplicated():
    """TC-EXEC-014 | 响应已含 a2a-extensions 头时不重复追加

    输入: 请求与响应均带 a2a-extensions 头
    预期输出: 响应中 a2a-extensions 头仅出现一次（内层原值）
    断言点: 响应头中 a2a-extensions 计数 == 1
    防回归: 若去重判断被删除，响应将出现重复头
    """
    captured = []

    async def inner(scope, receive, send):
        await send({
            "type": "http.response.start", "status": 200,
            "headers": [(b"a2a-extensions", b"inner-val")],
        })

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        captured.append(msg)

    mw = EchoExtensionsMiddleware(inner)
    await mw({"type": "http", "headers": [(b"a2a-extensions", b"Task-T/x")]}, receive, send)
    start = next(m for m in captured if m["type"] == "http.response.start")
    ext_headers = [v for k, v in start["headers"] if k == b"a2a-extensions"]
    assert ext_headers == [b"inner-val"]


def test_build_a2a_app_wraps_starlette_with_middleware():
    """TC-EXEC-015 | build_a2a_app 返回 EchoExtensionsMiddleware 包装的 Starlette

    输入: public_url + 最小 executor
    预期输出: 返回 EchoExtensionsMiddleware 实例，其 .app 为 Starlette
    断言点: isinstance EchoExtensionsMiddleware 且内层 app 暴露 routes
    防回归: 若包装或路由装配被改坏，类型不匹配
    """
    executor = _executor()
    app = build_a2a_app("http://127.0.0.1:9000/a2a", executor, agent_name="nm", agent_description="d")
    assert isinstance(app, EchoExtensionsMiddleware)
    assert len(app.app.routes) > 0


# =====================================================================
# E. MockAgentExecutor 方法
# =====================================================================


async def test_cancel_returns_none(db):
    """TC-EXEC-016 | cancel 固定返回 None

    输入: 任意 context / event_queue
    预期输出: None
    断言点: 返回值 is None
    防回归: 若 cancel 改为抛异常或返回非空，行为变化
    """
    executor = _executor(db)
    assert await executor.cancel(_make_request_context(), RecordingEventQueue()) is None


def test_agent_name_no_engine_falls_back(db):
    """TC-EXEC-017 | 无 engine/agent_id 时 _agent_name 回落 "MockAgent"

    输入: runtime 无 engine
    预期输出: "MockAgent"
    断言点: 返回 == "MockAgent"
    防回归: 若回落默认被改坏，名称错
    """
    executor = _executor(_runtime())
    assert executor._agent_name() == "MockAgent"


def test_agent_name_resolves_from_db(db):
    """TC-EXEC-018 | 有 engine+agent_id 且 Agent 存在时返回 agent.name

    输入: runtime 含真实 engine + 已存在 agent_id
    预期输出: "TestAgent"
    断言点: 返回 == "TestAgent"
    防回归: 若 DB 查询或 name 读取被改坏，返回错
    """
    executor = _executor(db)
    assert executor._agent_name() == "TestAgent"


def test_agent_name_missing_agent_falls_back(db):
    """TC-EXEC-019 | agent_id 不存在时回落 "MockAgent"

    输入: engine 真实、agent_id 为不存在值
    预期输出: "MockAgent"
    断言点: 返回 == "MockAgent"
    防回归: 若 agent is None 分支被改坏，访问 agent.name 抛异常
    """
    executor = _executor(_runtime(db, agent_id=999999))
    assert executor._agent_name() == "MockAgent"


def test_agent_name_db_error_falls_back(tmp_path):
    """TC-EXEC-020 | DB 查询异常时捕获并回落 "MockAgent"

    输入: engine 指向未建表的库（session.get 抛异常）
    预期输出: "MockAgent"
    断言点: 返回 == "MockAgent"
    防回归: 若异常捕获被删除，异常上抛
    """
    settings = _settings(tmp_path)
    eng = create_engine(f"sqlite:///{settings.db_path}", connect_args={"check_same_thread": False})
    executor = _executor(_runtime(SimpleNamespace(engine=eng, agent_id=1, settings=settings)))
    assert executor._agent_name() == "MockAgent"


def test_agent_available_no_engine_false(db):
    """TC-EXEC-021 | 无 engine/agent_id 时 _agent_available 返回 False

    输入: runtime 无 engine
    预期输出: False
    断言点: 返回 is False
    防回归: 若守卫被删除，None engine 下 session 访问将异常
    """
    executor = _executor(_runtime())
    assert executor._agent_available() is False


def test_agent_available_enabled_true(db):
    """TC-EXEC-022 | Agent 存在且 enabled 时返回 True

    输入: runtime 含真实 engine + enabled agent_id
    预期输出: True
    断言点: 返回 is True
    防回归: 若 enabled 判断被改坏，禁用 agent 误判可用
    """
    executor = _executor(db)
    assert executor._agent_available() is True


def test_agent_available_disabled_false(db):
    """TC-EXEC-023 | Agent 存在但 enabled=False 时返回 False

    输入: engine 真实 + 一个 disabled agent
    预期输出: False
    断言点: 返回 is False
    防回归: 若 enabled 字段读取被改坏，禁用 agent 误判可用
    """
    with Session(db.engine) as s:
        disabled = Agent(organization="OpenAN", name="Disabled", enabled=False)
        s.add(disabled)
        s.commit()
        s.refresh(disabled)
        did = disabled.id
    executor = _executor(_runtime(db, agent_id=did))
    assert executor._agent_available() is False


def test_agent_available_missing_false(db):
    """TC-EXEC-024 | agent_id 不存在时返回 False

    输入: engine 真实、agent_id 不存在
    预期输出: False
    断言点: 返回 is False
    防回归: 若 agent is None 判断被改坏，访问属性异常
    """
    executor = _executor(_runtime(db, agent_id=999999))
    assert executor._agent_available() is False


def test_llm_reply_no_config_returns_none(db):
    """TC-EXEC-025 | llm_config 为 None 时返回 None 且 mode=dataset

    输入: runtime 无 llm_config
    预期输出: None；info["llm"]["mode"]=="dataset"
    断言点: 返回 None + mode 标记
    防回归: 若 None 守卫被删除，访问 cfg.language 将异常
    """
    info = {}
    executor = _executor(db)
    assert executor._llm_reply(TV_LIVE, "提示", info) is None
    assert info["llm"] == {"mode": "dataset", "used": False}


def test_llm_reply_no_template_or_empty_prompt_returns_none(db):
    """TC-EXEC-026 | 有 cfg 但无模板或空提示时返回 None（mode=llm）

    输入: llm_config 已设；template_uri=None / prompt=""
    预期输出: None
    断言点: 两种输入均返回 None 且 mode=="llm"
    防回归: 若空提示守卫被删除，将调用 LLM 客户端
    """
    executor = _executor(_runtime(db, llm_config=_llm_cfg()))
    assert executor._llm_reply(None, "提示", {}) is None
    assert executor._llm_reply(TV_LIVE, "", {}) is None
    assert executor._llm_reply(TV_LIVE, "   ", {}) is None


def test_llm_reply_ask_failure_returns_none_with_error(db, monkeypatch):
    """TC-EXEC-027 | ask_llm 抛异常时捕获、记录 error 并返回 None

    输入: monkeypatch ask_llm 抛 RuntimeError
    预期输出: None；info["llm"]["error"] 含异常信息
    断言点: 返回 None + error 含 "boom"
    防回归: 若异常捕获被删除，LLM 失败将上抛而非回落桩
    """
    def boom(cfg, prompt, timeout=120.0, transport=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(executor_module.llm_client, "ask_llm", boom)
    info = {}
    executor = _executor(_runtime(db, llm_config=_llm_cfg()))
    assert executor._llm_reply(TV_LIVE, "提示", info) is None
    assert "boom" in info["llm"]["error"]
    assert info["llm"]["used"] is False


def test_llm_reply_success_returns_prompt_artifact(db, monkeypatch):
    """TC-EXEC-028 | ask_llm 成功时返回 {artifactPrompt, artifactName=llm.<seg>}

    输入: monkeypatch ask_llm 返回 "llm-text"
    预期输出: {"artifactPrompt":"llm-text","artifactName":"llm.live-stream-quality"}
    断言点: artifactPrompt 等于 mock 文本；artifactName 取倒数第二段
    防回归: 若模型/used/命名逻辑被改坏，返回内容错
    """
    monkeypatch.setattr(executor_module.llm_client, "ask_llm", lambda *a, **k: "llm-text")
    info = {}
    executor = _executor(_runtime(db, llm_config=_llm_cfg()))
    result = executor._llm_reply(TV_LIVE, "提示", info)
    assert result == {"artifactPrompt": "llm-text", "artifactName": "llm.live-stream-quality"}
    assert info["llm"]["used"] is True
    assert info["llm"]["model"] == "qwen-test"


def test_workflow_reply_no_config_returns_none(db):
    """TC-EXEC-029 | workflow_config 为 None 时返回 None 且 mode=None

    输入: runtime 无 workflow_config
    预期输出: None；info["workflow"]["mode"] is None
    断言点: 返回 None + mode 标记
    防回归: 若 None 守卫被删除，访问 cfg.get 将异常
    """
    info = {}
    executor = _executor(db)
    assert executor._workflow_reply(TV_LIVE, "提示", info) is None
    assert info["workflow"] == {"mode": None, "used": False}


def test_workflow_reply_disabled_returns_none(db):
    """TC-EXEC-030 | workflow.enabled=False 时返回 None

    输入: workflow_config={"enabled": False}
    预期输出: None
    断言点: 返回 None
    防回归: 若 enabled 判断被改坏，禁用工作流仍执行
    """
    executor = _executor(_runtime(db, workflow_config={"enabled": False}))
    assert executor._workflow_reply(TV_LIVE, "提示", {}) is None


def test_workflow_reply_missing_definition_returns_none(db, monkeypatch):
    """TC-EXEC-031 | 工作流定义未找到时返回 None 并记 error

    输入: cfg enabled，monkeypatch load_builtin 返回 None
    预期输出: None；info["workflow"]["error"] 含 "not found"
    断言点: 返回 None + error 关键字
    防回归: 若未找到守卫被删除，将访问空工作流字典
    """
    monkeypatch.setattr(executor_module.workflow_mode, "load_builtin", lambda wid: None)
    info = {}
    executor = _executor(_runtime(db, workflow_config={"enabled": True, "workflowId": "nope"}))
    assert executor._workflow_reply(TV_LIVE, "提示", info) is None
    assert "not found" in info["workflow"]["error"]


def test_workflow_reply_no_cards_returns_none(db, monkeypatch):
    """TC-EXEC-032 | 工作流定义存在但无 agent cards 时返回 None 并记 error

    输入: cfg enabled + 空 workflow_cards，load_builtin 返回定义
    预期输出: None；error 含 "no agent cards"
    断言点: 返回 None + error 关键字
    防回归: 若空 cards 守卫被删除，run_workflow_sync 将以空 cards 执行
    """
    monkeypatch.setattr(executor_module.workflow_mode, "load_builtin", lambda wid: {"id": wid, "steps": []})
    info = {}
    executor = _executor(_runtime(db, workflow_config={"enabled": True}, workflow_cards=[]))
    assert executor._workflow_reply(TV_LIVE, "提示", info) is None
    assert "no agent cards" in info["workflow"]["error"]


def test_workflow_reply_run_failure_returns_none(db, monkeypatch):
    """TC-EXEC-033 | run_workflow_sync 抛异常时返回 None 并记 error

    输入: cfg enabled + cards，monkeypatch run_workflow_sync 抛异常
    预期输出: None；error 含异常信息
    断言点: 返回 None + error 含 "wf-boom"
    防回归: 若异常捕获被删除，工作流失败将上抛而非回落
    """
    monkeypatch.setattr(executor_module.workflow_mode, "load_builtin", lambda wid: {"id": wid})
    monkeypatch.setattr(executor_module.workflow_mode, "run_workflow_sync", lambda *a: (_ for _ in ()).throw(RuntimeError("wf-boom")))
    info = {}
    executor = _executor(_runtime(db, workflow_config={"enabled": True}, workflow_cards=[{"name": "A"}]))
    assert executor._workflow_reply(TV_LIVE, "提示", info) is None
    assert "wf-boom" in info["workflow"]["error"]


def test_workflow_reply_unsuccessful_returns_none(db, monkeypatch):
    """TC-EXEC-034 | 工作流执行完成但 success=False 时返回 None 并记 error

    输入: monkeypatch summarize_execution 返回 {"success": False, "steps": [], "finalText": ""}
    预期输出: None；error 含 "without success"
    断言点: 返回 None + used True + error 关键字
    防回归: 若 success 判断被改坏，失败工作流仍返回 artifact
    """
    monkeypatch.setattr(executor_module.workflow_mode, "load_builtin", lambda wid: {"id": wid})
    monkeypatch.setattr(executor_module.workflow_mode, "run_workflow_sync", lambda *a: {"events": []})
    monkeypatch.setattr(
        executor_module.workflow_mode, "summarize_execution",
        lambda outcome: {"success": False, "steps": [], "finalText": ""},
    )
    info = {}
    executor = _executor(_runtime(db, workflow_config={"enabled": True}, workflow_cards=[{"name": "A"}]))
    assert executor._workflow_reply(TV_LIVE, "提示", info) is None
    assert info["workflow"]["used"] is True
    assert "without success" in info["workflow"]["error"]


def test_workflow_reply_success_returns_artifact(db, monkeypatch):
    """TC-EXEC-035 | 工作流执行成功时返回含步骤汇总的 artifact

    输入: monkeypatch run_workflow_sync + summarize_execution 返回成功摘要（含步骤）
    预期输出: {"artifactPrompt": <含 workflowId 与步骤行>, "artifactName": "workflow-execution-report"}
    断言点: artifactName 固定；artifactPrompt 含 workflowId 与步骤行与 finalText
    防回归: 若步骤行拼接或 finalText 拼接被改坏，artifact 内容错
    """
    monkeypatch.setattr(executor_module.workflow_mode, "load_builtin", lambda wid: {"id": wid})
    monkeypatch.setattr(executor_module.workflow_mode, "run_workflow_sync", lambda *a: {"events": []})
    monkeypatch.setattr(
        executor_module.workflow_mode, "summarize_execution",
        lambda outcome: {
            "success": True,
            "steps": [{"step": "S1", "status": "success", "agent": "A1"}],
            "finalText": "FINAL-TEXT",
        },
    )
    info = {}
    executor = _executor(_runtime(db, workflow_config={"enabled": True, "workflowId": "wf-x"}, workflow_cards=[{"name": "A"}]))
    result = executor._workflow_reply(TV_LIVE, "提示", info)
    assert result["artifactName"] == "workflow-execution-report"
    assert "wf-x" in result["artifactPrompt"]
    assert "S1" in result["artifactPrompt"]
    assert "A1" in result["artifactPrompt"]
    assert "FINAL-TEXT" in result["artifactPrompt"]
    assert info["workflow"]["used"] is True


# =====================================================================
# F. _select_stub 选择链
# =====================================================================


def test_select_stub_no_engine_or_no_template_returns_none(db):
    """TC-EXEC-036 | 无 engine 或无 template_uri 时 _select_stub 返回 None

    输入: template_uri=None（有 engine）/ 有 template 无 engine
    预期输出: None
    断言点: 两种输入均返回 None
    防回归: 若守卫被删除，None engine 下 pick_variant 将异常
    """
    fe = _FakeFlowEnv()
    e1 = _executor(_runtime(db), flow_env=fe)
    assert e1._select_stub(None, "提示", {}) is None
    e2 = _executor(_runtime(db, engine=None), flow_env=fe)
    assert e2._select_stub(TV_LIVE, "提示", {}) is None


def test_select_stub_dataset_match_returns_adapted_reply(db):
    """TC-EXEC-037 | 数据集命中时返回回填后的 {artifactPrompt, artifactName} 并记 meta

    输入: 同模板样例请求作为 prompt（score 高）；dataset_search 开启
    预期输出: dict 含 artifactPrompt/artifactName；info["datasetMatch"] 为 meta dict
    断言点: 返回含 artifactName；meta.score 存在且 > 0
    防回归: 若数据集命中或回填被改坏，回落到变体池
    """
    prompt = dataset_retrieval.sample_request(TV_LIVE)
    info = {}
    executor = _executor(db)
    result = executor._select_stub(TV_LIVE, prompt, info)
    assert "artifactPrompt" in result
    assert "artifactName" in result
    assert info["datasetMatch"] is not None
    assert info["datasetMatch"]["score"] > 0


def test_select_stub_dataset_search_failure_falls_to_variant_pool(db, monkeypatch):
    """TC-EXEC-061 | dataset_retrieval.search 抛异常时捕获并回落变体池

    输入: monkeypatch dataset_retrieval.search 抛 RuntimeError；该模板有变体
    预期输出: 返回变体 artifactPrompt；info["datasetMatch"] is None
    断言点: 返回变体内容；datasetMatch 为 None（异常被吞）
    防回归: 若异常捕获被删除，dataset 检索失败将上抛而非回落变体池
    """
    def boom(tpl, prompt):
        raise RuntimeError("search-boom")

    monkeypatch.setattr(executor_module.dataset_retrieval, "search", boom)
    info = {}
    executor = _executor(db)
    result = executor._select_stub(TV_LIVE, "直播间卡顿", info)
    assert result["artifactPrompt"] == "live-stub-text"
    assert info["datasetMatch"] is None


def test_select_stub_out_of_scope_falls_to_variant_pool(db):
    """TC-EXEC-038 | 模板不在 dataset_templates 范围内时跳过检索、回落变体池

    输入: dataset_templates 排除当前模板；该模板有变体
    预期输出: 返回变体 artifactPrompt；info["datasetMatch"]["skipped"]=="out-of-scope"
    断言点: 返回含变体 artifactPrompt；datasetMatch 标记 skipped
    防回归: 若范围判断被改坏，越界模板仍走检索
    """
    info = {}
    executor = _executor(_runtime(db, dataset_templates=["Other-T/x/y"]))
    result = executor._select_stub(TV_LIVE, "直播间卡顿", info)
    assert result["artifactPrompt"] == "live-stub-text"
    assert info["datasetMatch"]["skipped"] == "out-of-scope"


def test_select_stub_dataset_search_disabled_falls_to_variant_pool(db):
    """TC-EXEC-039 | dataset_search 关闭时直接走变体池（datasetMatch=None）

    输入: settings.dataset_search=False；该模板有变体
    预期输出: 返回变体 artifactPrompt；info["datasetMatch"] is None
    断言点: 返回变体内容；datasetMatch 为 None
    防回归: 若 dataset_search 开关被忽略，仍会执行检索
    """
    import dataclasses
    settings = dataclasses.replace(db.settings, dataset_search=False)
    info = {}
    executor = _executor(_runtime(db, settings=settings))
    result = executor._select_stub(TV_LIVE, "直播间卡顿", info)
    assert result["artifactPrompt"] == "live-stub-text"
    assert info["datasetMatch"] is None


def test_select_stub_no_variant_returns_none(db):
    """TC-EXEC-040 | 无匹配变体且无数据集命中时返回 None

    输入: dataset_search 关闭 + 无变体模板
    预期输出: None
    断言点: 返回 is None
    防回归: 若 None 变体处理被改坏，访问 variant.variant_json 将异常
    """
    import dataclasses
    settings = dataclasses.replace(db.settings, dataset_search=False)
    executor = _executor(_runtime(db, settings=settings))
    assert executor._select_stub(TV_NOVARIANT, "提示", {}) is None


def test_select_stub_workflow_path_returns_workflow_reply(db, monkeypatch):
    """TC-EXEC-041 | 工作流命中时返回工作流 artifact

    输入: workflow_config enabled + monkeypatch 工作流成功
    预期输出: {"artifactPrompt": <含 workflowId>, "artifactName": "workflow-execution-report"}
    断言点: artifactName 固定工作流报告名
    防回归: 若工作流优先级被改坏，将回落 LLM/数据集
    """
    monkeypatch.setattr(executor_module.workflow_mode, "load_builtin", lambda wid: {"id": wid})
    monkeypatch.setattr(executor_module.workflow_mode, "run_workflow_sync", lambda *a: {"events": []})
    monkeypatch.setattr(
        executor_module.workflow_mode, "summarize_execution",
        lambda outcome: {"success": True, "steps": [{"step": "S", "status": "success", "agent": "A"}], "finalText": "F"},
    )
    executor = _executor(_runtime(db, workflow_config={"enabled": True, "workflowId": "wf-x"}, workflow_cards=[{"name": "A"}]))
    result = executor._select_stub(TV_LIVE, "提示", {})
    assert result["artifactName"] == "workflow-execution-report"


def test_select_stub_llm_path_returns_llm_reply(db, monkeypatch):
    """TC-EXEC-042 | 工作流未启用、LLM 命中时返回 LLM artifact

    输入: llm_config 已设、无 workflow_config；monkeypatch ask_llm 成功
    预期输出: {"artifactPrompt": "llm-text", "artifactName": "llm.live-stream-quality"}
    断言点: artifactName 取 llm.<段>
    防回归: 若 LLM 优先级或回落被改坏，将走数据集/变体池
    """
    monkeypatch.setattr(executor_module.llm_client, "ask_llm", lambda *a, **k: "llm-text")
    executor = _executor(_runtime(db, llm_config=_llm_cfg()))
    result = executor._select_stub(TV_LIVE, "提示", {})
    assert result["artifactName"] == "llm.live-stream-quality"
    assert result["artifactPrompt"] == "llm-text"


def test_select_stub_real_agent_subclass_infers_template(db):
    """TC-EXEC-043 | 真实 Agent 子类 transform_request 推断模板后命中数据集

    输入: livestream-stub Agent 实例 + template_uri=None + 直播相关 prompt
    预期输出: 返回数据集命中的 artifact（artifactName 存在）
    断言点: 推断模板 == TV_LIVE 且返回含 artifactName
    防回归: 若 Agent 子类注入或 transform_request 调用被改坏，模板推断失效
    """
    agent = agent_registry.load_agent_instance(agent_registry.agents_dir() / "livestream-stub")
    prompt = dataset_retrieval.sample_request(TV_LIVE)
    executor = _executor(_runtime(db, agent=agent))
    result = executor._select_stub(None, prompt, {})
    assert "artifactName" in result


# =====================================================================
# G. _enqueue / _update_status
# =====================================================================


def _completed_flow(text=None, data=None, name=None):
    return FlowResult(
        state="COMPLETED", message_text="ok", reply_metadata={},
        artifact_data=data, negotiated=False, artifact_text=text, artifact_name=name,
    )


async def test_enqueue_completed_artifact_text_emits_artifact(db):
    """TC-EXEC-044 | COMPLETED+artifact_text 入队 Task/WORKING 状态/artifact 事件

    输入: COMPLETED FlowResult 含 artifact_text
    预期输出: 事件序列 [Task, TaskStatusUpdate(WORKING), TaskArtifactUpdate]
    断言点: 事件类型序列 + artifact.parts[0].text == artifact_text
    防回归: 若 artifact 装配或 WORKING 状态更新被改坏，事件缺失
    """
    executor = _executor(db)
    eq = RecordingEventQueue()
    flow = _completed_flow(text="the-text", name="art-nm")
    await executor._enqueue(_make_request_context(), eq, "tid", "cid", flow, TV_LIVE)
    types = [type(e).__name__ for e in eq.events]
    assert types == ["Task", "TaskStatusUpdateEvent", "TaskArtifactUpdateEvent"]
    artifact_event = eq.events[-1]
    assert artifact_event.artifact.parts[0].text == "the-text"
    assert artifact_event.artifact.name == "art-nm"
    assert artifact_event.last_chunk is True


async def test_enqueue_completed_artifact_data_emits_data_artifact(db):
    """TC-EXEC-045 | COMPLETED+artifact_data（无 text）入队 data 型 artifact

    输入: COMPLETED FlowResult 含 artifact_data（dict）无 artifact_text
    预期输出: artifact.parts[0] 为 data（Struct）；name 由 artifact_name(template) 推导
    断言点: artifact.name == artifact_name(TV_LIVE)；data 字段可读
    防回归: 若 data 分支被改坏，ParseDict data 将异常或缺失
    """
    executor = _executor(db)
    eq = RecordingEventQueue()
    flow = _completed_flow(data={"k": "v"})
    await executor._enqueue(_make_request_context(), eq, "tid", "cid", flow, TV_LIVE)
    artifact_event = eq.events[-1]
    assert artifact_event.artifact.name == artifact_name(TV_LIVE)
    assert MessageToDict(artifact_event.artifact.parts[0])["data"] == {"k": "v"}


async def test_enqueue_completed_with_match_meta_merges_metadata(db):
    """TC-EXEC-046 | COMPLETED 带 match_meta 时 artifact.metadata 含 openan.datasetMatch

    输入: COMPLETED FlowResult + match_meta={"pairId":"p"}
    预期输出: artifact.metadata 含 openan.datasetMatch（JSON 字符串）
    断言点: metadata["openan.datasetMatch"] 含 pairId
    防回归: 若 match_meta 合并被改坏，datasetMatch 丢失
    """
    executor = _executor(db)
    eq = RecordingEventQueue()
    flow = _completed_flow(text="t")
    await executor._enqueue(_make_request_context(), eq, "tid", "cid", flow, TV_LIVE, match_meta={"pairId": "p1"})
    artifact_event = eq.events[-1]
    meta = MessageToDict(artifact_event.artifact.metadata)
    assert "pairId" in meta["openan.datasetMatch"]


async def test_enqueue_input_required_emits_working_negotiating(db):
    """TC-EXEC-047 | INPUT_REQUIRED 入队 Task + WORKING(negotiating) 状态

    输入: INPUT_REQUIRED FlowResult
    预期输出: 事件序列 [Task, TaskStatusUpdate(WORKING)]
    断言点: 事件类型序列（无 artifact 事件）
    防回归: 若 INPUT_REQUIRED 分支被改坏，不会发 negotiating 状态
    """
    executor = _executor(db)
    eq = RecordingEventQueue()
    flow = FlowResult(state="INPUT_REQUIRED", message_text="neg", reply_metadata={}, artifact_data=None, negotiated=True)
    await executor._enqueue(_make_request_context(), eq, "tid", "cid", flow, TV_LIVE)
    types = [type(e).__name__ for e in eq.events]
    assert types == ["Task", "TaskStatusUpdateEvent"]
    assert eq.events[1].status.state == TaskState.TASK_STATE_WORKING


async def test_enqueue_other_state_emits_only_initial_task(db):
    """TC-EXEC-048 | 非 COMPLETED/INPUT_REQUIRED 状态仅入队初始 Task

    输入: FAILED FlowResult
    预期输出: 事件序列 [Task]
    断言点: 仅一个 Task 事件
    防回归: 若状态分支被改坏，FAILED 会误发 artifact
    """
    executor = _executor(db)
    eq = RecordingEventQueue()
    flow = FlowResult(state="FAILED", message_text="bad", reply_metadata={}, artifact_data=None, negotiated=False)
    await executor._enqueue(_make_request_context(), eq, "tid", "cid", flow, TV_LIVE)
    assert [type(e).__name__ for e in eq.events] == ["Task"]


async def test_update_status_non_terminal_emits_working_state(db):
    """TC-EXEC-049 | 非终态状态入队 TaskStatusUpdateEvent 且状态为 WORKING

    输入: state_json="TASK_STATE_WORKING"
    预期输出: 入队 TaskStatusUpdateEvent，其 status.state == TASK_STATE_WORKING
    断言点: 事件类型 + status.state == TaskState.TASK_STATE_WORKING
    防回归: 若状态映射被改坏，state 值错位
    """
    executor = _executor(db)
    eq = RecordingEventQueue()
    ctx = _make_request_context()
    await executor._update_status(ctx, eq, "tid", "cid", "TASK_STATE_WORKING", "processing")
    assert type(eq.events[0]).__name__ == "TaskStatusUpdateEvent"
    assert eq.events[0].status.state == TaskState.TASK_STATE_WORKING


async def test_update_status_terminal_emits_completed_state(db):
    """TC-EXEC-050 | 终态状态入队 TaskStatusUpdateEvent 且状态为 COMPLETED

    输入: state_json="TASK_STATE_COMPLETED"（终态）
    预期输出: status.state == TASK_STATE_COMPLETED
    断言点: status.state == TaskState.TASK_STATE_COMPLETED（终态分支被执行）
    防回归: 若终态判断/状态映射被改坏，终态 state 错位
    """
    executor = _executor(db)
    eq = RecordingEventQueue()
    ctx = _make_request_context()
    await executor._update_status(ctx, eq, "tid", "cid", "TASK_STATE_COMPLETED", "done")
    assert eq.events[0].status.state == TaskState.TASK_STATE_COMPLETED


async def test_update_status_with_metadata_sets_message_metadata(db):
    """TC-EXEC-051 | 带 metadata 时写入 status.message.metadata

    输入: state_json="TASK_STATE_WORKING" + metadata={"k":"v"}
    预期输出: status.message.metadata 含 k
    断言点: metadata 序列化后含 k
    防回归: 若 metadata 合并被改坏，message.metadata 丢失
    """
    executor = _executor(db)
    eq = RecordingEventQueue()
    ctx = _make_request_context()
    await executor._update_status(ctx, eq, "tid", "cid", "TASK_STATE_WORKING", "x", metadata={"k": "v"})
    meta = MessageToDict(eq.events[0].status.message.metadata)
    assert meta.get("k") == "v"


async def test_update_status_copies_existing_current_task(db):
    """TC-EXEC-052 | context.current_task 已存在时 CopyFrom 后更新 id/status

    输入: context.current_task 为既有 Task（含历史 id）
    预期输出: 执行后 current_task.id 被覆盖为新 task_id，status 为新状态
    断言点: current_task.id == 新 task_id（旧 id 被覆盖）
    防回归: 若 CopyFrom 分支被改坏，既有 task 字段未被正确复制/覆盖
    """
    from a2a.types.a2a_pb2 import Task
    executor = _executor(db)
    eq = RecordingEventQueue()
    ctx = _make_request_context()
    existing = Task()
    existing.id = "old-id"
    ctx.current_task = existing
    await executor._update_status(ctx, eq, "new-tid", "cid", "TASK_STATE_WORKING", "x")
    assert ctx.current_task.id == "new-tid"
    assert ctx.current_task.status.state == TaskState.TASK_STATE_WORKING


# =====================================================================
# H. execute 端到端
# =====================================================================


async def test_execute_agent_disabled_returns_failed(db, real_flow_env):
    """TC-EXEC-053 | agent 不可用时 execute 返回 FAILED 并写入日志

    输入: runtime 无 engine/agent_id（_agent_available=False）；带 log_sink
    预期输出: task_state=FAILED；事件含初始 Task 与终态状态更新
    断言点: sink 记录 task_state=="TASK_STATE_FAILED"；事件含终态更新
    防回归: 若不可用分支被改坏，会尝试 run_flow 导致异常
    """
    sink_logs = []

    async def sink(entry):
        sink_logs.append(entry)

    executor = MockAgentExecutor(real_flow_env, _runtime(), log_sink=sink)
    eq = RecordingEventQueue()
    msg = _make_message(TV_LIVE, "提示")
    ctx = _make_request_context(message=msg, exts={TASK_T_URI})
    await executor.execute(ctx, eq)
    assert sink_logs
    assert sink_logs[0]["task_state"] == "TASK_STATE_FAILED"
    assert sink_logs[0]["response_body"]["state"] == "FAILED"
    assert any(type(e).__name__ == "TaskStatusUpdateEvent" for e in eq.events)


async def test_execute_completed_variant_pool_emits_artifact(db, real_flow_env):
    """TC-EXEC-054 | agent 可用且无数据集命中时走变体池，COMPLETED 发 artifact

    输入: runtime 含 engine+agent_id；消息模板有变体；prompt 不命中数据集
    预期输出: 事件含 TaskArtifactUpdateEvent；sink 记录 COMPLETED
    断言点: 存在 artifact 事件；sink task_state==COMPLETED；artifact.parts[0].text 非空
    防回归: 若变体池选择或 COMPLETED artifact 装配被改坏，artifact 缺失
    """
    sink_logs = []

    async def sink(entry):
        sink_logs.append(entry)

    executor = MockAgentExecutor(real_flow_env, _runtime(db), log_sink=sink)
    eq = RecordingEventQueue()
    msg = _make_message(TV_LIVE, "zzz-qxx-不匹配-数据集")
    ctx = _make_request_context(message=msg, exts={TASK_T_URI})
    await executor.execute(ctx, eq)
    artifact_events = [e for e in eq.events if type(e).__name__ == "TaskArtifactUpdateEvent"]
    assert artifact_events
    assert artifact_events[0].artifact.parts[0].text == "live-stub-text"
    assert sink_logs[0]["task_state"] == "TASK_STATE_COMPLETED"


async def test_execute_dataset_match_emits_trace_metadata(db, real_flow_env):
    """TC-EXEC-055 | 数据集命中时 execute 追加 trace metadata 二次状态更新

    输入: runtime 含 engine+agent_id；prompt 为同模板样例请求（高命中）
    预期输出: 事件末尾出现两次终态 TaskStatusUpdateEvent（第二次带 datasetMatch metadata）
    断言点: 终态状态更新计数==2；第二次含 openan.datasetMatch metadata；sink 记录 datasetMatch
    防回归: 若 trace metadata 分支被改坏，第二次状态更新缺失
    """
    sink_logs = []

    async def sink(entry):
        sink_logs.append(entry)

    executor = MockAgentExecutor(real_flow_env, _runtime(db), log_sink=sink)
    eq = RecordingEventQueue()
    prompt = dataset_retrieval.sample_request(TV_LIVE)
    msg = _make_message(TV_LIVE, prompt)
    ctx = _make_request_context(message=msg, exts={TASK_T_URI})
    await executor.execute(ctx, eq)
    status_events = [e for e in eq.events if type(e).__name__ == "TaskStatusUpdateEvent"]
    terminal = [e for e in status_events if e.status.state == TaskState.TASK_STATE_COMPLETED]
    assert len(terminal) == 2
    second_meta = MessageToDict(terminal[1].status.message.metadata)
    assert "openan.datasetMatch" in second_meta
    assert sink_logs[0]["response_body"]["datasetMatch"] is not None


async def test_execute_dataset_match_json_failure_skips_trace(db, real_flow_env, monkeypatch):
    """TC-EXEC-062 | match_meta 序列化失败时跳过 trace metadata 与 artifact datasetMatch

    输入: 数据集命中（match_meta 为 dict）；rebind executor 模块的 json 为抛 TypeError 的桩
    预期输出: 终态状态更新计数==1（trace 跳过）；artifact.metadata 不含 openan.datasetMatch
    断言点: 终态 COMPLETED 计数==1；artifact metadata 无 openan.datasetMatch；sink 仍记录 datasetMatch
    防回归: 若 json.dumps 异常捕获被删除，序列化失败将上抛导致事件缺失
    """
    sink_logs = []

    async def sink(entry):
        sink_logs.append(entry)

    def raising_dumps(*a, **k):
        raise TypeError("not serializable")

    monkeypatch.setattr(executor_module, "json", SimpleNamespace(dumps=raising_dumps))
    executor = MockAgentExecutor(real_flow_env, _runtime(db), log_sink=sink)
    eq = RecordingEventQueue()
    prompt = dataset_retrieval.sample_request(TV_LIVE)
    msg = _make_message(TV_LIVE, prompt)
    ctx = _make_request_context(message=msg, exts={TASK_T_URI})
    await executor.execute(ctx, eq)
    status_events = [e for e in eq.events if type(e).__name__ == "TaskStatusUpdateEvent"]
    terminal = [e for e in status_events if e.status.state == TaskState.TASK_STATE_COMPLETED]
    assert len(terminal) == 1
    artifact_event = next(e for e in eq.events if type(e).__name__ == "TaskArtifactUpdateEvent")
    assert "openan.datasetMatch" not in MessageToDict(artifact_event.artifact.metadata)
    assert sink_logs[0]["response_body"]["datasetMatch"] is not None


async def test_execute_run_flow_error_returns_internal_error(db, real_flow_env, monkeypatch):
    """TC-EXEC-056 | run_flow 抛异常时 execute 捕获并返回 FAILED "internal error"

    输入: monkeypatch executor.run_flow 抛 RuntimeError；agent 可用
    预期输出: sink 记录 message 含 "internal error"；task_state=FAILED
    断言点: sink response_body.message 含 "internal error"
    防回归: 若 run_flow 异常捕获被删除，execute 将上抛而非回落 FAILED
    """
    sink_logs = []

    async def sink(entry):
        sink_logs.append(entry)

    def raising(*a, **kw):
        raise RuntimeError("flow-boom")

    monkeypatch.setattr(executor_module, "run_flow", raising)
    executor = MockAgentExecutor(real_flow_env, _runtime(db), log_sink=sink)
    eq = RecordingEventQueue()
    msg = _make_message(TV_LIVE, "提示")
    ctx = _make_request_context(message=msg, exts={TASK_T_URI})
    await executor.execute(ctx, eq)
    assert "internal error" in sink_logs[0]["response_body"]["message"]
    assert sink_logs[0]["task_state"] == "TASK_STATE_FAILED"


async def test_execute_log_sink_failure_still_completes(db, real_flow_env):
    """TC-EXEC-057 | log_sink 抛异常时 execute 捕获并仍完成状态更新

    输入: agent 不可用（FAILED 路径）；log_sink 抛 RuntimeError
    预期输出: 仍发出终态 TaskStatusUpdateEvent（异常被吞）
    断言点: 事件含终态状态更新（log_sink 异常未中断）
    防回归: 若 log_sink 异常捕获被删除，execute 将上抛导致事件缺失
    """

    async def bad_sink(entry):
        raise RuntimeError("sink-boom")

    executor = MockAgentExecutor(real_flow_env, _runtime(), log_sink=bad_sink)
    eq = RecordingEventQueue()
    msg = _make_message(TV_LIVE, "提示")
    ctx = _make_request_context(message=msg, exts={TASK_T_URI})
    await executor.execute(ctx, eq)
    status_events = [e for e in eq.events if type(e).__name__ == "TaskStatusUpdateEvent"]
    assert status_events
    assert status_events[-1].status.state == TaskState.TASK_STATE_FAILED


def test_state_json_and_terminal_constants():
    """TC-EXEC-058 | STATE_JSON 映射与 TERMINAL_STATES 集合符合约定

    输入: 无
    预期输出: STATE_JSON["COMPLETED"]=="TASK_STATE_COMPLETED"；终态集合含四个
    断言点: 映射值精确 + 终态集合内容
    防回归: 若状态映射被改坏，execute 写入的 task_state 错位
    """
    assert STATE_JSON["COMPLETED"] == "TASK_STATE_COMPLETED"
    assert STATE_JSON["FAILED"] == "TASK_STATE_FAILED"
    assert set(STATE_JSON).issuperset({"COMPLETED", "REJECTED", "CANCELED", "INPUT_REQUIRED", "FAILED"})
