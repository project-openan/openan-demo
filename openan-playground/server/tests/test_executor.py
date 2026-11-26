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

import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from a2a.types import Task, TaskArtifactUpdateEvent, TaskStatusUpdateEvent
from google.protobuf.struct_pb2 import Struct

from openan_debug import db, main
from openan_debug.agent import executor, flow_env
from openan_debug.agent.a2a_app import EchoExtensionsMiddleware, build_a2a_app
from openan_debug.agent.executor import MockAgentExecutor, artifact_name, extract_request
from openan_debug.config import Settings
from openan_debug.db import init_db, make_engine
from openan_debug.llm_client import LlmConfig
from openan_debug.models import Agent, RequestLog, ServiceSettings, User
from openan_debug.protocol_flow import FlowResult
from tests.conftest import TEST_ENV


# --------------------------------------------------------------------------- #
# Shared helpers / fakes
# --------------------------------------------------------------------------- #
class _FakeQueue:
    def __init__(self):
        self.events = []

    async def enqueue_event(self, event):
        self.events.append(event)


class _FakeCtx:
    def __init__(self, task_id="t-1", context_id="c-1", message=None, current_task=None):
        self.task_id = task_id
        self.context_id = context_id
        self.message = message
        self.current_task = current_task
        self.requested_extensions = None
        self.call_context = None


def _struct(d):
    s = Struct()
    s.update(d)
    return s


def _runtime(settings, **overrides):
    rt = {
        "engine": None,
        "agent_id": None,
        "settings": settings,
        "dataset_templates": None,
        "instance_id": None,
        "llm_config": None,
        "workflow_config": None,
        "workflow_cards": [],
    }
    rt.update(overrides)
    return rt


def _flow_env():
    return SimpleNamespace(a2at=object(), cursor={}, cursor_lock=threading.Lock())


def _executor(settings, log_sink=None, **overrides):
    return MockAgentExecutor(_flow_env(), _runtime(settings, **overrides), log_sink=log_sink)


def _ctx_with_template(template_uri="Task-T/network-layer/complaint-diagnosis/v1", task_id="t-1", context_id="c-1"):
    return _FakeCtx(
        task_id=task_id,
        context_id=context_id,
        message=SimpleNamespace(metadata=_struct({"templateUri": template_uri})),
    )


def _engine_and_agent(settings):
    engine = make_engine(settings)
    init_db(engine, settings)
    with Session(engine) as s:
        agent_id = s.scalar(select(Agent.id).order_by(Agent.id).limit(1))
    return engine, agent_id


def _count(events, cls):
    return sum(1 for e in events if isinstance(e, cls))


def _llm_cfg(**kw):
    base = dict(enabled=True, provider="openai", base_url="http://x", model="m", api_key="k", max_attempts=1)
    base.update(kw)
    return LlmConfig(**base)


# --------------------------------------------------------------------------- #
# executor — TC-DEXEC (module-level helpers)
# --------------------------------------------------------------------------- #
def test_dexec_artifact_name_branches():
    """TC-DEXEC-001 | artifact_name 按模板分段返回 stub 名

    输入: None / 'Task-T/x/y' / 'single' / 'a/b/'
    预期输出: 'stub.result' / 'stub.y' / 'stub.result' / 'stub.a'
    断言点: 各分支返回值精确匹配
    防回归: 若分段逻辑改坏，名称错误
    """
    assert artifact_name(None) == "stub.result"
    assert artifact_name("Task-T/x/y") == "stub.x"
    assert artifact_name("single") == "stub.result"
    assert artifact_name("a/b/") == "stub.a"


def test_dexec_extract_request_message_none_or_empty():
    """TC-DEXEC-002 | extract_request 对无 message/无 metadata 提前返回空

    输入: message=None 与 message.metadata=None
    预期输出: (None, '', None, set())
    断言点: 返回元组各字段
    防回归: 若守卫删除，会访问 metadata 抛错
    """
    ctx = _FakeCtx(message=None)
    ctx.requested_extensions = {"ext1"}
    assert extract_request(ctx) == (None, "", None, {"ext1"})
    ctx2 = _FakeCtx(message=SimpleNamespace(metadata=None))
    assert extract_request(ctx2) == (None, "", None, set())


def test_dexec_extract_request_extensions_resolution():
    """TC-DEXEC-003 | extract_request 优先用 context.requested_extensions，缺失时回落 call_context

    输入: context.requested_extensions={'a'}；另一例为 None 且 call_context.requested_extensions={'b'}
    预期输出: exts 分别为 {'a'} 与 {'b'}
    断言点: 扩展集合来源
    防回归: 若回落分支删除，None 时 exts 丢失
    """
    ctx = _FakeCtx(message=None)
    ctx.requested_extensions = {"a"}
    assert extract_request(ctx)[3] == {"a"}

    ctx2 = _FakeCtx(message=None)
    ctx2.requested_extensions = None
    ctx2.call_context = SimpleNamespace(requested_extensions={"b"})
    assert extract_request(ctx2)[3] == {"b"}


def test_dexec_extract_request_full_metadata():
    """TC-DEXEC-004 | extract_request 解析 templateUri/扩展 prompt/negotiationContext

    输入: message.metadata 含 templateUri、扩展 URI prompt、negotiationContext
    预期输出: (template_uri, prompt, negotiation_context, exts)
    断言点: 各字段值
    防回归: 若解析改坏，template_uri/prompt/上下文错误
    """
    from openan_debug.agent.flow_env import ext_uri_for

    template_uri = "Task-T/network-layer/complaint-diagnosis/v1"
    ext_uri = ext_uri_for(template_uri)
    meta = {"templateUri": template_uri, ext_uri: "prompt-text", "negotiationContext": {"id": "n1"}}
    ctx = _FakeCtx(message=SimpleNamespace(metadata=_struct(meta)))
    ctx.requested_extensions = {"ext1"}
    tpl, prompt, nego, exts = extract_request(ctx)
    assert tpl == template_uri
    assert prompt == "prompt-text"
    assert nego == {"id": "n1"}
    assert exts == {"ext1"}


async def test_dexec_cancel_is_noop():
    """TC-DEXEC-005 | cancel 为空操作，返回 None 且不产生事件

    输入: 任意 context 与空事件队列
    预期输出: None，队列无事件
    断言点: 返回 None + 队列空
    防回归: 若 cancel 被改成入队事件，队列非空
    """
    ex = _executor(None)  # settings unused by cancel
    queue = _FakeQueue()
    assert await ex.cancel(_FakeCtx(), queue) is None
    assert queue.events == []


# --------------------------------------------------------------------------- #
# executor — TC-DEXEC (_llm_reply / _agent_name)
# --------------------------------------------------------------------------- #
def test_dexec_llm_reply_no_config_or_empty_prompt():
    """TC-DEXEC-006 | _llm_reply 无 cfg 或空 prompt 时返回 None 并标注模式

    输入: cfg=None；以及 cfg 存在但 prompt 为空
    预期输出: 均返回 None；info['llm']['mode'] 分别为 'dataset'/'llm' 且 used=False
    断言点: 返回值 + info 标注
    防回归: 若守卫删除，会调用 LLM 抛错
    """
    ex = _executor(None, llm_config=None)
    info = {}
    assert ex._llm_reply("Task-T/x/y", "prompt", info) is None
    assert info["llm"] == {"mode": "dataset", "used": False}

    ex2 = _executor(None, llm_config=_llm_cfg())
    info2 = {}
    assert ex2._llm_reply("Task-T/x/y", "   ", info2) is None
    assert info2["llm"]["mode"] == "llm"
    assert info2["llm"]["used"] is False


def test_dexec_llm_reply_success(monkeypatch):
    """TC-DLLM-007 → TC-DEXEC-007 | _llm_reply 成功返回 artifactPrompt/Name 并标记 used

    输入: cfg 存在 + template+prompt，mock sample_response/build_prompt/ask_llm
    预期输出: {'artifactPrompt':'llm text','artifactName':'llm.x'}，info used=True/model 记录
    断言点: 返回 dict + info['llm']['used']/['model']
    防回归: 若返回构造改坏，artifactName 或 used 错误
    """
    monkeypatch.setattr(executor.dataset_retrieval, "sample_response", lambda tpl: "sample")
    monkeypatch.setattr(executor.llm_client, "build_simulator_prompt", lambda *a, **kw: "prompt")
    monkeypatch.setattr(executor.llm_client, "ask_llm", lambda cfg, prompt: "llm text")
    ex = _executor(None, llm_config=_llm_cfg(model="gpt-4"))
    info = {}
    result = ex._llm_reply("Task-T/x/y", "do task", info)
    assert result == {"artifactPrompt": "llm text", "artifactName": "llm.x"}
    assert info["llm"]["used"] is True
    assert info["llm"]["model"] == "gpt-4"


def test_dexec_llm_reply_failure_returns_none(monkeypatch):
    """TC-DEXEC-008 | _llm_reply 在 ask_llm 抛错时回落 None 并记录 error

    输入: ask_llm 抛 RuntimeError
    预期输出: None，info['llm']['error'] 含错误信息
    断言点: 返回 None + error 记录
    防回归: 若 except 被删除，异常向上抛
    """
    monkeypatch.setattr(executor.dataset_retrieval, "sample_response", lambda tpl: "sample")
    monkeypatch.setattr(executor.llm_client, "build_simulator_prompt", lambda *a, **kw: "prompt")

    def boom(cfg, prompt):
        raise RuntimeError("llm boom")

    monkeypatch.setattr(executor.llm_client, "ask_llm", boom)
    ex = _executor(None, llm_config=_llm_cfg())
    info = {}
    assert ex._llm_reply("Task-T/x/y", "do task", info) is None
    assert "llm boom" in info["llm"]["error"]


def test_dexec_agent_name_without_engine():
    """TC-DEXEC-009 | _agent_name 在 engine/agent_id 缺失时返回 'MockAgent'

    输入: runtime engine=None 与 agent_id=None
    预期输出: 'MockAgent'
    断言点: 返回值
    防回归: 若守卫删除，访问 None engine 抛错
    """
    ex = _executor(None, engine=None, agent_id=None)
    assert ex._agent_name() == "MockAgent"
    ex2 = _executor(None, engine=None, agent_id=5)
    assert ex2._agent_name() == "MockAgent"


def test_dexec_agent_name_from_db(settings):
    """TC-DEXEC-010 | _agent_name 从数据库读取 Agent 名

    输入: 真实 engine + 默认 agent_id
    预期输出: 默认 Agent 名 'OpenAN Debug Mock Agent'
    断言点: 返回值 == 数据库中 Agent.name
    防回归: 若 DB 查询改坏，返回 'MockAgent'
    """
    engine, agent_id = _engine_and_agent(settings)
    ex = _executor(settings, engine=engine, agent_id=agent_id)
    assert ex._agent_name() == "OpenAN Debug Mock Agent"


def test_dexec_agent_name_on_db_error(monkeypatch):
    """TC-DEXEC-011 | _agent_name 在 Session.get 抛错时回落 'MockAgent'

    输入: monkeypatch executor.Session 使 get 抛异常
    预期输出: 'MockAgent'
    断言点: 返回 'MockAgent'（异常被吞）
    防回归: 若 except 删除，异常向上抛
    """

    class _BoomSession:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **kw):
            raise RuntimeError("db down")

    monkeypatch.setattr(executor, "Session", _BoomSession)
    ex = _executor(None, engine=object(), agent_id=1)
    assert ex._agent_name() == "MockAgent"


# --------------------------------------------------------------------------- #
# executor — TC-DEXEC (_workflow_reply)
# --------------------------------------------------------------------------- #
def test_dexec_workflow_reply_no_or_disabled_config():
    """TC-DEXEC-012 | _workflow_reply 无 cfg 或未启用时返回 None

    输入: workflow_config=None 与 {'enabled': False}
    预期输出: None；info['workflow']['mode'] 分别 None/'workflow'，used=False
    断言点: 返回 None + mode 标注
    防回归: 若守卫删除，会加载工作流
    """
    ex = _executor(None, workflow_config=None)
    info = {}
    assert ex._workflow_reply("Task-T/x/y", "p", info) is None
    assert info["workflow"]["mode"] is None

    ex2 = _executor(None, workflow_config={"enabled": False})
    info2 = {}
    assert ex2._workflow_reply("Task-T/x/y", "p", info2) is None
    assert info2["workflow"]["mode"] == "workflow"


def test_dexec_workflow_reply_not_found_or_no_cards(monkeypatch):
    """TC-DEXEC-013 | _workflow_reply 工作流定义缺失或无 agent 卡时返回 None 并记 error

    输入: load_builtin 返回 None（定义缺失）；以及 cards=[]（无卡）
    预期输出: None，info['workflow']['error'] 含对应关键字
    断言点: 返回 None + error 文本
    防回归: 若分支删除，错误未记录
    """
    monkeypatch.setattr(executor.workflow_mode, "load_builtin", lambda wid: None)
    ex = _executor(None, workflow_config={"enabled": True, "workflowId": "nope"}, workflow_cards=[{"name": "a"}])
    info = {}
    assert ex._workflow_reply("Task-T/x/y", "p", info) is None
    assert "workflow definition not found: nope" in info["workflow"]["error"]

    monkeypatch.setattr(executor.workflow_mode, "load_builtin", lambda wid: {"steps": []})
    ex2 = _executor(None, workflow_config={"enabled": True}, workflow_cards=[])
    info2 = {}
    assert ex2._workflow_reply("Task-T/x/y", "p", info2) is None
    assert "no agent cards resolved" in info2["workflow"]["error"]


def test_dexec_workflow_reply_run_failure(monkeypatch):
    """TC-DEXEC-014 | _workflow_reply 在 run_workflow_sync 抛错时返回 None 并记 error

    输入: load_builtin 返回定义，run_workflow_sync 抛 RuntimeError
    预期输出: None，error 含错误信息
    断言点: 返回 None + error
    防回归: 若 except 删除，异常向上抛
    """
    monkeypatch.setattr(executor.workflow_mode, "load_builtin", lambda wid: {"steps": []})

    def boom(*a, **kw):
        raise RuntimeError("wf boom")

    monkeypatch.setattr(executor.workflow_mode, "run_workflow_sync", boom)
    ex = _executor(None, workflow_config={"enabled": True}, workflow_cards=[{"name": "a"}])
    info = {}
    assert ex._workflow_reply("Task-T/x/y", "p", info) is None
    assert "wf boom" in info["workflow"]["error"]


def test_dexec_workflow_reply_not_success(monkeypatch):
    """TC-DEXEC-015 | _workflow_reply 摘要 success=False 时返回 None 并记 error

    输入: run_workflow_sync 返回 {}，summarize_execution 返回 success=False
    预期输出: None，info['workflow']['used']=True 且 error='workflow finished without success'
    断言点: 返回 None + used=True + error 文本
    防回归: 若 success 判定删除，会返回错误的工作流产物
    """
    monkeypatch.setattr(executor.workflow_mode, "load_builtin", lambda wid: {"steps": []})
    monkeypatch.setattr(executor.workflow_mode, "run_workflow_sync", lambda *a, **kw: {})
    monkeypatch.setattr(
        executor.workflow_mode, "summarize_execution", lambda outcome: {"success": False, "steps": [], "finalText": ""}
    )
    ex = _executor(None, workflow_config={"enabled": True}, workflow_cards=[{"name": "a"}])
    info = {}
    assert ex._workflow_reply("Task-T/x/y", "p", info) is None
    assert info["workflow"]["used"] is True
    assert info["workflow"]["error"] == "workflow finished without success"


def test_dexec_workflow_reply_success(monkeypatch):
    """TC-DEXEC-016 | _workflow_reply 成功时返回工作流产物报告

    输入: summarize_execution 返回 success=True + steps + finalText
    预期输出: {'artifactPrompt':含工作流标题与步骤,'artifactName':'workflow-execution-report'}
    断言点: artifactName + 产物含步骤行与 finalText
    防回归: 若产物拼接改坏，内容缺失
    """
    monkeypatch.setattr(executor.workflow_mode, "load_builtin", lambda wid: {"steps": []})
    monkeypatch.setattr(executor.workflow_mode, "run_workflow_sync", lambda *a, **kw: {})
    monkeypatch.setattr(
        executor.workflow_mode,
        "summarize_execution",
        lambda outcome: {
            "success": True,
            "steps": [{"step": "s1", "status": "success", "agent": "a1"}],
            "finalText": "done-text",
        },
    )
    ex = _executor(None, workflow_config={"enabled": True}, workflow_cards=[{"name": "a"}])
    info = {}
    result = ex._workflow_reply("Task-T/x/y", "p", info)
    assert result["artifactName"] == "workflow-execution-report"
    assert "工作流执行结果" in result["artifactPrompt"]
    assert "s1" in result["artifactPrompt"]
    assert "（a1）" in result["artifactPrompt"]
    assert "done-text" in result["artifactPrompt"]
    assert info["workflow"]["used"] is True


# --------------------------------------------------------------------------- #
# executor — TC-DEXEC (_select_stub priority & branches)
# --------------------------------------------------------------------------- #
def test_dexec_select_stub_workflow_priority(monkeypatch):
    """TC-DEXEC-017 | _select_stub 工作流命中时直接返回工作流产物（优先于 LLM/数据集）

    输入: workflow 启用且成功（mock），同时 llm_config 也存在
    预期输出: 返回工作流产物 artifactName='workflow-execution-report'
    断言点: 返回工作流产物 + info['workflow']['used']=True
    防回归: 若优先级改坏，会落到 LLM/数据集
    """
    monkeypatch.setattr(executor.workflow_mode, "load_builtin", lambda wid: {"steps": []})
    monkeypatch.setattr(executor.workflow_mode, "run_workflow_sync", lambda *a, **kw: {})
    monkeypatch.setattr(
        executor.workflow_mode,
        "summarize_execution",
        lambda outcome: {"success": True, "steps": [{"step": "s", "status": "ok"}], "finalText": "f"},
    )
    ex = _executor(None, workflow_config={"enabled": True}, workflow_cards=[{"name": "a"}], llm_config=_llm_cfg())
    info = {}
    result = ex._select_stub("Task-T/x/y", "p", info)
    assert result["artifactName"] == "workflow-execution-report"
    assert info["workflow"]["used"] is True


def test_dexec_select_stub_llm_priority(monkeypatch):
    """TC-DEXEC-018 | _select_stub 工作流未命中时回退 LLM 并返回 LLM 产物

    输入: workflow_config=None，llm_config 存在，mock ask_llm 成功
    预期输出: 返回 LLM 产物 artifactName='llm.x'
    断言点: 返回 LLM 产物
    防回归: 若 LLM 分支删除，会落到数据集/变体池
    """
    monkeypatch.setattr(executor.dataset_retrieval, "sample_response", lambda tpl: "sample")
    monkeypatch.setattr(executor.llm_client, "build_simulator_prompt", lambda *a, **kw: "prompt")
    monkeypatch.setattr(executor.llm_client, "ask_llm", lambda cfg, prompt: "llm text")
    ex = _executor(None, workflow_config=None, llm_config=_llm_cfg())
    info = {}
    result = ex._select_stub("Task-T/x/y", "do task", info)
    assert result == {"artifactPrompt": "llm text", "artifactName": "llm.x"}


def test_dexec_select_stub_dataset_out_of_scope(settings):
    """TC-DEXEC-019 | _select_stub 模板超出 dataset_templates 范围时标记 skipped 并回落变体池

    输入: dataset_templates={'Other-T/x'}（不含请求模板），engine=None
    预期输出: None，info['datasetMatch']['skipped']='out-of-scope'
    断言点: 返回 None + skipped 标记 + scopeTemplates 计数
    防回归: 若范围检查删除，会执行数据集检索
    """
    ex = _executor(settings, dataset_templates={"Other-T/x"}, engine=None)
    info = {}
    assert ex._select_stub("Task-T/x/y", "hello", info) is None
    assert info["datasetMatch"]["skipped"] == "out-of-scope"
    assert info["datasetMatch"]["scopeTemplates"] == 1


def test_dexec_select_stub_dataset_search_error(settings, monkeypatch):
    """TC-DEXEC-020 | _select_stub 数据集检索抛错时回落 None

    输入: monkeypatch dataset_retrieval.search 抛异常，engine=None
    预期输出: None，info['datasetMatch']=None
    断言点: 返回 None + datasetMatch 为 None
    防回归: 若 except 删除，异常向上抛
    """
    monkeypatch.setattr(executor.dataset_retrieval, "search", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("idx")))
    ex = _executor(settings, engine=None)
    info = {}
    assert ex._select_stub("Task-T/x/y", "hello", info) is None
    assert info["datasetMatch"] is None


def test_dexec_select_stub_dataset_match(settings, monkeypatch):
    """TC-DEXEC-021 | _select_stub 数据集命中时返回 adapt 后的产物

    输入: mock search 返回命中对、adapt 返回文本
    预期输出: {'artifactPrompt':'adapted','artifactName':'art'}，info['datasetMatch']=meta
    断言点: 返回 dict + meta
    防回归: 若 adapt/返回构造改坏，产物错误
    """
    monkeypatch.setattr(
        executor.dataset_retrieval, "search", lambda tpl, p: {"responseText": "resp", "artifactName": "art", "meta": {"pairId": "p1"}}
    )
    monkeypatch.setattr(executor.dataset_retrieval, "adapt", lambda resp, req: "adapted")
    ex = _executor(settings, engine=None)
    info = {}
    result = ex._select_stub("Task-T/x/y", "hello", info)
    assert result == {"artifactPrompt": "adapted", "artifactName": "art"}
    assert info["datasetMatch"] == {"pairId": "p1"}


def test_dexec_select_stub_dataset_no_match_or_disabled(settings, monkeypatch):
    """TC-DEXEC-022 | _select_stub 数据集未命中或关闭时标记 None 并回落变体池

    输入: (a) search 返回 None（dataset_search=True）；(b) dataset_search=False
    预期输出: 均返回 None，info['datasetMatch']=None
    断言点: 返回 None + datasetMatch None（两个分支）
    防回归: 若分支改坏，会进入检索或抛错
    """
    ex = _executor(settings, engine=None)
    ex._runtime["workflow_config"] = None
    ex._runtime["llm_config"] = None
    monkeypatch.setattr(executor.dataset_retrieval, "search", lambda *a, **kw: None)
    info = {}
    assert ex._select_stub("Task-T/x/y", "hello", info) is None
    assert info["datasetMatch"] is None

    settings.dataset_search = False
    info2 = {}
    assert ex._select_stub("Task-T/x/y", "hello", info2) is None
    assert info2["datasetMatch"] is None


def test_dexec_select_stub_variant_pool_deepcopy(settings, monkeypatch):
    """TC-DEXEC-023 | _select_stub 回落变体池时返回 variant_json 的深拷贝

    输入: dataset_search=False（跳过数据集），真实 engine，mock pick_variant 返回变体
    预期输出: 返回 {'k':'v'}，且为深拷贝（修改不影响原对象）
    断言点: 返回值相等 + 不是同一对象
    防回归: 若 deepcopy 删除，修改返回值会污染原 variant_json
    """
    engine, agent_id = _engine_and_agent(settings)
    original = {"k": "v"}
    monkeypatch.setattr(executor, "pick_variant", lambda *a, **kw: SimpleNamespace(variant_json=original))
    settings.dataset_search = False
    ex = _executor(settings, engine=engine, agent_id=agent_id)
    ex._runtime["workflow_config"] = None
    ex._runtime["llm_config"] = None
    info = {}
    result = ex._select_stub("Task-T/x/y", "hello", info)
    assert result == {"k": "v"}
    assert result is not original
    result["k"] = "mutated"
    assert original == {"k": "v"}


def test_dexec_select_stub_variant_pool_none(settings, monkeypatch):
    """TC-DEXEC-024 | _select_stub 变体池无命中时返回 None

    输入: dataset_search=False，mock pick_variant 返回 None
    预期输出: None
    断言点: 返回 None
    防回归: 若 None 分支改坏，会访问 None.variant_json 抛错
    """
    engine, agent_id = _engine_and_agent(settings)
    monkeypatch.setattr(executor, "pick_variant", lambda *a, **kw: None)
    settings.dataset_search = False
    ex = _executor(settings, engine=engine, agent_id=agent_id)
    ex._runtime["workflow_config"] = None
    ex._runtime["llm_config"] = None
    assert ex._select_stub("Task-T/x/y", "hello", {}) is None


# --------------------------------------------------------------------------- #
# executor — TC-DEXEC (_agent_available)
# --------------------------------------------------------------------------- #
def test_dexec_agent_available_false_branches(settings):
    """TC-DEXEC-025 | _agent_available 在 engine/agent_id 缺失或 agent 不存在时返回 False

    输入: engine=None；agent_id=None；真实 engine + 不存在 id
    预期输出: 均为 False
    断言点: 三种情况均 False
    防回归: 若守卫删除，None engine 访问抛错
    """
    ex = _executor(settings, engine=None, agent_id=1)
    assert ex._agent_available() is False
    ex2 = _executor(settings, engine=object(), agent_id=None)
    assert ex2._agent_available() is False
    engine, _ = _engine_and_agent(settings)
    ex3 = _executor(settings, engine=engine, agent_id=999999)
    assert ex3._agent_available() is False


def test_dexec_agent_available_true(settings):
    """TC-DEXEC-026 | _agent_available 对已启用默认 Agent 返回 True

    输入: 真实 engine + 默认 agent_id
    预期输出: True
    断言点: 返回 True
    防回归: 若查询改坏，返回 False
    """
    engine, agent_id = _engine_and_agent(settings)
    ex = _executor(settings, engine=engine, agent_id=agent_id)
    assert ex._agent_available() is True


# --------------------------------------------------------------------------- #
# executor — TC-DEXEC (execute / _enqueue / _update_status)
# --------------------------------------------------------------------------- #
async def test_dexec_execute_agent_unavailable_failed_flow(settings):
    """TC-DEXEC-027 | execute 在 Agent 不可用时产出 FAILED 流并写日志

    输入: engine=None（Agent 不可用），log_sink 记录 entry
    预期输出: 事件含 FAILED 状态；log_sink entry task_state=FAILED 且 message 含 disabled
    断言点: 事件类型 + log_sink entry 字段
    防回归: 若不可用分支删除，会调用 run_flow
    """
    store = {}

    async def sink(entry):
        store["entry"] = entry

    ex = _executor(settings, engine=None, agent_id=None, log_sink=sink)
    queue = _FakeQueue()
    await ex.execute(_ctx_with_template(), queue)
    assert _count(queue.events, Task) == 1
    assert _count(queue.events, TaskStatusUpdateEvent) == 1
    assert store["entry"]["task_state"] == "TASK_STATE_FAILED"
    assert store["entry"]["response_body"]["state"] == "FAILED"
    assert "disabled" in store["entry"]["response_body"]["message"]


async def test_dexec_execute_run_flow_error_failed_flow(settings, monkeypatch):
    """TC-DEXEC-028 | execute 在 run_flow 抛错时产出 FAILED 'internal error' 流

    输入: Agent 可用，monkeypatch run_flow 抛异常
    预期输出: 事件含 FAILED 状态；log_sink entry message 含 'internal error'
    断言点: 事件 + entry message
    防回归: 若 except 删除，异常向上抛
    """
    store = {}

    async def sink(entry):
        store["entry"] = entry

    def boom(*a, **kw):
        raise RuntimeError("flow boom")

    monkeypatch.setattr(executor, "run_flow", boom)
    engine, agent_id = _engine_and_agent(settings)
    ex = _executor(settings, engine=engine, agent_id=agent_id, log_sink=sink)
    queue = _FakeQueue()
    await ex.execute(_ctx_with_template(), queue)
    assert _count(queue.events, TaskStatusUpdateEvent) == 1
    assert store["entry"]["task_state"] == "TASK_STATE_FAILED"
    assert "internal error" in store["entry"]["response_body"]["message"]
    assert "flow boom" in store["entry"]["response_body"]["message"]


async def test_dexec_execute_log_sink_error_swallowed(settings, monkeypatch):
    """TC-DEXEC-029 | execute 在 log_sink 抛错时吞掉异常，仍完成状态更新

    输入: Agent 可用，run_flow 返回 COMPLETED，log_sink 抛异常
    预期输出: 不抛异常，事件含 WORKING/artifact/COMPLETED
    断言点: 事件计数（4）+ log_sink 被调用
    防回归: 若 except 删除，log_sink 异常向上抛
    """
    flag = {"called": False}

    async def sink(entry):
        flag["called"] = True
        raise RuntimeError("sink boom")

    def fake_run_flow(server, flow_env, request, stub_fn, fallback_enabled=True):
        return FlowResult(
            state="COMPLETED", message_text="ok", reply_metadata={}, artifact_data=None, negotiated=False, artifact_text="hi"
        )

    monkeypatch.setattr(executor, "run_flow", fake_run_flow)
    engine, agent_id = _engine_and_agent(settings)
    ex = _executor(settings, engine=engine, agent_id=agent_id, log_sink=sink)
    queue = _FakeQueue()
    await ex.execute(_ctx_with_template(), queue)
    assert flag["called"] is True
    assert _count(queue.events, Task) == 1
    assert _count(queue.events, TaskArtifactUpdateEvent) == 1
    assert _count(queue.events, TaskStatusUpdateEvent) == 2  # WORKING + COMPLETED


async def test_dexec_execute_non_serializable_match_meta_no_trace(settings, monkeypatch):
    """TC-DEXEC-030 | execute 对不可序列化 datasetMatch 跳过 trace 且 _enqueue 回退空元数据

    输入: COMPLETED 流 + _select_stub 设置 datasetMatch={1,2}（不可 JSON 序列化）
    预期输出: 不抛异常；仅 1 个 COMPLETED 状态（trace 为 None，无二次更新）
    断言点: 事件计数 4（无二次状态更新）
    防回归: 若 except 删除，json.dumps(set) 抛 TypeError 向上传播
    """
    def fake_run_flow(server, flow_env, request, stub_fn, fallback_enabled=True):
        stub_fn(request.template_uri)  # _select_stub 写入 retrieval_info['datasetMatch']
        return FlowResult(
            state="COMPLETED", message_text="ok", reply_metadata={}, artifact_data=None, negotiated=False, artifact_text="hi"
        )

    monkeypatch.setattr(executor, "run_flow", fake_run_flow)
    engine, agent_id = _engine_and_agent(settings)
    ex = _executor(settings, engine=engine, agent_id=agent_id)
    ex._select_stub = lambda tpl, pt, info: info.__setitem__("datasetMatch", {1, 2}) or None
    queue = _FakeQueue()
    await ex.execute(_ctx_with_template(), queue)
    assert _count(queue.events, TaskStatusUpdateEvent) == 2  # WORKING + COMPLETED（无二次合并更新）


async def test_dexec_execute_serializable_match_meta_second_update(settings, monkeypatch):
    """TC-DEXEC-031 | execute 对可序列化 datasetMatch 在终态进行二次状态更新（合并 trace 元数据）

    输入: COMPLETED 流 + _select_stub 设置 datasetMatch={'pairId':'p1'}
    预期输出: 产生 3 个状态事件（WORKING + COMPLETED + COMPLETED-merged）+ 1 个 artifact
    断言点: 状态事件计数 3
    防回归: 若二次更新删除，状态事件仅 2 个
    """
    def fake_run_flow(server, flow_env, request, stub_fn, fallback_enabled=True):
        stub_fn(request.template_uri)
        return FlowResult(
            state="COMPLETED", message_text="ok", reply_metadata={}, artifact_data=None, negotiated=False, artifact_text="hi"
        )

    monkeypatch.setattr(executor, "run_flow", fake_run_flow)
    engine, agent_id = _engine_and_agent(settings)
    ex = _executor(settings, engine=engine, agent_id=agent_id)
    ex._select_stub = lambda tpl, pt, info: info.__setitem__("datasetMatch", {"pairId": "p1"}) or None
    queue = _FakeQueue()
    await ex.execute(_ctx_with_template(), queue)
    assert _count(queue.events, TaskStatusUpdateEvent) == 3  # WORKING + COMPLETED + COMPLETED(merged)
    assert _count(queue.events, TaskArtifactUpdateEvent) == 1


async def test_dexec_execute_completed_artifact_data_branch(settings, monkeypatch):
    """TC-DEXEC-032 | execute 在 artifact_text 为空但 artifact_data 存在时走 data 产物分支

    输入: COMPLETED 流，artifact_text=None，artifact_data={'k':'v'}
    预期输出: 产生 1 个 artifact 事件（data 产物）
    断言点: artifact 事件计数 1
    防回归: 若 else 分支删除，无 artifact 事件
    """
    def fake_run_flow(server, flow_env, request, stub_fn, fallback_enabled=True):
        return FlowResult(
            state="COMPLETED",
            message_text="ok",
            reply_metadata={},
            artifact_data={"k": "v"},
            negotiated=False,
            artifact_text=None,
        )

    monkeypatch.setattr(executor, "run_flow", fake_run_flow)
    engine, agent_id = _engine_and_agent(settings)
    ex = _executor(settings, engine=engine, agent_id=agent_id)
    queue = _FakeQueue()
    await ex.execute(_ctx_with_template(), queue)
    assert _count(queue.events, TaskArtifactUpdateEvent) == 1


async def test_dexec_execute_input_required_branch(settings, monkeypatch):
    """TC-DEXEC-033 | execute 在 INPUT_REQUIRED 流时入队 negotiating WORKING 状态

    输入: run_flow 返回 INPUT_REQUIRED
    预期输出: 事件含 SUBMITTED Task + 2 个状态事件（negotiating WORKING + INPUT_REQUIRED）
    断言点: 事件计数与类型
    防回归: 若 INPUT_REQUIRED 分支删除，缺少 negotiating 状态
    """
    def fake_run_flow(server, flow_env, request, stub_fn, fallback_enabled=True):
        return FlowResult(
            state="INPUT_REQUIRED", message_text="need more", reply_metadata={}, artifact_data=None, negotiated=True
        )

    monkeypatch.setattr(executor, "run_flow", fake_run_flow)
    engine, agent_id = _engine_and_agent(settings)
    ex = _executor(settings, engine=engine, agent_id=agent_id)
    queue = _FakeQueue()
    await ex.execute(_ctx_with_template(), queue)
    assert _count(queue.events, Task) == 1
    assert _count(queue.events, TaskStatusUpdateEvent) == 2  # negotiating WORKING + INPUT_REQUIRED
    assert _count(queue.events, TaskArtifactUpdateEvent) == 0


# --------------------------------------------------------------------------- #
# main — TC-MAIN
# --------------------------------------------------------------------------- #
async def test_main_log_sink_writes_request_log(settings):
    """TC-MAIN-001 | _log_sink 在 engine 可用时写入 RequestLog 行

    输入: runtime 含真实 engine + 合法 entry
    预期输出: 数据库新增一条 RequestLog，字段与 entry 一致
    断言点: 回读行 agent_id/template_uri/feature/task_state
    防回归: 若 _write 未 commit 或字段丢失，回读不一致
    """
    engine, _ = _engine_and_agent(settings)
    runtime = {"engine": engine}
    entry = {
        "agent_id": 1,
        "template_uri": "Task-T/x/y",
        "direction": "inbound",
        "feature": "a2at",
        "request_body": {},
        "response_body": {},
        "task_state": "TASK_STATE_COMPLETED",
        "negotiated": False,
        "latency_ms": 5,
    }
    await main._log_sink(runtime, entry)
    with Session(engine) as s:
        log = s.scalar(select(RequestLog).order_by(RequestLog.id.desc()))
    assert log.agent_id == 1
    assert log.template_uri == "Task-T/x/y"
    assert log.feature == "a2at"
    assert log.task_state == "TASK_STATE_COMPLETED"


async def test_main_log_sink_noop_without_engine(settings):
    """TC-MAIN-002 | _log_sink 在 engine 为 None 时直接返回且不写入

    输入: runtime={'engine': None}
    预期输出: 返回 None，RequestLog 行数不变
    断言点: 返回 None + 行数前后一致
    防回归: 若守卫删除，Session(None) 抛错
    """
    engine, _ = _engine_and_agent(settings)
    with Session(engine) as s:
        before = s.scalar(select(RequestLog.id))
    before_count = before if before is not None else 0
    result = await main._log_sink({"engine": None}, {"agent_id": 1})
    assert result is None
    with Session(engine) as s:
        after = s.scalar(select(RequestLog.id))
    after_count = after if after is not None else 0
    assert after_count == before_count


def test_main_public_base_strips_suffix():
    """TC-MAIN-003 | _public_base 仅在以 /debug/a2a 结尾时剥离，否则原样返回

    输入: 'http://h/debug/a2a' 与 'http://h/other'
    预期输出: 'http://h' 与 'http://h/other'
    断言点: 后缀匹配剥离；不匹配原样
    防回归: 若剥离逻辑改坏，URL 拼接错误
    """
    assert main._public_base("http://h/debug/a2a") == "http://h"
    assert main._public_base("http://h/other") == "http://h/other"


def test_main_health_and_healthz_endpoints(client):
    """TC-MAIN-004 | /api/v1/health 与 /healthz 返回 ok

    输入: GET 两个健康端点
    预期输出: 200 + {'status':'ok'}
    断言点: 状态码与响应体
    防回归: 若端点删除，404
    """
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    assert client.get("/healthz").json() == {"status": "ok"}


def test_main_readyz_ok(client):
    """TC-MAIN-005 | /readyz 在 DB 可读时返回 ok

    输入: GET /readyz
    预期输出: 200 + {'status':'ok'}
    断言点: 状态码 + status
    防回归: 若 DB 校验删除，行为变化
    """
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_main_readyz_503_on_db_error(client, monkeypatch):
    """TC-MAIN-006 | /readyz 在 DB 查询异常时返回 503 unavailable

    输入: monkeypatch main.Session 使 scalar 抛异常，GET /readyz
    预期输出: 503 + {'status':'unavailable'} 且 detail 含错误信息
    断言点: 状态码 + status + detail
    防回归: 若异常分支删除，500 而非 503
    """

    class _Boom:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def scalar(self, *a, **kw):
            raise RuntimeError("db down")

    monkeypatch.setattr(main, "Session", _Boom)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unavailable"
    assert "db down" in body["detail"]


def test_main_mounts_non_default_agent_at_startup(tmp_path):
    """TC-MAIN-007 | create_app 启动时为预置的非默认启用 Agent 挂载 A2A 子应用

    输入: 预置数据库含默认 Agent + 一个非默认启用 Agent，create_app
    预期输出: 非默认 agent-card 端点 200 且 name 匹配；默认卡片亦可达
    断言点: 非默认卡片 name + 默认卡片 name
    防回归: 若 _mount_agent 非默认分支删除，非默认卡片 404
    """
    env_path = tmp_path / ".env"
    env_path.write_text(TEST_ENV, encoding="utf-8")
    settings = Settings(
        db_path=tmp_path / "mount.db",
        jwt_secret="s",
        admin_password="admin-pass-01",
        language="zh-CN",
        env_path=env_path,
    )
    engine = make_engine(settings)
    init_db(engine, settings)
    with Session(engine) as s:
        extra = Agent(name="Extra Agent", description="extra", enabled=True)
        s.add(extra)
        s.commit()
        s.refresh(extra)
        extra_id = extra.id
    engine.dispose()
    app = main.create_app(settings)
    with TestClient(app) as c:
        resp = c.get(f"/debug/a2a/agent/{extra_id}/.well-known/agent-card.json")
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Extra Agent"
        default_resp = c.get("/debug/a2a/.well-known/agent-card.json")
        assert default_resp.status_code == 200
        assert default_resp.json()["name"] == "OpenAN Debug Mock Agent"


def test_main_mount_agent_reorders_before_default_route(tmp_path):
    """TC-MAIN-008 | _mount_agent 在默认路由已存在时将非默认路由插入到 /debug/a2a 之前

    输入: create_app（仅默认）后，再 _mount_agent 一个非默认 Agent
    预期输出: 非默认挂载路由出现在 /debug/a2a 之前
    断言点: 路由顺序——非默认 index < 默认 index
    防回归: 若路由重排逻辑删除，非默认路由排在 /debug/a2a 之后
    """
    env_path = tmp_path / ".env"
    env_path.write_text(TEST_ENV, encoding="utf-8")
    settings = Settings(
        db_path=tmp_path / "ro.db",
        jwt_secret="s",
        admin_password="admin-pass-01",
        language="zh-CN",
        env_path=env_path,
    )
    app = main.create_app(settings)
    with Session(app.state.engine) as s:
        extra = Agent(name="Reorder Agent", description="r", enabled=True)
        s.add(extra)
        s.commit()
        s.refresh(extra)
        extra_id = extra.id
    main._mount_agent(app, extra, settings, app.state.flow_env)
    paths = [getattr(r, "path", None) for r in app.router.routes]
    default_idx = paths.index("/debug/a2a")
    extra_idx = paths.index(f"/debug/a2a/agent/{extra_id}")
    assert extra_idx < default_idx


# --------------------------------------------------------------------------- #
# flow_env — TC-FLOW
# --------------------------------------------------------------------------- #
def test_flow_ext_uri_for_mapping():
    """TC-FLOW-001 | ext_uri_for 按前缀映射扩展 URI，未知/空返回 None

    输入: None / 'Task-T/x' / 'Unknown-T/x'
    预期输出: None / Task-T 扩展 URI / None
    断言点: 映射值与 None
    防回归: 若映射表改坏，扩展 URI 错误
    """
    from a2a_t.core.metadata import TASK_T_EXTENSION_URI

    assert flow_env.ext_uri_for(None) is None
    assert flow_env.ext_uri_for("Task-T/x") == TASK_T_EXTENSION_URI
    assert flow_env.ext_uri_for("Unknown-T/x") is None


def test_flow_schema_for_caches():
    """TC-FLOW-002 | schema_for 首次取回后缓存，二次命中缓存不再调用 schema_access

    输入: 同一 templateUri 连续两次 schema_for
    预期输出: 两次返回同一对象，slot_schema 仅调用一次
    断言点: 返回值同一性 + 调用次数
    防回归: 若缓存删除，slot_schema 被调用两次
    """
    sentinel = object()
    calls = []
    fe = object.__new__(flow_env.FlowEnvironment)
    fe._schema_cache = {}
    fe.language = "zh-CN"

    def slot_schema(*a, **kw):
        calls.append(1)
        return sentinel

    fe.schema_access = SimpleNamespace(slot_schema=slot_schema)
    first = fe.schema_for("Task-T/x/y")
    second = fe.schema_for("Task-T/x/y")
    assert first is sentinel
    assert second is sentinel
    assert len(calls) == 1


def test_flow_schema_for_returns_none_on_error():
    """TC-FLOW-003 | schema_for 在 slot_schema 抛异常时返回 None 且不缓存

    输入: slot_schema 抛 RuntimeError
    预期输出: None，且缓存为空
    断言点: 返回 None + 缓存未写入
    防回归: 若 except 删除，异常向上抛
    """
    fe = object.__new__(flow_env.FlowEnvironment)
    fe._schema_cache = {}
    fe.language = "zh-CN"
    fe.schema_access = SimpleNamespace(slot_schema=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no schema")))
    assert fe.schema_for("Task-T/x/y") is None
    assert fe._schema_cache == {}


def test_flow_env_falls_back_on_a2at_failure(monkeypatch, tmp_path):
    """TC-FLOW-004 | A2ATServer 首次构造失败时回退到内置 fallback env 并重试成功

    输入: monkeypatch A2ATServer 首次抛异常
    预期输出: flow_env.a2at 成功构造，fallback 文件已写入，第二次用 fallback 路径
    断言点: a2at 非空 + 第二次 env_path 为 fallback + 文件存在
    防回归: 若回退分支删除，构造直接失败
    """
    monkeypatch.chdir(tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text(TEST_ENV, encoding="utf-8")
    real = flow_env.A2ATServer
    calls = []

    def fake(env_path=None):
        calls.append(str(env_path) if env_path is not None else None)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real(env_path=env_path)

    monkeypatch.setattr(flow_env, "A2ATServer", fake)
    settings = Settings(
        db_path=tmp_path / "x.db",
        jwt_secret="s",
        admin_password="p",
        language="zh-CN",
        env_path=env_path,
    )
    fe = flow_env.FlowEnvironment(settings)
    assert fe.a2at is not None
    assert len(calls) == 2
    assert calls[1].endswith("a2at-fallback.env")
    assert (tmp_path / "data" / "a2at-fallback.env").exists()


# --------------------------------------------------------------------------- #
# db — TC-DB
# --------------------------------------------------------------------------- #
def test_db_init_creates_defaults(settings):
    """TC-DB-001 | init_db 创建默认 admin 用户、默认 Agent、4 个服务设置

    输入: 全新 engine + init_db
    预期输出: users 1 条 admin，agents 1 条默认启用，service_settings 4 条且键集合匹配
    断言点: 行数 + admin 角色 + agent enabled + 设置键集合
    防回归: 若任一初始化删除，行数/字段不符
    """
    engine = make_engine(settings)
    init_db(engine, settings)
    with Session(engine) as s:
        user = s.scalar(select(User).where(User.username == "admin"))
        agents = s.scalars(select(Agent)).all()
        settings_rows = s.scalars(select(ServiceSettings)).all()
    assert user is not None and user.role == "admin"
    assert len(agents) == 1 and agents[0].enabled is True
    assert {r.key for r in settings_rows} == set(db.SERVICE_URL_DEFAULTS)


def test_db_init_migrates_legacy_schema(settings):
    """TC-DB-002 | init_db 对缺 feature 列的遗留 request_logs 执行 ALTER 并提交

    输入: 预建 request_logs 表（无 feature 列），再 init_db
    预期输出: ALTER 成功并 commit，feature 列存在
    断言点: inspector 显示 feature 列存在
    防回归: 若 ALTER/commit 分支删除，遗留表无 feature 列
    """
    engine = make_engine(settings)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE request_logs (id INTEGER PRIMARY KEY, agent_id INTEGER)"))
    init_db(engine, settings)
    columns = {c["name"] for c in inspect(engine).get_columns("request_logs")}
    assert "feature" in columns


def test_db_init_admin_password_none_prints_bootstrap(settings, capsys):
    """TC-DB-003 | init_db 在 admin_password 为 None 时生成密码并打印到 stderr

    输入: settings.admin_password=None，全新 engine
    预期输出: stderr 含 bootstrap 密码行，admin 用户已创建
    断言点: stderr 含 'bootstrap admin user' + admin 用户存在
    防回归: 若 print 删除，stderr 无密码行
    """
    settings.admin_password = None
    engine = make_engine(settings)
    init_db(engine, settings)
    captured = capsys.readouterr()
    assert "bootstrap admin user" in captured.err
    with Session(engine) as s:
        user = s.scalar(select(User).where(User.username == "admin"))
    assert user is not None


# --------------------------------------------------------------------------- #
# a2a_app — TC-A2A
# --------------------------------------------------------------------------- #
async def test_a2a_middleware_delegates_non_http_scope():
    """TC-A2A-001 | EchoExtensionsMiddleware 对非 http scope（如 lifespan）直接转发给下游 app

    输入: scope type='lifespan'
    预期输出: 下游 app 收到原 scope，middleware 直接返回
    断言点: 下游被调用且 scope.type 保持 'lifespan'
    防回归: 若非 http 分支删除，lifespan 被当 http 处理会出错
    """
    seen = {}

    async def inner(scope, receive, send):
        seen["type"] = scope["type"]

    mw = EchoExtensionsMiddleware(inner)
    await mw({"type": "lifespan"}, lambda: None, lambda m: None)
    assert seen["type"] == "lifespan"


async def test_a2a_middleware_echoes_extensions_header():
    """TC-A2A-002 | http 请求带 a2a-extensions 头时响应头回显该扩展

    输入: scope type='http'，headers 含 (b'a2a-extensions', b'ext1')
    预期输出: http.response.start 头包含 (b'a2a-extensions', b'ext1')
    断言点: 响应头回显
    防回归: 若回显逻辑删除，响应无 a2a-extensions
    """
    captured = {}

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        if message["type"] == "http.response.start":
            captured["headers"] = message["headers"]

    async def receive():
        return {"type": "http.request"}

    mw = EchoExtensionsMiddleware(inner)
    await mw({"type": "http", "headers": [(b"a2a-extensions", b"ext1")]}, receive, send)
    assert (b"a2a-extensions", b"ext1") in captured["headers"]


def test_a2a_build_a2a_app_wraps_starlette():
    """TC-A2A-003 | build_a2a_app 返回 EchoExtensionsMiddleware 包装的 Starlette 应用

    输入: 公开 URL + 执行器 + 名称/描述
    预期输出: 返回 EchoExtensionsMiddleware，其内层为 Starlette
    断言点: 返回类型 + 内层 app 类型名
    防回归: 若包装结构改坏，类型不符
    """
    ex = _executor(None)
    app = build_a2a_app("http://h/debug/a2a", ex, agent_name="N", agent_description="D")
    assert isinstance(app, EchoExtensionsMiddleware)
    assert type(app.app).__name__ == "Starlette"
