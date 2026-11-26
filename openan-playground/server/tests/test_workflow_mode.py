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

import pytest

from openan_debug import workflow_mode


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_wf_cache():
    workflow_mode._WF_CACHE.clear()
    yield
    workflow_mode._WF_CACHE.clear()


def _make_async_psop(events):
    async def _gen(**kwargs):
        for ev in events:
            yield ev

    return _gen


# ===========================================================================
# workflow_mode
# ===========================================================================


# ---------------------------------------------------------------------------
# workflow_mode — load_builtin / list_builtin
# ---------------------------------------------------------------------------


def test_load_builtin_cache_hit():
    """TC-DWF-001 | 缓存命中时直接返回缓存值

    输入: _WF_CACHE 已含 workflow_id
    预期输出: 返回缓存 dict（不读文件）
    断言点: 返回值 identity 等于缓存值
    防回归: 若缓存逻辑被删，可能读取文件并返回不同对象
    """
    cached = {"id": "cached-wf", "steps": []}
    workflow_mode._WF_CACHE["cached-wf"] = cached
    assert workflow_mode.load_builtin("cached-wf") is cached


def test_load_builtin_not_found_returns_none():
    """TC-DWF-002 | 不存在的 workflow_id 返回 None

    输入: 不存在的 workflow_id（缓存已清空）
    预期输出: None
    断言点: 返回值为 None
    防回归: 若文件未找到时未返回 None，本用例失败
    """
    assert workflow_mode.load_builtin("no-such-workflow-xyz") is None


def test_load_builtin_from_file():
    """TC-DWF-003 | 从文件加载内置工作流 live-assurance-demo

    输入: workflow_id="live-assurance-demo"（缓存已清空）
    预期输出: 返回 dict 含 id/steps
    断言点: 返回值 id 正确，steps 非空，且被写入缓存
    防回归: 若文件加载逻辑被破坏，本用例失败
    """
    data = workflow_mode.load_builtin("live-assurance-demo")
    assert data is not None
    assert data["id"] == "live-assurance-demo"
    assert len(data["steps"]) >= 4
    assert data["id"] in workflow_mode._WF_CACHE or "live-assurance-demo" in workflow_mode._WF_CACHE


def test_list_builtin_returns_entries():
    """TC-DWF-004 | list_builtin 返回内置工作流列表

    输入: 无
    预期输出: 列表含 live-assurance-demo 条目（id/name/description）
    断言点: 条目 id/name/description 非空
    防回归: 若遍历逻辑或字段提取错误，本用例失败
    """
    result = workflow_mode.list_builtin()
    assert isinstance(result, list)
    assert len(result) >= 1
    entry = next(r for r in result if r["id"] == "live-assurance-demo")
    assert entry["name"] == "直播业务保障演示工作流"
    assert "业务保障" in entry["description"]


def test_list_builtin_skips_malformed_json(monkeypatch):
    """TC-DWF-034 | list_builtin 跳过 JSON 解析失败的文件（except ValueError: continue）

    输入: monkeypatch json.loads 抛出 ValueError
    预期输出: 返回空列表（每个文件被 except ValueError 跳过）
    断言点: 返回空列表，不抛异常
    防回归: 若 except ValueError 分支被删，ValueError 向上传播
    """

    def _bad_json(*a, **kw):
        raise ValueError("malformed")

    monkeypatch.setattr(workflow_mode.json, "loads", _bad_json)
    assert workflow_mode.list_builtin() == []


def test_list_builtin_handles_oserror(monkeypatch):
    """TC-DWF-035 | list_builtin 遇 OSError 时返回空列表（except OSError: pass）

    输入: monkeypatch importlib_resources.files 抛出 OSError
    预期输出: 返回空列表，不抛异常
    断言点: 返回空列表
    防回归: 若 except OSError 分支被删，异常向上传播
    """

    def _raise_oserror(*a, **kw):
        raise OSError("cannot access package")

    monkeypatch.setattr(workflow_mode.importlib_resources, "files", _raise_oserror)
    assert workflow_mode.list_builtin() == []


def test_agent_cards_for_builds_matching_cards():
    """TC-DWF-005 | 为工作流引用的 Agent 构建 A2A 卡

    输入: workflow_dict 引用 Agent A/B，define 含对应实例
    预期输出: 两张卡，name/url/description/version/capabilities 正确
    断言点: 卡数量=2，name 集合匹配，url 含端口号
    防回归: 若卡构建逻辑或字段映射错误，本用例失败
    """
    workflow_dict = {"steps": [
        {"name": "s1", "subtasks": [{"agent": "Agent A"}]},
        {"name": "s2", "subtasks": [{"agent": "Agent B"}]},
    ]}
    define = {"instances": [
        {"agentName": "Agent A", "port": 9001, "description": "desc A"},
        {"agentName": "Agent B", "port": 9002, "description": "desc B"},
    ]}
    cards = workflow_mode.agent_cards_for(workflow_dict, define)
    assert len(cards) == 2
    names = {c["name"] for c in cards}
    assert names == {"Agent A", "Agent B"}
    card_a = next(c for c in cards if c["name"] == "Agent A")
    assert card_a["description"] == "desc A"
    assert card_a["version"] == "1.0.0"
    assert card_a["capabilities"] == {"streaming": False}
    assert card_a["supportedInterfaces"][0]["url"] == "http://127.0.0.1:9001/"
    assert card_a["supportedInterfaces"][0]["protocolBinding"] == "HTTP+JSON"


def test_agent_cards_for_missing_agents_not_in_cards():
    """TC-DWF-006 | 工作流引用但 define 中无对应实例的 Agent 不生成卡

    输入: workflow 引用 Agent A 和 Missing Agent，define 仅含 Agent A
    预期输出: 仅 1 张卡（Agent A）
    断言点: 卡数量=1，Missing Agent 不在卡列表中
    防回归: 若 missing 检测逻辑被破坏，可能生成空卡
    """
    workflow_dict = {"steps": [
        {"name": "s1", "subtasks": [{"agent": "Agent A"}]},
        {"name": "s2", "subtasks": [{"agent": "Missing Agent"}]},
    ]}
    define = {"instances": [{"agentName": "Agent A", "port": 9001}]}
    cards = workflow_mode.agent_cards_for(workflow_dict, define)
    assert len(cards) == 1
    assert cards[0]["name"] == "Agent A"


def test_agent_cards_for_name_fallback_and_default_port():
    """TC-DWF-007 | 实例无 agentName 时用 name 回退，无 port 时默认 9300

    输入: define 实例只有 name，无 port
    预期输出: 卡 name 取自 name 字段，url 端口为 9300
    断言点: name 正确，url 含 9300
    防回归: 若 name 回退或默认端口逻辑被破坏，本用例失败
    """
    workflow_dict = {"steps": [{"name": "s1", "subtasks": [{"agent": "Named Agent"}]}]}
    define = {"instances": [{"name": "Named Agent", "description": "via name"}]}
    cards = workflow_mode.agent_cards_for(workflow_dict, define)
    assert len(cards) == 1
    assert cards[0]["name"] == "Named Agent"
    assert cards[0]["supportedInterfaces"][0]["url"] == "http://127.0.0.1:9300/"


def test_agent_cards_for_no_subtasks_no_cards():
    """TC-DWF-008 | 步骤无 subtasks 时不产生 needed Agent

    输入: workflow 步骤无 subtasks
    预期输出: 空卡列表
    断言点: 返回空列表
    防回归: 若无 subtasks 时误添加 Agent，本用例失败
    """
    workflow_dict = {"steps": [{"name": "s1", "step_type": "SelfLoop"}]}
    define = {"instances": []}
    assert workflow_mode.agent_cards_for(workflow_dict, define) == []


# ---------------------------------------------------------------------------
# workflow_mode — _summarize_upstream
# ---------------------------------------------------------------------------


def test_summarize_upstream_with_results():
    """TC-DWF-009 | 有上游结果时汇总为 "[step] output" 格式

    输入: WorkflowInput 含一条 UpstreamStepResult，其 task_results[0].outputs=("out-1",)
    预期输出: "[up-step] out-1"
    断言点: 返回字符串完全匹配
    防回归: 若格式化逻辑或字段访问错误，本用例失败
    """
    from workflow_engine import TaskExecutionResult, TaskStatus, UpstreamStepResult, WorkflowInput

    tr = TaskExecutionResult(
        agent_name="a1", skill="s1", task_id="t1", task_description="d1",
        status=TaskStatus.SUCCESS, outputs=("out-1",),
    )
    upstream = UpstreamStepResult(step_name="up-step", task_results=(tr,))
    wi = WorkflowInput(upstream_results=(upstream,))
    assert workflow_mode._summarize_upstream(wi) == "[up-step] out-1"


def test_summarize_upstream_empty():
    """TC-DWF-010 | 无上游结果时返回空字符串

    输入: 空 WorkflowInput
    预期输出: ""
    断言点: 返回值为空字符串
    防回归: 若空输入处理错误，本用例失败
    """
    from workflow_engine import WorkflowInput

    assert workflow_mode._summarize_upstream(WorkflowInput()) == ""


def test_summarize_upstream_truncates_long_output():
    """TC-DWF-011 | 上游输出超 160 字符时截断至 160

    输入: UpstreamStepResult 含 outputs=("x"*200,)
    预期输出: "[step] " + "x"*160
    断言点: 输出部分长度恰好 160
    防回归: 若截断逻辑被删，输出为 200 字符
    """
    from workflow_engine import TaskExecutionResult, TaskStatus, UpstreamStepResult, WorkflowInput

    tr = TaskExecutionResult(
        agent_name="a1", skill="s1", task_id="t1", task_description="d1",
        status=TaskStatus.SUCCESS, outputs=("x" * 200,),
    )
    upstream = UpstreamStepResult(step_name="long-step", task_results=(tr,))
    wi = WorkflowInput(upstream_results=(upstream,))
    summary = workflow_mode._summarize_upstream(wi)
    assert summary == f"[long-step] {'x' * 160}"


# ---------------------------------------------------------------------------
# workflow_mode — MockWorkflowControlPoint
# ---------------------------------------------------------------------------


def test_control_point_on_task_known_agent(monkeypatch):
    """TC-DWF-012 | on_task 已知 Agent：构建 metadata+extensions

    输入: agent_name=无线域打桩 Agent，monkeypatch sample_request 返回 fake-prompt
    预期输出: MessageContent.metadata 含 templateUri+ext_uri=prompt，extensions 含 ext_uri
    断言点: metadata 内容、extensions 内容、part.text=instruction
    防回归: 若模板映射或 metadata 构建逻辑错误，本用例失败
    """
    from a2a.types import Part
    from workflow_engine import BusinessInput, TaskRequest

    monkeypatch.setattr(
        workflow_mode.dataset_retrieval, "sample_request", lambda uri: "fake-prompt"
    )
    cp = workflow_mode.MockWorkflowControlPoint("test-intent")
    request = TaskRequest(
        execution_id="e1", task_id="t1", input=BusinessInput.from_text("input"),
        agent_name="无线域打桩 Agent", skill="stub", instruction="diagnose cell",
        step_name="无线小区保障",
    )
    result = asyncio.run(cp.on_task(request))
    ext_uri = workflow_mode.EXT_URIS["Task-T"]
    assert result.metadata["templateUri"] == "Task-T/network-layer/wireless-cell-diagnosis/v1"
    assert result.metadata[ext_uri] == "fake-prompt"
    assert ext_uri in result.extensions
    assert result.parts[0].text == "diagnose cell"


def test_control_point_on_task_unknown_agent():
    """TC-DWF-013 | on_task 未知 Agent：无 template_uri，metadata/extensions 为空

    输入: agent_name 不在 AGENT_TEMPLATE_MAP 中
    预期输出: metadata 为空，extensions 为空，part.text=instruction
    断言点: metadata 空字典、extensions 空 frozenset
    防回归: 若未知 Agent 误生成 metadata，本用例失败
    """
    from workflow_engine import BusinessInput, TaskRequest

    cp = workflow_mode.MockWorkflowControlPoint("test-intent")
    request = TaskRequest(
        execution_id="e1", task_id="t1", input=BusinessInput.from_text("input"),
        agent_name="Unknown Agent", skill="s", instruction="do something",
        step_name="step1",
    )
    result = asyncio.run(cp.on_task(request))
    assert dict(result.metadata) == {}
    assert len(result.extensions) == 0
    assert result.parts[0].text == "do something"


def test_control_point_on_task_with_upstream(monkeypatch):
    """TC-DWF-014 | on_task 含上游结果时 instruction 追加上游摘要

    输入: request.workflow_input 含上游结果，known agent
    预期输出: part.text 含 "上游步骤结果" 与上游摘要
    断言点: part.text 包含上游步骤名与输出
    防回归: 若上游追加逻辑被删，part.text 不含上游
    """
    from workflow_engine import (
        BusinessInput, TaskExecutionResult, TaskRequest, TaskStatus,
        UpstreamStepResult, WorkflowInput,
    )

    monkeypatch.setattr(
        workflow_mode.dataset_retrieval, "sample_request", lambda uri: "fp"
    )
    tr = TaskExecutionResult(
        agent_name="a1", skill="s1", task_id="t1", task_description="d1",
        status=TaskStatus.SUCCESS, outputs=("upstream-output",),
    )
    upstream = UpstreamStepResult(step_name="prev-step", task_results=(tr,))
    wi = WorkflowInput(upstream_results=(upstream,))
    cp = workflow_mode.MockWorkflowControlPoint("test-intent")
    request = TaskRequest(
        execution_id="e1", task_id="t1", input=BusinessInput.from_text("input"),
        agent_name="无线域打桩 Agent", skill="s", instruction="base instruction",
        step_name="step1", workflow_input=wi,
    )
    result = asyncio.run(cp.on_task(request))
    text = result.parts[0].text
    assert text.startswith("base instruction")
    assert "上游步骤结果" in text
    assert "[prev-step] upstream-output" in text


def test_control_point_on_task_sample_request_none_falls_back(monkeypatch):
    """TC-DWF-015 | on_task sample_request 返回 None 时 prompt 回退为 instruction

    输入: known agent，sample_request 返回 None
    预期输出: metadata[ext_uri] = instruction（非 None）
    断言点: metadata[ext_uri] 等于 instruction 文本
    防回归: 若 `or instruction` 回退被删，metadata[ext_uri] 为 None
    """
    from workflow_engine import BusinessInput, TaskRequest

    monkeypatch.setattr(
        workflow_mode.dataset_retrieval, "sample_request", lambda uri: None
    )
    cp = workflow_mode.MockWorkflowControlPoint("test-intent")
    request = TaskRequest(
        execution_id="e1", task_id="t1", input=BusinessInput.from_text("input"),
        agent_name="无线域打桩 Agent", skill="s", instruction="fallback instruction",
        step_name="step1",
    )
    result = asyncio.run(cp.on_task(request))
    ext_uri = workflow_mode.EXT_URIS["Task-T"]
    assert result.metadata[ext_uri] == "fallback instruction"


def test_control_point_on_task_intent_fallback():
    """TC-DWF-016 | on_task instruction 空+input.text=None 时回退到 self._intent

    输入: instruction=""，input 用 data（text=None），agent 未知
    预期输出: part.text == self._intent
    断言点: part.text 等于构造时传入的 intent
    防回归: 若 intent 回退链被破坏，part.text 为空
    """
    from workflow_engine import BusinessInput, TaskRequest

    cp = workflow_mode.MockWorkflowControlPoint("fallback-intent")
    request = TaskRequest(
        execution_id="e1", task_id="t1", input=BusinessInput.from_data({"k": "v"}),
        agent_name="Unknown Agent", skill="s", instruction="",
        step_name="step1",
    )
    result = asyncio.run(cp.on_task(request))
    assert result.parts[0].text == "fallback-intent"


def test_control_point_on_self_task_intent_step():
    """TC-DWF-017 | on_self_task 意图步骤返回意图解析结果

    输入: step_name 含 "意图"
    预期输出: TaskResult.succeeded，output 含 "意图解析结果" 和 intent
    断言点: result.success=True，output 含关键字
    防回归: 若意图分支被删，output 不含 "意图解析结果"
    """
    from workflow_engine import BusinessInput, TaskRequest

    cp = workflow_mode.MockWorkflowControlPoint("my-intent", "zh-CN")
    request = TaskRequest(
        execution_id="e1", task_id="t1", input=BusinessInput.from_text("input"),
        agent_name="a", skill="s", instruction="i", step_name="意图解析",
    )
    result = asyncio.run(cp.on_self_task(request))
    assert result.success is True
    assert len(result.outputs) == 1
    output_text = str(result.outputs[0])
    assert "意图解析结果" in output_text
    assert "my-intent" in output_text


def test_control_point_on_self_task_aggregation_with_upstream():
    """TC-DWF-018 | on_self_task 聚合步骤含上游输出

    输入: step_name 不含 "意图"，workflow_input 含上游结果
    预期输出: TaskResult.succeeded，output 含 "[step]" 和上游输出
    断言点: output 含上游步骤名与输出内容
    防回归: 若聚合分支被删，output 不含上游内容
    """
    from workflow_engine import (
        BusinessInput, TaskExecutionResult, TaskRequest, TaskStatus,
        UpstreamStepResult, WorkflowInput,
    )

    tr = TaskExecutionResult(
        agent_name="a1", skill="s1", task_id="t1", task_description="d1",
        status=TaskStatus.SUCCESS, outputs=("agg-output",),
    )
    upstream = UpstreamStepResult(step_name="agg-step", task_results=(tr,))
    wi = WorkflowInput(upstream_results=(upstream,))
    cp = workflow_mode.MockWorkflowControlPoint("my-intent")
    request = TaskRequest(
        execution_id="e1", task_id="t1", input=BusinessInput.from_text("input"),
        agent_name="a", skill="s", instruction="i", step_name="结果聚合",
        workflow_input=wi,
    )
    result = asyncio.run(cp.on_self_task(request))
    assert result.success is True
    output_text = str(result.outputs[0])
    assert "聚合结果" in output_text
    assert "[agg-step]" in output_text
    assert "agg-output" in output_text


def test_control_point_on_self_task_aggregation_no_upstream():
    """TC-DWF-019 | on_self_task 聚合步骤无上游输出时返回占位文本

    输入: step_name 不含 "意图"，workflow_input 为空
    预期输出: TaskResult.succeeded，output 含 "（无上游输出）"
    断言点: output 含占位文本
    防回归: 若无上游分支处理错误，output 不含占位文本
    """
    from workflow_engine import BusinessInput, TaskRequest

    cp = workflow_mode.MockWorkflowControlPoint("my-intent")
    request = TaskRequest(
        execution_id="e1", task_id="t1", input=BusinessInput.from_text("input"),
        agent_name="a", skill="s", instruction="i", step_name="结果聚合",
    )
    result = asyncio.run(cp.on_self_task(request))
    assert result.success is True
    assert "（无上游输出）" in str(result.outputs[0])


def test_control_point_on_route_allows():
    """TC-DWF-020 | on_route 无条件返回 allow

    输入: RouteRequest
    预期输出: RouteDecision.allowed=True，reason 含 "unconditional"
    断言点: allowed=True + reason 关键字
    防回归: 若 on_route 返回 deny，本用例失败
    """
    from workflow_engine import RouteRequest, WorkflowInput

    cp = workflow_mode.MockWorkflowControlPoint("intent")
    request = RouteRequest(
        execution_id="e1", step_name="s1", next_step="s2",
        condition="cond", workflow_input=WorkflowInput(), current_results=(),
    )
    result = asyncio.run(cp.on_route(request))
    assert result.allowed is True
    assert "unconditional" in result.reason


# ---------------------------------------------------------------------------
# workflow_mode — _collect_events / run_workflow_sync
# ---------------------------------------------------------------------------


def test_collect_events_breaks_on_complete(monkeypatch):
    """TC-DWF-021 | _collect_events 遇 complete 事件时停止收集

    输入: execute_psop 返回 step_start + complete + 额外事件
    预期输出: events 仅含前两个（complete 后 break）
    断言点: events 长度=2，末尾事件 type=complete
    防回归: 若 break 逻辑被删，会收集全部 3 个事件
    """
    monkeypatch.setattr(workflow_mode, "execute_psop", _make_async_psop([
        {"type": "step_start", "data": {"step": "s1"}},
        {"type": "complete", "data": {}},
        {"type": "step_start", "data": {"step": "s2"}},
    ]))
    result = asyncio.run(workflow_mode._collect_events({}, [], "intent"))
    assert len(result["events"]) == 2
    assert result["events"][-1]["type"] == "complete"


def test_collect_events_breaks_on_error(monkeypatch):
    """TC-DWF-022 | _collect_events 遇 error 事件时停止收集

    输入: execute_psop 返回 error + 额外事件
    预期输出: events 仅含 error（后 break）
    断言点: events 长度=1，type=error
    防回归: 若 error break 被删，会收集更多事件
    """
    monkeypatch.setattr(workflow_mode, "execute_psop", _make_async_psop([
        {"type": "error", "data": {"error": "boom"}},
        {"type": "complete", "data": {}},
    ]))
    result = asyncio.run(workflow_mode._collect_events({}, [], "intent"))
    assert len(result["events"]) == 1
    assert result["events"][0]["type"] == "error"


def test_collect_events_no_terminal_collects_all(monkeypatch):
    """TC-DWF-023 | _collect_events 无 complete/error 时收集全部事件

    输入: execute_psop 返回多个非终止事件
    预期输出: events 含全部事件
    断言点: events 长度=3
    防回归: 若无终止事件时提前停止，长度不符
    """
    monkeypatch.setattr(workflow_mode, "execute_psop", _make_async_psop([
        {"type": "step_start", "data": {"step": "s1"}},
        {"type": "agent_request", "data": {"agent": "A"}},
        {"type": "task_response", "data": {"step": "s1", "outputs": ["ok"]}},
    ]))
    result = asyncio.run(workflow_mode._collect_events({}, [], "intent"))
    assert len(result["events"]) == 3


def test_run_workflow_sync_returns_events(monkeypatch):
    """TC-DWF-024 | run_workflow_sync 同步执行并返回 events dict

    输入: execute_psop 返回 step_start + complete
    预期输出: {"events": [...]} 长度=2
    断言点: 返回 dict 含 events 键，长度正确
    防回归: 若 asyncio.run 包装逻辑错误，本用例失败
    """
    monkeypatch.setattr(workflow_mode, "execute_psop", _make_async_psop([
        {"type": "step_start", "data": {"step": "s1"}},
        {"type": "complete", "data": {}},
    ]))
    result = workflow_mode.run_workflow_sync({}, [], "intent")
    assert "events" in result
    assert len(result["events"]) == 2


# ---------------------------------------------------------------------------
# workflow_mode — summarize_execution
# ---------------------------------------------------------------------------


def test_summarize_full_workflow_success():
    """TC-DWF-025 | 完整工作流事件流压缩为成功摘要

    输入: step_start→agent_request→task_response→step_complete→complete
    预期输出: success=True，steps 各状态正确，finalText 来自结果聚合
    断言点: success=True，step 状态/agent/outputPreview，finalText 非空
    防回归: 若任一事件类型处理错误，摘要字段不符
    """
    events = [
        {"type": "step_start", "data": {"step": "意图解析"}},
        {"type": "agent_request", "data": {"agent": "self"}},
        {"type": "task_response", "data": {"step": "意图解析", "agent": "self", "status": "success"}},
        {"type": "step_complete", "data": {"step": "意图解析", "results": [{"outputs": ["意图完成"]}]}},
        {"type": "step_start", "data": {"step": "结果聚合"}},
        {"type": "task_response", "data": {"step": "结果聚合", "status": "success"}},
        {"type": "step_complete", "data": {"step": "结果聚合", "results": [{"outputs": ["聚合完成"]}]}},
        {"type": "complete", "data": {}},
    ]
    result = workflow_mode.summarize_execution({"events": events})
    assert result["success"] is True
    assert len(result["steps"]) == 2
    step_map = {s["step"]: s for s in result["steps"]}
    assert step_map["意图解析"]["status"] == "success"
    assert step_map["意图解析"]["agent"] == "self"
    assert step_map["意图解析"]["outputPreview"] == "意图完成"
    assert step_map["结果聚合"]["outputPreview"] == "聚合完成"
    assert result["finalText"] == "聚合完成"


def test_summarize_error_event_adds_failed_step():
    """TC-DWF-026 | error 事件追加 failed 步骤

    输入: events 含 step_start + error
    预期输出: success=False，steps 含 "(error)" failed 条目
    断言点: 有 step="(error)" status="failed" 条目
    防回归: 若 error 事件未处理，无 failed 条目
    """
    events = [
        {"type": "step_start", "data": {"step": "s1"}},
        {"type": "error", "data": {"error": "boom"}},
    ]
    result = workflow_mode.summarize_execution({"events": events})
    assert result["success"] is False
    error_steps = [s for s in result["steps"] if s["step"] == "(error)"]
    assert len(error_steps) == 1
    assert error_steps[0]["status"] == "failed"
    assert error_steps[0]["error"] == "boom"


def test_summarize_empty_events():
    """TC-DWF-027 | 空事件流返回 success=False/空 steps/空 finalText

    输入: events=[]
    预期输出: {"success": False, "steps": [], "finalText": ""}
    断言点: 三个字段值
    防回归: 若空事件处理错误，字段不符
    """
    result = workflow_mode.summarize_execution({"events": []})
    assert result["success"] is False
    assert result["steps"] == []
    assert result["finalText"] == ""


def test_summarize_task_response_error_marks_step_failed():
    """TC-DWF-028 | task_response 含 error 时步骤状态置 failed

    输入: step_start + task_response(error)
    预期输出: step status=failed，error 字段已填充
    断言点: step["status"]=="failed" 且 step["error"] 非空
    防回归: 若 error 覆盖逻辑被删，status 仍为 success
    """
    events = [
        {"type": "step_start", "data": {"step": "s1"}},
        {"type": "task_response", "data": {"step": "s1", "status": "success", "outputs": ["ok"], "error": "partial"}},
    ]
    result = workflow_mode.summarize_execution({"events": events})
    step = result["steps"][0]
    assert step["status"] == "failed"
    assert step["error"] == "partial"
    assert step["outputPreview"] == "ok"


def test_summarize_step_complete_collects_results_outputs():
    """TC-DWF-029 | step_complete 的 results[].outputs 被收集

    输入: step_start + step_complete(results 含 outputs)
    预期输出: step status=success，outputPreview 取首个 output
    断言点: status=success，outputPreview 正确
    防回归: 若 results outputs 收集逻辑错误，outputPreview 为空
    """
    events = [
        {"type": "step_start", "data": {"step": "s1"}},
        {"type": "step_complete", "data": {"step": "s1", "results": [{"outputs": ["r1", "r2"]}]}},
    ]
    result = workflow_mode.summarize_execution({"events": events})
    step = result["steps"][0]
    assert step["status"] == "success"
    assert step["outputPreview"] == "r1"


def test_summarize_workflow_complete_sets_success():
    """TC-DWF-030 | workflow_complete 事件类型设置 success=True

    输入: events 仅含 workflow_complete
    预期输出: success=True
    断言点: success=True
    防回归: 若 workflow_complete 未纳入 complete 判定，success=False
    """
    result = workflow_mode.summarize_execution({"events": [{"type": "workflow_complete", "data": {}}]})
    assert result["success"] is True


def test_summarize_final_text_from_intent_when_no_aggregation():
    """TC-DWF-031 | 无结果聚合时 finalText 取自意图解析步骤

    输入: 意图解析步骤有 output，无结果聚合，complete 事件
    预期输出: finalText == 意图解析的输出
    断言点: finalText 等于意图解析 output
    防回归: 若优先级逻辑反了，finalText 取自其他步骤
    """
    events = [
        {"type": "step_start", "data": {"step": "意图解析"}},
        {"type": "task_response", "data": {"step": "意图解析", "outputs": ["意图输出"]}},
        {"type": "complete", "data": {}},
    ]
    result = workflow_mode.summarize_execution({"events": events})
    assert result["finalText"] == "意图输出"


def test_summarize_final_text_fallback_no_preferred_step():
    """TC-DWF-032 | 无结果聚合/意图解析时 finalText 取首个有输出步骤

    输入: 其他步骤有 output，无 preferred 步骤，complete 事件
    预期输出: finalText == 其他步骤输出
    断言点: finalText 非空且等于该步骤 output
    防回归: 若 fallback 逻辑被删，finalText 为空
    """
    events = [
        {"type": "step_start", "data": {"step": "其他步骤"}},
        {"type": "task_response", "data": {"step": "其他步骤", "outputs": ["其他输出"]}},
        {"type": "complete", "data": {}},
    ]
    result = workflow_mode.summarize_execution({"events": events})
    assert result["finalText"] == "其他输出"


def test_summarize_agent_request_without_step_start_ignored():
    """TC-DWF-033 | agent_request 无前置 step_start 时被忽略

    输入: events 仅含 agent_request（current_step_name 为空）
    预期输出: steps 为空（不创建步骤）
    断言点: steps=[]
    防回归: 若无 current step 时误创建步骤，steps 非空
    """
    result = workflow_mode.summarize_execution({"events": [
        {"type": "agent_request", "data": {"agent": "orphan"}},
    ]})
    assert result["steps"] == []
