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

"""协议流/桩服务/校验模型/数据库引导/数据集检索 覆盖率补测。

直接对 mockagent_engine.protocol_flow 的纯逻辑（A2A-T 消息构造与解析）做单测，
不经过 HTTP；并对 stub_service、schemas、db、dataset_retrieval 补齐边界/异常分支。
"""
import threading

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from a2a_t.core.errors.exceptions import (
    A2ATError,
    ContentValidationError,
    ErrorCatalog,
    SlotValidationError,
)
from a2a_t.core.standard_templates import INFORMATION_NEGOTIATION_PROPOSE_URI

from mockagent_engine import dataset_retrieval as dr
from mockagent_engine import protocol_flow as pf
from mockagent_engine.config import Settings
from mockagent_engine.db import SERVICE_URL_DEFAULTS, init_db, make_engine
from mockagent_engine.models import Agent, Base, ServiceSettings, User, Variant
from mockagent_engine.protocol_flow import (
    FlowRequest,
    FlowResult,
    carried_context_from_params,
    detect_missing,
    family_prefix,
    is_llm_failure,
    missing_items_from_errors,
    run_flow,
)
from mockagent_engine.schemas import (
    AgentCreate,
    AgentPatch,
    DebugProxyRequest,
    ServiceUrlsUpdate,
)
from mockagent_engine.stub_service import fill_placeholders, pick_variant

TPL_LIVE = "Task-T/network-layer/live-stream-quality/v1"


# --------------------------------------------------------------------------- #
# 桩对象：A2ATServer / FlowEnvironment / 合规结果 / 参数提取结果
# --------------------------------------------------------------------------- #
class _Failure:
    def __init__(self, code="", message=""):
        self.code = code
        self.message = message


class _Compliance:
    def __init__(self, success=True, failure=None):
        self.success = success
        self.failure = failure


class _Params:
    def __init__(self, data, context=None):
        self.data = data
        self.context = context


class _MetadataContent:
    def __init__(self, payload):
        self._payload = payload

    def build_metadata_content(self):
        return self._payload


class _FakeServer:
    """A2ATServer 桩：可控的合规/校验/协商结果，驱动 run_flow 各分支。"""

    def __init__(self, *, compliance=None, params=None, metadata=None,
                 check_exc=None, validate_exc=None):
        self._compliance = compliance
        self._params = params
        self._metadata = {"negotiation": "propose"} if metadata is None else metadata
        self._check_exc = check_exc
        self._validate_exc = validate_exc
        self.validate_calls = []
        self.propose_args = None

    def check_task_prompt(self, *, processed_prompt_text):
        if self._check_exc is not None:
            raise self._check_exc
        return self._compliance if self._compliance is not None else _Compliance(success=True)

    def _do_validate(self):
        if self._validate_exc is not None:
            raise self._validate_exc
        return self._params

    def validate_notification_prompt_and_data_filling(self, prompt, schema, template_uri):
        self.validate_calls.append(("Notification-T", template_uri))
        return self._do_validate()

    def validate_auth_prompt_and_data_filling(self, prompt, schema, template_uri):
        self.validate_calls.append(("Authorization-T", template_uri))
        return self._do_validate()

    def validate_propose_prompt_and_data_filling(self, prompt, ctx, schema, template_uri):
        self.validate_calls.append(("Negotiation-T", template_uri))
        return self._do_validate()

    def validate_task_prompt_and_data_filling(self, prompt, schema, template_uri):
        self.validate_calls.append(("Task-T", template_uri))
        return self._do_validate()

    def generate_negotiation_propose_prompt_from_data(self, data, uri):
        self.propose_args = (data, uri)
        return _MetadataContent(self._metadata)


class _FakeFlowEnv:
    def __init__(self, schema="schema-stub"):
        self._schema = schema

    def schema_for(self, template_uri):
        return self._schema


def _req(template_uri="Task-T/x/v1", prompt="do something", context=None):
    return FlowRequest(
        template_uri=template_uri,
        prompt_text=prompt,
        negotiation_context=context,
    )


# --------------------------------------------------------------------------- #
# protocol_flow —— 纯函数
# --------------------------------------------------------------------------- #
def test_is_llm_failure_matches_all_markers():
    """TC-FLOW-001 | LLM 失败标记命中返回 True

    输入: 含 LLM_FAILURE_MARKERS 各子串的消息（含大小写与下划线变体）
    预期输出: True
    断言点: 每个标记子串均命中；混合句中也命中
    防回归: 若标记列表被删减或匹配改为大小写敏感，用例变红
    """
    for marker in pf.LLM_FAILURE_MARKERS:
        assert is_llm_failure(marker) is True, marker
    assert is_llm_failure("ERROR: invocation_failed please retry") is True


def test_is_llm_failure_clean_message_returns_false():
    """TC-FLOW-002 | 正常消息与空串返回 False

    输入: "task completed" / ""
    预期输出: False
    断言点: 不含任何失败标记时返回 False
    防回归: 若误把普通文本判为失败，会错误触发 LLM-less 回退
    """
    assert is_llm_failure("task completed successfully") is False
    assert is_llm_failure("") is False


def test_family_prefix_splits_family():
    """TC-FLOW-003 | family_prefix 取模板族前缀

    输入: "Task-T/network-layer/live/v1"
    预期输出: "Task-T"
    断言点: 以首个 / 切分返回前段
    防回归: 若切分逻辑改为按末段，用例变红
    """
    assert family_prefix("Task-T/network-layer/live/v1") == "Task-T"


def test_family_prefix_none_and_no_slash():
    """TC-FLOW-004 | family_prefix 边界：None 与无斜杠

    输入: None / "noslash"
    预期输出: None / "noslash"
    断言点: None 返回 None；无斜杠返回原串
    防回归: 若 None 守卫被删，None.split 会抛 AttributeError
    """
    assert family_prefix(None) is None
    assert family_prefix("noslash") == "noslash"


def test_detect_missing_non_dict_returns_empty():
    """TC-FLOW-005 | detect_missing 非字典入参返回空列表

    输入: 字符串 / None / 列表
    预期输出: []
    断言点: 非 dict 提前返回 []，不迭代
    防回归: 若类型守卫被删，对字符串迭代会逐字符判定并误报
    """
    assert detect_missing("string") == []
    assert detect_missing(None) == []
    assert detect_missing([]) == []


def test_detect_missing_lists_null_and_blank():
    """TC-FLOW-006 | detect_missing 列出空值/空白非上下文键

    输入: {"id":"x","round":1,"maxRounds":5,"a":None,"b":"  ","c":"keep","d":""}
    预期输出: ["a","b","d"]
    断言点: CONTEXT_PARAM_KEYS 排除；None 与空白字符串视为缺失；非空保留
    防回归: 若空白判定被删，"  " 会被漏判
    """
    res = detect_missing(
        {"id": "x", "round": 1, "maxRounds": 5, "a": None, "b": "  ", "c": "keep", "d": ""}
    )
    assert res == ["a", "b", "d"]


class _ErrSlot:
    def __init__(self, slot_name):
        self.slot_name = slot_name


def test_missing_items_from_errors_extracts_and_dedups():
    """TC-FLOW-007 | missing_items_from_errors 提取 slot_name 并去重

    输入: 含 port/port/ticket/None/空白 的错误列表
    预期输出: ["port","ticket"]
    断言点: 去重；过滤 None 与空白；保持出现顺序
    防回归: 若去重或空值过滤被删，结果含重复或空串
    """
    errors = [_ErrSlot("port"), _ErrSlot("port"), _ErrSlot("ticket"), _ErrSlot(None), _ErrSlot("  ")]
    assert missing_items_from_errors(errors) == ["port", "ticket"]


def test_missing_items_from_errors_none_and_empty():
    """TC-FLOW-008 | missing_items_from_errors 边界：None / 空列表

    输入: None / []
    预期输出: []
    断言点: errors 为 None 时不抛错，返回 []
    防回归: 若 `errors or []` 守卫被删，对 None 迭代会抛 TypeError
    """
    assert missing_items_from_errors(None) == []
    assert missing_items_from_errors([]) == []


def test_carried_context_none_and_missing_keys():
    """TC-FLOW-009 | carried_context_from_params 边界：非 dict / 缺键 / 完整

    输入: None / {"id":"x"} / {"round":1} / {"id":"x","round":1}
    预期输出: None / None / None / {"id":"x","round":1}
    断言点: 必须同时含 id 与 round 才返回；否则 None
    防回归: 若键存在性判定被删，缺键时返回残缺字典
    """
    assert carried_context_from_params(None) is None
    assert carried_context_from_params({"id": "x"}) is None
    assert carried_context_from_params({"round": 1}) is None
    assert carried_context_from_params({"id": "x", "round": 1}) == {"id": "x", "round": 1}


def test_carried_context_skips_none_values():
    """TC-FLOW-010 | carried_context_from_params 跳过 None 值

    输入: {"id":"x","round":None,"maxRounds":5} / {"id":None,"round":None}
    预期输出: {"id":"x","maxRounds":5} / None
    断言点: None 值键被剔除；全空时返回 None
    防回归: 若 None 过滤被删，会携带 round:None 进入 NegotiationContext
    """
    assert carried_context_from_params({"id": "x", "round": None, "maxRounds": 5}) == {"id": "x", "maxRounds": 5}
    assert carried_context_from_params({"id": None, "round": None}) is None


# --------------------------------------------------------------------------- #
# protocol_flow —— _stub_result
# --------------------------------------------------------------------------- #
def test_stub_result_failed_when_no_variant():
    """TC-FLOW-011 | _stub_result 桩函数返回 None 时 FAILED

    输入: stub_fn 返回 None
    预期输出: state=FAILED, message 含 "no enabled stub variant" 与模板名
    断言点: state/message/无 artifact；negotiated 透传
    防回归: 若 None 分支被删，会对 None 调 fill_placeholders 抛错
    """
    res = pf._stub_result("Task-T/x/v1", lambda t: None, negotiated=False, fallback=False)
    assert res.state == "FAILED"
    assert "no enabled stub variant" in res.message_text
    assert "Task-T/x/v1" in res.message_text
    assert res.artifact_data is None
    assert res.negotiated is False


def test_stub_result_completed_plain_dict():
    """TC-FLOW-012 | _stub_result 普通字典变体 COMPLETED（非回退）

    输入: stub_fn 返回 {"k":"v"}, fallback=False
    预期输出: state=COMPLETED, message="stub data returned", fallback_used=False
    断言点: artifact_data 回填后仍为 {"k":"v"}；非回退文案
    防回归: 若回退文案分支错位，message 与 fallback_used 不匹配
    """
    res = pf._stub_result("Task-T/x/v1", lambda t: {"k": "v"}, negotiated=True, fallback=False)
    assert res.state == "COMPLETED"
    assert res.message_text == "stub data returned"
    assert res.fallback_used is False
    assert res.artifact_data == {"k": "v"}
    assert res.negotiated is True


def test_stub_result_fallback_message():
    """TC-FLOW-013 | _stub_result 回退模式文案与标记

    输入: stub_fn 返回 {"k":"v"}, fallback=True
    预期输出: message 含 "LLM-less fallback mode", fallback_used=True
    断言点: 回退文案与 fallback_used 一致
    防回归: 若 fallback 三元分支被简化，回退文案丢失
    """
    res = pf._stub_result("Task-T/x/v1", lambda t: {"k": "v"}, negotiated=False, fallback=True)
    assert res.message_text == "stub data returned (LLM-less fallback mode)"
    assert res.fallback_used is True


def test_stub_result_prompt_variant_with_name():
    """TC-FLOW-014 | _stub_result prompt 型变体（带 artifactName）

    输入: stub_fn 返回 {"artifactPrompt":"hello","artifactName":"report.md"}
    预期输出: state=COMPLETED, artifact_text="hello", artifact_name="report.md", artifact_data=None
    断言点: artifactPrompt 型变体走独立分支，落到 artifact_text 而非 artifact_data
    防回归: 若 prompt 型分支被删，artifactPrompt 会进 artifact_data
    """
    res = pf._stub_result("Task-T/x/v1", lambda t: {"artifactPrompt": "hello", "artifactName": "report.md"},
                          negotiated=True, fallback=False)
    assert res.state == "COMPLETED"
    assert res.artifact_text == "hello"
    assert res.artifact_name == "report.md"
    assert res.artifact_data is None
    assert res.fallback_used is False


def test_stub_result_prompt_variant_without_name_and_slot_fill():
    """TC-FLOW-015 | _stub_result prompt 型变体无 name + 槽位回填

    输入: stub_fn 返回 {"artifactPrompt":"{{slots.port}}"}, 无 artifactName, params={"port":"ETH0"}
    预期输出: artifact_text="ETH0", artifact_name=None
    断言点: 缺 name 时 artifact_name=None；fill_placeholders 替换槽位
    防回归: 若 `filled.get("artifactName") or None` 改为直接取，缺键会异常
    """
    res = pf._stub_result("Task-T/x/v1", lambda t: {"artifactPrompt": "{{slots.port}}"},
                          negotiated=False, fallback=True, params={"port": "ETH0"})
    assert res.artifact_text == "ETH0"
    assert res.artifact_name is None
    assert res.fallback_used is True


# --------------------------------------------------------------------------- #
# protocol_flow —— _validate 路由分派
# --------------------------------------------------------------------------- #
def test_validate_routes_task_prefix():
    """TC-FLOW-016 | _validate Task-T 前缀路由到 task 校验

    输入: template_uri="Task-T/foo/v1"
    预期输出: 调用 validate_task_prompt_and_data_filling
    断言点: validate_calls 记录 ("Task-T", uri)
    防回归: 若默认路由改前缀分派错位，会调到其它方法
    """
    server = _FakeServer()
    pf._validate(server, "Task-T/foo/v1", "prompt", "schema")
    assert server.validate_calls == [("Task-T", "Task-T/foo/v1")]


@pytest.mark.parametrize("uri,prefix", [
    ("Notification-T/x/v1", "Notification-T"),
    ("Authorization-T/x/v1", "Authorization-T"),
    ("Negotiation-T/x/v1", "Negotiation-T"),
])
def test_validate_routes_by_family(uri, prefix):
    """TC-FLOW-017 | _validate 按族前缀路由 Notification/Auth/Negotiation

    输入: 三种族前缀的 template_uri
    预期输出: 分别路由到对应 validate_* 方法
    断言点: validate_calls 记录正确族前缀
    防回归: 若族前缀分支被删，全部回落到 task 校验
    """
    server = _FakeServer()
    pf._validate(server, uri, "prompt", "schema")
    assert server.validate_calls == [(prefix, uri)]


def test_validate_default_route_unknown_prefix():
    """TC-FLOW-018 | _validate 未知前缀默认路由到 task 校验

    输入: template_uri="Foo-T/bar/v1"
    预期输出: 调用 validate_task_prompt_and_data_filling
    断言点: validate_calls 记录 ("Task-T", uri)
    防回归: 若默认分支被删，未知前缀会抛 AttributeError
    """
    server = _FakeServer()
    pf._validate(server, "Foo-T/bar/v1", "prompt", "schema")
    assert server.validate_calls == [("Task-T", "Foo-T/bar/v1")]


# --------------------------------------------------------------------------- #
# protocol_flow —— _propose 协商提议
# --------------------------------------------------------------------------- #
def test_propose_input_required_with_carried_context():
    """TC-FLOW-019 | _propose 携带上轮上下文发起提议

    输入: missing=["port","ticket"], carried={"id":"ctx-9","round":2,"maxRounds":5}
    预期输出: state=INPUT_REQUIRED, context.round=3（next_round 2→3）
    断言点: reply_metadata 回传；items 名单与 missing 一致；round 递增
    防回归: 若 next_round 被删，round 不递增；若 items 构造错位，名单失序
    """
    server = _FakeServer(metadata={"neg": "meta"})
    res = pf._propose(server, ["port", "ticket"], {"id": "ctx-9", "round": 2, "maxRounds": 5})
    assert res.state == "INPUT_REQUIRED"
    assert res.reply_metadata == {"neg": "meta"}
    assert res.negotiated is True
    data, uri = server.propose_args
    assert data.context.round == 3
    assert data.context.max_rounds == 5
    assert [it.name for it in data.content.items] == ["port", "ticket"]
    assert data.content.relationship is None
    assert uri == INFORMATION_NEGOTIATION_PROPOSE_URI


def test_propose_input_required_without_carried():
    """TC-FLOW-020 | _propose 无上下文时新建首轮提议

    输入: missing=["a"], carried=None
    预期输出: state=INPUT_REQUIRED, context.round=1, max_rounds=5（默认）
    断言点: 无 carried 走新建分支，round=1
    防回归: 若新建分支被删，None 会触发 .get 报错
    """
    server = _FakeServer()
    res = pf._propose(server, ["a"], None)
    assert res.state == "INPUT_REQUIRED"
    data, _ = server.propose_args
    assert data.context.round == 1
    assert data.context.max_rounds == 5


def test_propose_rejected_on_malformed_round():
    """TC-FLOW-021 | _propose 非法 round 值被拒绝

    输入: carried={"round":"not-a-number"}
    预期输出: state=REJECTED, message 含 "malformed negotiation context"
    断言点: int() 抛 ValueError 被捕获转 REJECTED；不调用 generate 方法
    防回归: 若异常捕获被删，ValueError 会外泄
    """
    server = _FakeServer()
    res = pf._propose(server, [], {"round": "not-a-number"})
    assert res.state == "REJECTED"
    assert "malformed negotiation context" in res.message_text
    assert res.negotiated is True
    assert server.propose_args is None


def test_propose_failed_when_rounds_exhausted():
    """TC-FLOW-022 | _propose 超出最大轮次 FAILED

    输入: carried={"id":"c","round":5,"maxRounds":5}
    预期输出: state=FAILED, message 含 "rounds exhausted" 与 "6/5"
    断言点: next_round 后 6>5 触发 FAILED；不调用 generate 方法
    防回归: 若轮次耗尽判定被删，会继续发起提议
    """
    server = _FakeServer()
    res = pf._propose(server, [], {"id": "c", "round": 5, "maxRounds": 5})
    assert res.state == "FAILED"
    assert "negotiation rounds exhausted" in res.message_text
    assert "6/5" in res.message_text
    assert server.propose_args is None


# --------------------------------------------------------------------------- #
# protocol_flow —— run_flow 主流程
# --------------------------------------------------------------------------- #
def test_run_flow_rejected_missing_template_uri():
    """TC-FLOW-023 | run_flow 缺失 templateUri 直接拒绝

    输入: FlowRequest(template_uri=None, prompt_text="p")
    预期输出: state=REJECTED, message 含 "missing A2A-T metadata"
    断言点: state/message/negotiated=False；stub_fn 不被调用
    防回归: 若空值守卫被删，会进入后续流程并调用 stub_fn
    """
    calls = []

    def stub(t):
        calls.append(t)
        return {"x": 1}

    res = run_flow(_FakeServer(), _FakeFlowEnv(), _req(template_uri=None), stub)
    assert res.state == "REJECTED"
    assert "missing A2A-T metadata" in res.message_text
    assert res.negotiated is False
    assert calls == []


def test_run_flow_rejected_missing_prompt_text():
    """TC-FLOW-024 | run_flow 缺失 prompt 直接拒绝

    输入: FlowRequest(template_uri="Task-T/x/v1", prompt_text="")
    预期输出: state=REJECTED, message 含 "missing A2A-T metadata"
    断言点: 空 prompt 走同一守卫
    防回归: 若只判 template_uri，空 prompt 会漏过
    """
    res = run_flow(_FakeServer(), _FakeFlowEnv(), _req(prompt=""), lambda t: {"x": 1})
    assert res.state == "REJECTED"
    assert "missing A2A-T metadata" in res.message_text


def test_run_flow_canceled_on_reject_performative():
    """TC-FLOW-025 | run_flow 客户端 REJECT 取消协商

    输入: negotiation_context={"performative":"reject"}
    预期输出: state=CANCELED, message="client rejected the negotiation"
    断言点: performative 大小写不敏感；CANCELED 文案
    防回归: 若 performative 判定被删，会继续走校验
    """
    res = run_flow(_FakeServer(), _FakeFlowEnv(), _req(context={"performative": "reject"}),
                   lambda t: {"x": 1})
    assert res.state == "CANCELED"
    assert res.message_text == "client rejected the negotiation"
    assert res.negotiated is True


def test_run_flow_canceled_on_abort_performative():
    """TC-FLOW-026 | run_flow 客户端 ABORT 取消协商

    输入: negotiation_context={"performative":"abort"}
    预期输出: state=CANCELED, message="client aborted the negotiation"
    断言点: ABORT 与 REJECT 文案区分
    防回归: 若两个 performative 文案合并，无法区分取消原因
    """
    res = run_flow(_FakeServer(), _FakeFlowEnv(), _req(context={"performative": "abort"}),
                   lambda t: {"x": 1})
    assert res.state == "CANCELED"
    assert res.message_text == "client aborted the negotiation"


def test_run_flow_schema_none_falls_back_to_stub():
    """TC-FLOW-027 | run_flow 无 schema 时回退桩数据

    输入: schema_for 返回 None, stub_fn 返回 {"k":"v"}
    预期输出: state=COMPLETED, fallback_used=True, artifact_data={"k":"v"}
    断言点: schema None 跳过校验，params None 触发回退桩
    防回归: 若 params None 回退分支被删，会以 params 走后续判定报错
    """
    res = run_flow(_FakeServer(), _FakeFlowEnv(schema=None), _req(), lambda t: {"k": "v"})
    assert res.state == "COMPLETED"
    assert res.fallback_used is True
    assert res.artifact_data == {"k": "v"}


def test_run_flow_compliance_fail_non_llm_rejected():
    """TC-FLOW-028 | run_flow 合规失败且非 LLM 码 → 拒绝

    输入: compliance.success=False, failure.code="schema.mismatch"
    预期输出: state=REJECTED, message 含 "prompt compliance failed" 与 "schema.mismatch"
    断言点: 非 LLM 码不触发回退，直接拒绝
    防回归: 若非 LLM 码误触发回退，会用错数据返回 COMPLETED
    """
    server = _FakeServer(compliance=_Compliance(success=False, failure=_Failure(code="schema.mismatch", message="bad")))
    res = run_flow(server, _FakeFlowEnv(), _req(), lambda t: {"stub": True})
    assert res.state == "REJECTED"
    assert "prompt compliance failed" in res.message_text
    assert "schema.mismatch" in res.message_text
    assert res.negotiated is False


def test_run_flow_compliance_fail_llm_code_falls_back():
    """TC-FLOW-029 | run_flow 合规失败 LLM 码 → 回退桩

    输入: compliance.success=False, failure.code="llm.not_configured", fallback_enabled=True
    预期输出: state=COMPLETED, fallback_used=True
    断言点: LLM 码触发回退；stub 返回数据透传
    防回归: 若 LLM 码回退分支被删，会落到 REJECTED
    """
    server = _FakeServer(compliance=_Compliance(success=False, failure=_Failure(code="llm.not_configured", message="")))
    res = run_flow(server, _FakeFlowEnv(), _req(), lambda t: {"stub": True}, fallback_enabled=True)
    assert res.state == "COMPLETED"
    assert res.fallback_used is True
    assert res.artifact_data == {"stub": True}


def test_run_flow_compliance_fail_llm_code_fallback_disabled_rejected():
    """TC-FLOW-030 | run_flow LLM 码但回退禁用 → 拒绝

    输入: compliance.success=False, failure.code="llm.not_configured", fallback_enabled=False
    预期输出: state=REJECTED, message 含 "prompt compliance failed"
    断言点: 回退禁用时 _fallback 返回 None，回落到拒绝
    防回归: 若 None 判定被删，会对 None 返回 COMPLETED
    """
    server = _FakeServer(compliance=_Compliance(success=False, failure=_Failure(code="llm.not_configured", message="")))
    res = run_flow(server, _FakeFlowEnv(), _req(), lambda t: {"stub": True}, fallback_enabled=False)
    assert res.state == "REJECTED"
    assert "prompt compliance failed" in res.message_text
    assert res.negotiated is False


def test_run_flow_a2at_error_non_llm_rejected():
    """TC-FLOW-031 | run_flow check 抛 A2ATError 非 LLM 码 → 拒绝

    输入: check_task_prompt 抛 A2ATError(code=INFRA_INTERNAL_ERROR)
    预期输出: state=REJECTED, message 含 "prompt check error" 与 "infra.internal_error"
    断言点: 非 LLM 异常码不回退，转拒绝
    防回归: 若异常码判定被删，所有异常都会触发回退
    """
    server = _FakeServer(check_exc=A2ATError("boom", code=ErrorCatalog.INFRA_INTERNAL_ERROR))
    res = run_flow(server, _FakeFlowEnv(), _req(), lambda t: {"stub": True})
    assert res.state == "REJECTED"
    assert "prompt check error" in res.message_text
    assert "infra.internal_error" in res.message_text


def test_run_flow_a2at_error_llm_code_falls_back():
    """TC-FLOW-032 | run_flow check 抛 A2ATError LLM 码 → 回退

    输入: check_task_prompt 抛 A2ATError(code=LLM_NOT_CONFIGURED), fallback_enabled=True
    预期输出: state=COMPLETED, fallback_used=True
    断言点: LLM 异常码触发回退
    防回归: 若异常回退分支被删，LLM 不可用时直接拒绝
    """
    server = _FakeServer(check_exc=A2ATError("not configured", code=ErrorCatalog.LLM_NOT_CONFIGURED))
    res = run_flow(server, _FakeFlowEnv(), _req(), lambda t: {"stub": True}, fallback_enabled=True)
    assert res.state == "COMPLETED"
    assert res.fallback_used is True


def test_run_flow_a2at_error_llm_marker_message_falls_back():
    """TC-FLOW-033 | run_flow check 抛 A2ATError 非 LLM 码但消息含标记 → 回退

    输入: A2ATError(code=INFRA_INTERNAL_ERROR, message="LLM invocation failed")
    预期输出: state=COMPLETED, fallback_used=True
    断言点: is_llm_failure(str(error)) 命中标记触发回退
    防回归: 若消息标记回退分支被删，仅靠错误码会漏判
    """
    server = _FakeServer(check_exc=A2ATError("LLM invocation failed boom", code=ErrorCatalog.INFRA_INTERNAL_ERROR))
    res = run_flow(server, _FakeFlowEnv(), _req(), lambda t: {"stub": True}, fallback_enabled=True)
    assert res.state == "COMPLETED"
    assert res.fallback_used is True


def test_run_flow_validation_llm_code_falls_back():
    """TC-FLOW-034 | run_flow 校验抛 CVE LLM 码 → 回退

    输入: validate 抛 ContentValidationError(code=LLM_RESPONSE_INVALID)
    预期输出: state=COMPLETED, fallback_used=True
    断言点: 校验异常 LLM 码触发回退（即使带 slot_errors）
    防回归: 若校验回退分支被删，LLM 不可用时落到拒绝
    """
    cve = ContentValidationError(
        code=ErrorCatalog.LLM_RESPONSE_INVALID,
        errors=[SlotValidationError(slot_name="port", code="c", message="m")],
    )
    server = _FakeServer(validate_exc=cve)
    res = run_flow(server, _FakeFlowEnv(), _req(), lambda t: {"stub": True}, fallback_enabled=True)
    assert res.state == "COMPLETED"
    assert res.fallback_used is True


def test_run_flow_validation_llm_marker_message_falls_back():
    """TC-FLOW-035 | run_flow 校验抛 CVE 非 LLM 码但消息含标记 → 回退

    输入: ContentValidationError(code=INFRA_INTERNAL_ERROR, message="invocation failed")
    预期输出: state=COMPLETED, fallback_used=True
    断言点: is_llm_failure(str(error)) 命中校验异常回退分支
    防回归: 若校验消息标记回退被删，仅靠错误码漏判
    """
    cve = ContentValidationError(code=ErrorCatalog.INFRA_INTERNAL_ERROR, message="invocation failed boom")
    server = _FakeServer(validate_exc=cve)
    res = run_flow(server, _FakeFlowEnv(), _req(), lambda t: {"stub": True}, fallback_enabled=True)
    assert res.state == "COMPLETED"
    assert res.fallback_used is True


def test_run_flow_validation_no_slots_rejected():
    """TC-FLOW-036 | run_flow 校验抛 CVE 非 LLM 无 slot → 拒绝

    输入: ContentValidationError(code=INFRA_INTERNAL_ERROR) 无 errors
    预期输出: state=REJECTED, message 含 "validation failed"
    断言点: 无 slot_names 时不可发起协商，转拒绝
    防回归: 若无 slot 拒绝分支被删，会以空 missing 发起提议
    """
    cve = ContentValidationError(code=ErrorCatalog.INFRA_INTERNAL_ERROR)
    server = _FakeServer(validate_exc=cve)
    res = run_flow(server, _FakeFlowEnv(), _req(), lambda t: {"stub": True})
    assert res.state == "REJECTED"
    assert "validation failed" in res.message_text
    assert res.negotiated is False


def test_run_flow_validation_with_slots_proposes():
    """TC-FLOW-037 | run_flow 校验抛 CVE 非 LLM 带 slot → 协商提议

    输入: ContentValidationError 带 SlotValidationError(slot_name="port")
    预期输出: state=INPUT_REQUIRED, 提议 items[0].name="port"
    断言点: slot_names 回填 missing 并发起协商
    防回归: 若 slot 回填分支被删，会落到拒绝
    """
    cve = ContentValidationError(
        code=ErrorCatalog.INFRA_INTERNAL_ERROR,
        errors=[SlotValidationError(slot_name="port", code="c", message="m")],
    )
    server = _FakeServer(validate_exc=cve, metadata={"propose": "ok"})
    res = run_flow(server, _FakeFlowEnv(), _req(), lambda t: None)
    assert res.state == "INPUT_REQUIRED"
    assert res.reply_metadata == {"propose": "ok"}
    assert res.negotiated is True
    data, _ = server.propose_args
    assert data.content.items[0].name == "port"


def test_run_flow_missing_params_propose_via_carried_context():
    """TC-FLOW-038 | run_flow 校验通过但缺参 → 由 params 重建上下文发起提议

    输入: validate 返回 params.data={"id":"ctx-1","round":1,"port":None}, carried=None
    预期输出: state=INPUT_REQUIRED, context.round=2（carried_context round 1→next 2）
    断言点: carried 缺省时用 carried_context_from_params(params.data) 重建上下文
    防回归: 若 carried_context 回退分支被删，会用 None 上下文发起首轮提议（round=1）
    """
    server = _FakeServer(params=_Params(data={"id": "ctx-1", "round": 1, "port": None}))
    res = run_flow(server, _FakeFlowEnv(), _req(context=None), lambda t: None)
    assert res.state == "INPUT_REQUIRED"
    data, _ = server.propose_args
    assert data.context.round == 2
    assert data.content.items[0].name == "port"


def test_run_flow_params_list_yields_empty_map():
    """TC-FLOW-039 | run_flow 无缺参且 data 为列表 → 空 params_map 回桩

    输入: validate 返回 params.data=["a","b"]（无缺参）
    预期输出: state=COMPLETED, fallback_used=False, 槽位缺省回填空串
    断言点: 列表型 data 走 params_map={} 分支；stub 拿到空 params
    防回归: 若列表分支被删，会对列表调 .items() 抛错
    """
    server = _FakeServer(params=_Params(data=["a", "b"]))
    res = run_flow(server, _FakeFlowEnv(), _req(), lambda t: {"out": "{{slots.x}}"})
    assert res.state == "COMPLETED"
    assert res.fallback_used is False
    assert res.artifact_data == {"out": ""}


def test_run_flow_params_dict_excludes_context_keys():
    """TC-FLOW-040 | run_flow 无缺参且 data 为字典 → 剔除上下文键后回桩

    输入: params.data={"id":"x","round":1,"maxRounds":5,"port":"ETH0"}
    预期输出: state=COMPLETED, stub 收到 params_map={"port":"ETH0"}, 槽位回填
    断言点: CONTEXT_PARAM_KEYS 被剔除；port 槽位回填 ETH0
    防回归: 若剔除逻辑被删，上下文键会进 params_map 并污染回填
    """
    server = _FakeServer(params=_Params(data={"id": "x", "round": 1, "maxRounds": 5, "port": "ETH0"}))
    res = run_flow(server, _FakeFlowEnv(), _req(), lambda t: {"out": "{{slots.port}}"})
    assert res.state == "COMPLETED"
    assert res.fallback_used is False
    assert res.artifact_data == {"out": "ETH0"}


def test_run_flow_compliance_fail_llm_marker_message_falls_back():
    """TC-FLOW-041 | run_flow 合规失败非 LLM 码但消息含标记 → 回退

    输入: compliance.success=False, failure.code="unknown", failure.message="LLM invocation failed"
    预期输出: state=COMPLETED, fallback_used=True
    断言点: is_llm_failure(message) 命中合规回退分支
    防回归: 若合规消息标记回退被删，仅靠错误码漏判
    """
    server = _FakeServer(compliance=_Compliance(success=False,
                          failure=_Failure(code="unknown", message="LLM invocation failed: timeout")))
    res = run_flow(server, _FakeFlowEnv(), _req(), lambda t: {"stub": True}, fallback_enabled=True)
    assert res.state == "COMPLETED"
    assert res.fallback_used is True


# --------------------------------------------------------------------------- #
# stub_service —— fill_placeholders / pick_variant
# --------------------------------------------------------------------------- #
def test_fill_placeholders_string_slots():
    """TC-FLOW-042 | fill_placeholders 替换字符串槽位

    输入: "port={{slots.port}}", {"port":"ETH0"} / "{{slots.a}}-{{slots.b}}" / 缺槽位
    预期输出: "port=ETH0" / "1-2" / "x="
    断言点: 槽位按 params 回填；缺省为空串
    防回归: 若 sub 回调改为忽略 params，槽位不替换
    """
    assert fill_placeholders("port={{slots.port}}", {"port": "ETH0"}) == "port=ETH0"
    assert fill_placeholders("{{slots.a}}-{{slots.b}}", {"a": "1", "b": "2"}) == "1-2"
    assert fill_placeholders("x={{slots.missing}}", {}) == "x="


def test_fill_placeholders_timestamp_and_uuid():
    """TC-FLOW-043 | fill_placeholders 替换 timestamp 与 uuid 占位符

    输入: "ts={{timestamp}} uid={{uuid}}", {}
    预期输出: 占位符被实际 ISO 时间与 UUID 字符串替换
    断言点: timestamp 可被 fromisoformat 解析；uuid 可被 UUID 解析
    防回归: 若占位符替换分支被删，原样保留 {{timestamp}}
    """
    import uuid as uuidlib
    from datetime import datetime

    out = fill_placeholders("ts={{timestamp}} uid={{uuid}}", {})
    assert "{{timestamp}}" not in out and "{{uuid}}" not in out
    ts_val = out.split("ts=")[1].split(" uid")[0]
    uid_val = out.split("uid=")[1]
    assert datetime.fromisoformat(ts_val).tzinfo is not None
    assert str(uuidlib.UUID(uid_val)) == uid_val


def test_fill_placeholders_list_and_dict_recursion():
    """TC-FLOW-044 | fill_placeholders 递归列表与字典

    输入: ["{{slots.a}}","b",3] / {"k":"{{slots.a}}","n":5}
    预期输出: ["X","b",3] / {"k":"Y","n":5}
    断言点: 列表逐项、字典逐值递归；非字符串原样保留
    防回归: 若 list/dict 分支被删，容器原样返回不替换
    """
    assert fill_placeholders(["{{slots.a}}", "b", 3], {"a": "X"}) == ["X", "b", 3]
    assert fill_placeholders({"k": "{{slots.a}}", "n": 5}, {"a": "Y"}) == {"k": "Y", "n": 5}


def test_fill_placeholders_scalar_passthrough():
    """TC-FLOW-045 | fill_placeholders 标量原样返回

    输入: 42 / None / True
    预期输出: 42 / None / True
    断言点: 非容器非字符串类型直接返回
    防回归: 若缺省分支被删，标量会进 str 分支报错
    """
    assert fill_placeholders(42, {}) == 42
    assert fill_placeholders(None, {}) is None
    assert fill_placeholders(True, {}) is True


def test_pick_variant_none_when_no_variants(tmp_path):
    """TC-FLOW-046 | pick_variant 无匹配变体返回 None

    输入: 空 variants 表，查询不存在的模板
    预期输出: None, cursor 不变
    断言点: 无 enabled 变体时返回 None 且不写 cursor
    防回归: 若 None 分支被删，对空列表取下标会 IndexError
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'pv.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        agent = Agent(name="A", organization="O")
        session.add(agent)
        session.commit()
        session.refresh(agent)
        cursor = {}
        assert pick_variant(session, agent.id, "Task-T/none/v1", cursor) is None
        assert cursor == {}


def test_pick_variant_cycles_in_seq_order(tmp_path):
    """TC-FLOW-047 | pick_variant 按 seq 排序并循环，禁用项排除

    输入: 3 个变体（seq=2/enabled, seq=1/enabled, seq=0/disabled），连续取 3 次
    预期输出: 依次 seq=1、seq=2、再 seq=1（游标回绕，禁用项不参与）
    断言点: order_by(seq,id)；disabled 不返回；cursor 自增并取模回绕
    防回归: 若 enabled 过滤被删，seq=0 会被返回；若回绕被删，第三次 IndexError
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'pv2.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    uri = "Task-T/cycle/v1"
    with Session(engine) as session:
        agent = Agent(name="A", organization="O")
        session.add(agent)
        session.commit()
        session.refresh(agent)
        aid = agent.id
        session.add(Variant(agent_id=aid, template_uri=uri, variant_json={"i": 1}, enabled=True, seq=2))
        session.add(Variant(agent_id=aid, template_uri=uri, variant_json={"i": 2}, enabled=True, seq=1))
        session.add(Variant(agent_id=aid, template_uri=uri, variant_json={"i": 3}, enabled=False, seq=0))
        session.commit()
        cursor = {}
        results = [pick_variant(session, aid, uri, cursor).variant_json for _ in range(4)]
        # order_by(seq,id)：seq=1(i=2) → seq=2(i=1) → 回绕 seq=1 → seq=2（seq=0 禁用被排除）
        assert results == [{"i": 2}, {"i": 1}, {"i": 2}, {"i": 1}]


# --------------------------------------------------------------------------- #
# schemas —— pydantic 校验器
# --------------------------------------------------------------------------- #
def test_agent_create_network_requires_domain():
    """TC-FLOW-048 | AgentCreate 网络层 Agent 必须填子域

    输入: AgentCreate(name="net", layer="network", networkDomain=None)
    预期输出: ValidationError, message 含 "网络层"
    断言点: model_validator 拒绝空子域
    防回归: 若该校验被删，网络层 Agent 无子域会被接受
    """
    with pytest.raises(ValidationError, match="网络层"):
        AgentCreate(name="net", layer="network", networkDomain=None)


def test_agent_create_service_clears_domain():
    """TC-FLOW-049 | AgentCreate 服务层清空子域

    输入: AgentCreate(name="svc", layer="service", networkDomain="wireless")
    预期输出: networkDomain 被置为 None
    断言点: 服务层强制 networkDomain=None
    防回归: 若清空分支被删，服务层会保留误填的子域
    """
    a = AgentCreate(name="svc", layer="service", networkDomain="wireless")
    assert a.networkDomain is None


def test_agent_patch_network_requires_domain():
    """TC-FLOW-050 | AgentPatch 网络层必须填子域

    输入: AgentPatch(layer="network", networkDomain=None)
    预期输出: ValidationError, message 含 "网络层"
    断言点: Patch 路径同样校验子域
    防回归: 若 Patch 校验被删，可把 Agent 改成无子域的网络层
    """
    with pytest.raises(ValidationError, match="网络层"):
        AgentPatch(layer="network", networkDomain=None)


def test_service_urls_rejects_non_http():
    """TC-FLOW-051 | ServiceUrlsUpdate 非 http(s) URL 被拒

    输入: registryUrl="ftp://x"
    预期输出: ValidationError, message 含 "must start with http"
    断言点: field_validator 拒绝非 http(s) 协议
    防回归: 若协议校验被删，任意 scheme 会被接受
    """
    with pytest.raises(ValidationError, match="must start with http"):
        ServiceUrlsUpdate(registryUrl="ftp://x")


def test_service_urls_accepts_http_and_none():
    """TC-FLOW-052 | ServiceUrlsUpdate 接受 http(s) 与 None

    输入: registryUrl="http://rc", orchestrationUrl="https://oc", executionHostUrl=None
    预期输出: 三值原样保留
    断言点: http(s) 通过；None 通过
    防回归: 若 None 守卫被删，None 会触发 startswith 报错
    """
    s = ServiceUrlsUpdate(registryUrl="http://rc", orchestrationUrl="https://oc", executionHostUrl=None)
    assert s.registryUrl == "http://rc"
    assert s.orchestrationUrl == "https://oc"
    assert s.executionHostUrl is None


def test_debug_proxy_rejects_unrooted_path():
    """TC-FLOW-053 | DebugProxyRequest path 必须以 / 开头

    输入: path="no-slash"
    预期输出: ValidationError, message 含 "path must start with"
    断言点: field_validator 拒绝非根路径
    防回归: 若路径校验被删，相对路径会被接受
    """
    with pytest.raises(ValidationError, match="path must start with"):
        DebugProxyRequest(method="GET", path="no-slash")


def test_debug_proxy_accepts_rooted_path_and_method_pattern():
    """TC-FLOW-054 | DebugProxyRequest 合法路径与方法模式

    输入: method="POST", path="/api/x", body={"k":1} / 非法 method
    预期输出: 合法构造成功；非法方法被 pattern 拒绝
    断言点: 根路径通过；method 模式生效
    防回归: 若 method pattern 被删，任意 HTTP 方法会被接受
    """
    d = DebugProxyRequest(method="POST", path="/api/x", body={"k": 1})
    assert d.path == "/api/x"
    assert d.method == "POST"
    with pytest.raises(ValidationError):
        DebugProxyRequest(method="TRACE", path="/x")


# --------------------------------------------------------------------------- #
# db —— 引擎/引导/列迁移/并发
# --------------------------------------------------------------------------- #
def test_init_db_creates_admin_agent_and_settings(tmp_path):
    """TC-FLOW-055 | init_db 首次引导创建 admin/agent/服务设置

    输入: 全新 SQLite 库 + admin_password="admin-pass-1"
    预期输出: 1 个 admin 用户、1 个 agent、4 个服务设置键
    断言点: 用户/Agent/ServiceSettings 落库且内容正确
    防回归: 若引导分支被删，表为空
    """
    settings = Settings(db_path=tmp_path / "init.db", jwt_secret="k" * 40, admin_password="admin-pass-1")
    engine = make_engine(settings)
    init_db(engine, settings)
    with Session(engine) as session:
        admin = session.scalar(select(User).where(User.username == "admin"))
        assert admin is not None and admin.role == "admin"
        assert session.scalar(select(Agent).limit(1)) is not None
        keys = {s.key for s in session.scalars(select(ServiceSettings)).all()}
        assert keys == set(SERVICE_URL_DEFAULTS)


def test_init_db_admin_password_none_prints_bootstrap(tmp_path, capsys):
    """TC-FLOW-056 | init_db 无预设密码时打印随机引导密码

    输入: admin_password=None, 全新库
    预期输出: stderr 含 "bootstrap admin user 'admin' password:"，admin 仍落库
    断言点: 无密码分支生成并打印随机密码；用户创建成功
    防回归: 若打印分支被删，运维无法获得初始密码
    """
    settings = Settings(db_path=tmp_path / "nopw.db", jwt_secret="k" * 40, admin_password=None)
    engine = make_engine(settings)
    init_db(engine, settings)
    captured = capsys.readouterr()
    assert "bootstrap admin user 'admin' password:" in captured.err
    with Session(engine) as session:
        assert session.scalar(select(User).where(User.username == "admin")) is not None


def test_init_db_adds_missing_columns_to_legacy_schema(tmp_path):
    """TC-FLOW-057 | init_db 为旧库补加缺失列（ALTER 成功路径）

    输入: 建表后 DROP 掉 feature/layer/network_domain 三列，再调 init_db
    预期输出: 三列被 ALTER ADD 重新加回
    断言点: PRAGMA table_info 显示三列存在
    防回归: 若 ALTER 成功+commit 分支被删，旧库升级会丢列
    """
    settings = Settings(db_path=tmp_path / "legacy.db", jwt_secret="k" * 40, admin_password="p")
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_request_logs_feature"))
        conn.execute(text("ALTER TABLE request_logs DROP COLUMN feature"))
        conn.execute(text("ALTER TABLE agents DROP COLUMN layer"))
        conn.execute(text("ALTER TABLE agents DROP COLUMN network_domain"))
        conn.commit()
    init_db(engine, settings)
    with engine.connect() as conn:
        cols_req = {row[1] for row in conn.execute(text("PRAGMA table_info(request_logs)"))}
        cols_agt = {row[1] for row in conn.execute(text("PRAGMA table_info(agents)"))}
    assert "feature" in cols_req
    assert "layer" in cols_agt
    assert "network_domain" in cols_agt


def test_init_db_idempotent_no_duplicate_bootstrap(tmp_path):
    """TC-FLOW-058 | init_db 二次调用幂等不产生重复

    输入: 同一库连续调用 init_db 两次
    预期输出: 仍仅 1 个 admin、4 个服务设置键
    断言点: 存在性守卫阻止重复插入；ALTER 重复执行被吞
    防回归: 若存在性守卫被删，二次调用会插重复 admin
    """
    settings = Settings(db_path=tmp_path / "idem.db", jwt_secret="k" * 40, admin_password="p")
    engine = make_engine(settings)
    init_db(engine, settings)
    init_db(engine, settings)
    with Session(engine) as session:
        admins = session.scalars(select(User).where(User.username == "admin")).all()
        assert len(admins) == 1
        keys = {s.key for s in session.scalars(select(ServiceSettings)).all()}
        assert keys == set(SERVICE_URL_DEFAULTS)


def test_init_db_concurrent_bootstrap_no_duplicates(tmp_path):
    """TC-FLOW-059 | 并发 bootstrap 下重复插入被回滚，唯一表不产生重复

    输入: 8 线程经 barrier 同时对同一空库调用 init_db（带 busy timeout 引擎）
    预期输出: 仅 1 个 admin、恰好 4 个服务设置键；无重复
    断言点: 唯一约束冲突的 IntegrityError 被回滚；最终一致
    防回归: 若 IntegrityError 回滚分支被删，并发会落重复 admin/设置
    """
    settings = Settings(db_path=tmp_path / "conc.db", jwt_secret="k" * 40, admin_password="p")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'conc.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)  # 预建表，避免并发 create_all 竞争
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait(timeout=30)
        try:
            init_db(engine, settings)
        except Exception:
            pass  # 锁/冲突异常由 init_db 内部回滚保证最终一致

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with Session(engine) as session:
        admins = session.scalars(select(User).where(User.username == "admin")).all()
        settings_rows = session.scalars(select(ServiceSettings)).all()
        agents = session.scalars(select(Agent)).all()
    assert len(admins) == 1, "唯一用户名约束 + 回滚应保证仅 1 个 admin"
    assert {s.key for s in settings_rows} == set(SERVICE_URL_DEFAULTS), "服务设置去重后应恰好 4 个 key"
    assert len(agents) >= 1


# --------------------------------------------------------------------------- #
# dataset_retrieval —— 边界/异常分支
# --------------------------------------------------------------------------- #
def test_dice_zero_for_empty_sets():
    """TC-FLOW-060 | _dice 空 bigram 集合返回 0.0

    输入: set() vs {"a","b"} / {"a","b"} vs set()
    预期输出: 0.0
    断言点: 任一为空则 Dice=0.0
    防回归: 若空集守卫被删，0 除会抛 ZeroDivisionError
    """
    assert dr._dice(set(), {"a", "b"}) == 0.0
    assert dr._dice({"a", "b"}, set()) == 0.0


def test_search_none_for_empty_inputs():
    """TC-FLOW-061 | search 空 template/prompt 返回 None

    输入: template_uri=None / prompt_text=""
    预期输出: None
    断言点: 空入参提前返回 None
    防回归: 若空值守卫被删，空 prompt 会进入打分并可能误命中
    """
    assert dr.search(None, "x") is None
    assert dr.search("Task-T/x", "") is None


def test_search_below_threshold_short_prompt_returns_none():
    """TC-FLOW-062 | search 低相似度（低于阈值）返回 None

    输入: TPL_LIVE + 短 prompt "直播"（仅 1 个共有 bigram，分数 ~0.003 < 0.12）
    预期输出: None（有候选但 best_score < _MIN_SCORE）
    断言点: 短 prompt 不命中；同模板长 prompt 命中（证阈值生效而非无数据）
    防回归: 若阈值判定被删，低分 prompt 会误返回候选
    """
    assert dr.search(TPL_LIVE, "直播") is None
    assert dr.search(TPL_LIVE, dr.sample_request(TPL_LIVE)) is not None


def test_sample_response_none_for_unknown_template():
    """TC-FLOW-063 | sample_response 未知模板返回 None

    输入: "Task-T/no-such/v1"
    预期输出: None
    断言点: 无匹配模板时遍历结束返回 None
    防回归: 若末尾 None 返回被删，会返回上一条非空响应
    """
    assert dr.sample_response("Task-T/no-such/v1") is None


def test_sample_request_none_for_unknown_template():
    """TC-FLOW-064 | sample_request 未知模板返回 None

    输入: "Task-T/no-such/v1"
    预期输出: None
    断言点: 无匹配模板时遍历结束返回 None
    防回归: 若末尾 None 返回被删，会返回上一条非空请求
    """
    assert dr.sample_request("Task-T/no-such/v1") is None


def test_adapt_skips_kind_absent_in_response():
    """TC-FLOW-065 | adapt 跳过响应中缺失的标识类型

    输入: 请求含 ticket+uuid；响应含 ticket 无 uuid
    预期输出: ticket 被请求值替换；uuid 类型因响应无值被跳过，不注入
    断言点: 请求 ticket 落入响应；旧 ticket 移除；请求 uuid 不被注入
    防回归: 若 `if not resp_values: continue` 被删，对空列表取下标会 IndexError
    """
    request = "ticket CMCC-GZ-TSCLX-20260925-77777 and uuid 12345678-1234-5678-1234-567812345678"
    response = "diag: ticket CMCC-GZ-TSCLX-20260925-99999 resolved"
    out = dr.adapt(response, request)
    assert "77777" in out
    assert "99999" not in out
    assert "12345678" not in out  # 响应无 uuid -> 该类型跳过，不注入请求 uuid


def test_load_skips_missing_dataset_file(monkeypatch):
    """TC-FLOW-066 | _load 跳过不可读的数据集文件

    输入: DATASET_FILES 含一个不存在的文件 + 正常 seed 文件；重置缓存
    预期输出: _load 返回非空（seed 文件加载，缺失文件被 OSError 跳过）
    断言点: 缺失文件不致整体失败；正常文件仍加载
    防回归: 若 except 分支被删，缺失文件会让 _load 抛 OSError 中断
    """
    monkeypatch.setattr(dr, "DATASET_FILES", (("missing", "no-such-file.json"), ("seed", "demo_dataset.json")))
    dr._INDEX = None
    try:
        index = dr._load()
        assert len(index) > 0
    finally:
        dr._INDEX = None  # 复位缓存，使后续用例按真实文件重新加载


def test_agent_patch_non_network_preserves_domain():
    """TC-FLOW-067 | AgentPatch 非网络层保留子域并正常返回

    输入: AgentPatch(layer="service", networkDomain="wireless")
    预期输出: 无异常，networkDomain 保留 "wireless"
    断言点: 非网络层不触发校验直接返回；Patch 不清空子域
    防回归: 若 _check_group 误提前 raise 或漏 return，构造失败或丢值
    """
    p = AgentPatch(layer="service", networkDomain="wireless")
    assert p.networkDomain == "wireless"
    assert p.layer == "service"
    # layer 缺省（None）同样不触发校验
    assert AgentPatch(description="x").description == "x"


def test_search_and_samples_boundary_paths():
    """TC-FLOW-068 | 数据集检索无候选/空入参/成功取样/空响应守卫

    输入: 未知模板搜索 / None 模板取样 / 真实模板取样 / 空响应 adapt
    预期输出: 无候选返回 None；None 模板返回 None；真实模板返回非空；空响应原样返回
    断言点: 各边界分支的返回值类型与内容
    防回归: 若无候选/空守卫/成功返回分支被删，对应路径报错或误命中
    """
    assert dr.search("Task-T/no-such/v1", "anything") is None  # 无同模板候选
    assert dr.sample_response(None) is None
    assert dr.sample_request(None) is None
    resp = dr.sample_response(TPL_LIVE)
    req = dr.sample_request(TPL_LIVE)
    assert resp and len(resp) > 20
    assert req and len(req) > 20
    assert dr.adapt("", "request") == ""  # 空响应守卫原样返回


def test_init_db_settings_commit_rolls_back_duplicate(tmp_path, monkeypatch):
    """TC-FLOW-069 | init_db 服务设置提交遇唯一冲突时回滚（不落库）

    输入: 关闭 session autoflush + SERVICE_URL_DEFAULTS 迭代产出重复键，使 settings 循环
          内对同一 key 产生两次 add（autoflush 关闭使第二次存在性检查看不到 pending add）
    预期输出: settings 提交抛 IntegrityError 被回滚 -> 无 service_settings 落库；
             admin/agent 因各自独立提交仍落库；init_db 不外泄异常
    断言点: service_settings 为空（回滚生效）；admin 与 agent 存在；调用不抛错
    防回归: 若 `except IntegrityError: rollback()` 被删，IntegrityError 外泄致 init_db 抛错
    """
    import mockagent_engine.db as dbm
    from sqlalchemy.orm import Session as _RealSession

    settings = Settings(db_path=tmp_path / "dup.db", jwt_secret="k" * 40, admin_password="p")
    engine = make_engine(settings)

    class _NoFlushSession(_RealSession):
        def __init__(self, *a, **kw):
            super().__init__(*a, autoflush=False, **kw)

    class _DupDefaults:
        def items(self):
            return [("registry_url", "http://rc"), ("registry_url", "http://rc2"), ("ontology_url", "http://ot")]

    monkeypatch.setattr(dbm, "Session", _NoFlushSession)
    monkeypatch.setattr(dbm, "SERVICE_URL_DEFAULTS", _DupDefaults())
    init_db(engine, settings)  # IntegrityError 被内部回滚，不外泄
    with Session(engine) as session:  # 真实 Session 查验落库（不受 monkeypatch 影响）
        assert session.scalar(select(User).where(User.username == "admin")) is not None
        assert session.scalar(select(Agent).limit(1)) is not None
        assert session.scalars(select(ServiceSettings)).all() == []  # 回滚 -> 无设置落库
