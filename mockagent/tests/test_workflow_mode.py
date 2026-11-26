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

"""工作流编排模式测试：内置工作流 / AgentCard 构建 / 事件摘要 / 控制点决策（async）。"""
import json
import logging

import pytest

from mockagent_engine import agent_registry
from mockagent_engine import scenario_registry
from mockagent_engine import workflow_mode as wm

EXT_TASK_T = "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1"
EXT_NOTIFICATION_T = "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Notification-T/v1"

# 正式 PSOP（psop_live_event_assurance_en）的 9 个步骤
PSOP_STEP_NAMES = [f"step{i}" for i in range(1, 10)]


def test_load_builtin_formal_psop():
    wf = wm.load_builtin("psop_live_event_assurance_en")
    assert wf and wf["id"] == "psop_live_event_assurance_en"
    assert [s["name"] for s in wf["steps"]] == PSOP_STEP_NAMES
    # 三个自环步骤（Live Streaming Agent 本地执行）+ 六个远端派发步骤
    self_steps = [s["name"] for s in wf["steps"] if s.get("type") == "SelfLoop"]
    assert self_steps == ["step1", "step4", "step7"]


def test_load_builtin_unknown_returns_none():
    assert wm.load_builtin("no-such-workflow") is None


def test_list_builtin_contains_formal_psop():
    assert "psop_live_event_assurance_en" in [w["id"] for w in wm.list_builtin()]


def test_agent_cards_for_urls_and_schema():
    define = agent_registry.load_define()
    cards = wm.agent_cards_for(wm.load_builtin("psop_live_event_assurance_en"), define)
    by_name = {c["name"]: c for c in cards}
    assert by_name["Assurance Agent"]["supportedInterfaces"][0]["url"].endswith(":9102/")
    assert by_name["RAN Agent"]["supportedInterfaces"][0]["url"].endswith(":9115/")
    assert by_name["Live Streaming Agent"]["supportedInterfaces"][0]["url"].endswith(":9110/")
    for card in cards:
        assert card["capabilities"] == {"streaming": False}
        assert card["supportedInterfaces"][0]["protocolBinding"] == "HTTP+JSON"


def test_summarize_execution_success():
    events = [
        {"type": "step_start", "data": {"step": "step2"}},
        {"type": "agent_request", "data": {"agent": "Assurance Agent"}},
        {"type": "task_response", "data": {"step": "step2", "agent": "Assurance Agent",
                                            "status": "TASK_STATE_COMPLETED", "outputs": ["1. 保障策略生成：成功"]}},
        {"type": "step_complete", "data": {"step": "step2", "results": []}},
        {"type": "step_start", "data": {"step": "step9"}},
        {"type": "step_complete", "data": {"step": "step9", "results": []}},
        {"type": "complete", "data": {"step_outputs": {}}},
    ]
    summary = wm.summarize_execution({"events": events})
    assert summary["success"] is True
    assurance = next(s for s in summary["steps"] if s["step"] == "step2")
    assert assurance["status"] == "TASK_STATE_COMPLETED"
    assert assurance["agent"] == "Assurance Agent"
    assert assurance["outputPreview"].startswith("1. 保障策略生成")
    assert "保障策略生成" in summary["finalText"]


def test_summarize_execution_error_event():
    summary = wm.summarize_execution({"events": [{"type": "error", "data": {"error": "boom"}}]})
    assert summary["success"] is False
    assert any(s["step"] == "(error)" and s["status"] == "failed" for s in summary["steps"])


class _FakeReq:
    """TaskRequest 最小桩：只提供 on_task 读取的字段。"""

    def __init__(self, agent_name, skill="Network Policy Execution", step_name="step3"):
        self.agent_name = agent_name
        self.skill = skill
        self.instruction = "执行功率提升与覆盖增强任务"
        self.step_name = step_name
        self.workflow_input = None

        class _Input:
            text = "执行功率提升与覆盖增强任务"

        self.input = _Input


class _FakeSelf:
    def __init__(self, step_name, skill="", instruction=""):
        self.step_name = step_name
        self.skill = skill
        self.instruction = instruction
        self.workflow_input = None


async def test_on_task_builds_template_metadata():
    cp = wm.MockWorkflowControlPoint("执行赛事直播保障")
    mc = await cp.on_task(_FakeReq("RAN Agent"))
    md = dict(mc.metadata)
    assert md["templateUri"] == "Task-T/network-layer/ran-energy-saving/v1"
    assert EXT_TASK_T in mc.extensions
    assert len(md[EXT_TASK_T]) > 50, "extUri 应携带数据集样例请求全文"
    assert mc.parts[0].text


async def test_on_task_skill_override_picks_recovery_template():
    """同一 Agent 的不同技能可映射到不同模板：(Assurance Agent, Recovery Policy Dispatch)。"""
    cp = wm.MockWorkflowControlPoint("恢复初始配置")
    mc = await cp.on_task(_FakeReq("Assurance Agent", skill="Recovery Policy Dispatch", step_name="step8"))
    assert dict(mc.metadata)["templateUri"] == "Notification-T/network-layer/service-recovery/v1"
    assert EXT_NOTIFICATION_T in mc.extensions


async def test_on_task_without_template_keeps_plain_text():
    cp = wm.MockWorkflowControlPoint("任意意图")
    mc = await cp.on_task(_FakeReq("未登记的 Agent"))
    assert dict(mc.metadata).get("templateUri") is None
    assert mc.parts[0].text


async def test_on_self_task_event_info_parsing():
    cp = wm.MockWorkflowControlPoint("保障本月底城市马拉松赛事直播")
    result = await cp.on_self_task(_FakeSelf("step1", skill="Event Info Parsing"))
    assert result.success
    assert "赛事信息解析结果" in result.outputs[0]


async def test_on_self_task_kqi_degradation_and_recovery():
    cp = wm.MockWorkflowControlPoint("监控直播 KQI")
    degraded = await cp.on_self_task(
        _FakeSelf("step4", skill="KQI Monitoring",
                  instruction="display the live broadcast KQI ... discovers that KQI metrics decline")
    )
    assert degraded.success
    assert "发现劣化" in degraded.outputs[0]

    recovered = await cp.on_self_task(
        _FakeSelf("step7", skill="KQI Monitoring",
                  instruction="re-check the live broadcast KQI ... confirm that the degradation has been improved")
    )
    assert recovered.success
    assert "劣化已改善" in recovered.outputs[0]


async def test_on_self_task_aggregates_upstream():
    class _WI:
        class upstream_results:
            pass

    wi = _WI()
    wi.upstream_results = [
        type("U", (), {"step_name": "step2",
                        "task_results": [type("T", (), {"outputs": ["1. 保障策略生成：成功"]})()]})(),
    ]
    cp = wm.MockWorkflowControlPoint("任意意图")
    result = await cp.on_self_task(type("R", (), {"step_name": "聚合", "workflow_input": wi})())
    assert result.success
    assert "保障策略生成" in result.outputs[0]


async def test_on_route_allows():
    cp = wm.MockWorkflowControlPoint("任意意图")
    decision = await cp.on_route(_FakeReq("RAN Agent"))
    assert getattr(decision, "allowed", True)


def _write_wf(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# clear_builtin_cache —— 缓存失效（行 87 / 89）
# ---------------------------------------------------------------------------


def test_clear_builtin_cache_all_invalidates_lookup(tmp_path, monkeypatch):
    """TC-WF-001 | 全量清缓存后已删除源文件的工作流必须查不到

    输入: 临时 workflows 目录写入 wf_a.json(id=wf-a)；load_builtin 命中并缓存；
          删除源文件后仍可命中（缓存生效）；clear_builtin_cache() 全量清缓存后
          再次 load_builtin 应返回 None（源已删、缓存已清）
    预期输出: 先非 None(id==wf-a) → 删文件后仍非 None(缓存) → 清缓存后为 None
    断言点: 缓存命中与失效的可观察返回值序列
    防回归: 若 clear_builtin_cache(None) 不清空 _WF_CACHE，最后一步仍返回旧值
    """
    src = tmp_path / "wfsrc"
    src.mkdir()
    _write_wf(src / "wf_a.json", {"id": "wf-a", "name": "A", "steps": []})
    monkeypatch.setattr(wm, "_workflows_dir", lambda: src)
    try:
        wm.clear_builtin_cache()
        first = wm.load_builtin("wf-a")
        assert first is not None and first["id"] == "wf-a"

        (src / "wf_a.json").unlink()
        cached = wm.load_builtin("wf-a")
        assert cached is not None and cached["id"] == "wf-a"

        wm.clear_builtin_cache()
        assert wm.load_builtin("wf-a") is None
    finally:
        wm.clear_builtin_cache()


def test_clear_builtin_cache_single_keeps_others(tmp_path, monkeypatch):
    """TC-WF-002 | 按 id 清缓存只失效目标项，其余缓存项保留

    输入: 临时目录 wf_a.json(id=wf-a)、wf_b.json(id=wf-b)；两者均缓存；
          删除两源文件后二者仍命中缓存；clear_builtin_cache("wf-a") 只清 wf-a
    预期输出: wf-a 查不到(None)，wf-b 仍命中(id==wf-b)
    断言点: 清单条目与保留条目的差异化返回值
    防回归: 若按 id 清缓存误清全部或不清，wf-a/wf-b 状态会与预期相反
    """
    src = tmp_path / "wfsrc2"
    src.mkdir()
    _write_wf(src / "wf_a.json", {"id": "wf-a", "name": "A", "steps": []})
    _write_wf(src / "wf_b.json", {"id": "wf-b", "name": "B", "steps": []})
    monkeypatch.setattr(wm, "_workflows_dir", lambda: src)
    try:
        wm.clear_builtin_cache()
        assert wm.load_builtin("wf-a")["id"] == "wf-a"
        assert wm.load_builtin("wf-b")["id"] == "wf-b"
        (src / "wf_a.json").unlink()
        (src / "wf_b.json").unlink()
        assert wm.load_builtin("wf-a")["id"] == "wf-a"
        assert wm.load_builtin("wf-b")["id"] == "wf-b"

        wm.clear_builtin_cache("wf-a")
        assert wm.load_builtin("wf-a") is None
        assert wm.load_builtin("wf-b")["id"] == "wf-b"
    finally:
        wm.clear_builtin_cache()


# ---------------------------------------------------------------------------
# list_builtin —— 全局 workflows 目录扫描（行 128-132）
# ---------------------------------------------------------------------------


def test_list_builtin_global_dir_skips_invalid_json(tmp_path, monkeypatch):
    """TC-WF-003 | list_builtin 扫描全局 workflows 目录并跳过非法 JSON

    输入: 临时 workflows 目录含 g1.json(合法,id=g-one) 与 bad.json(非法 JSON)；
          屏蔽场景目录扫描
    预期输出: 结果仅含 g-one 一项(name=G1,description=d1)，bad 被跳过
    断言点: 返回列表 id 集合 == {"g-one"}，且 name/description 正确回填
    防回归: 若 except ValueError 分支被删，bad.json 会让整个函数抛异常
    """
    src = tmp_path / "gsrc"
    src.mkdir()
    _write_wf(src / "g1.json", {"id": "g-one", "name": "G1", "description": "d1"})
    (src / "bad.json").write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(wm, "_workflows_dir", lambda: src)
    monkeypatch.setattr(scenario_registry, "list_scenario_dirs", lambda: [])

    result = wm.list_builtin()
    assert [r["id"] for r in result] == ["g-one"]
    assert result[0]["name"] == "G1"
    assert result[0]["description"] == "d1"


# ---------------------------------------------------------------------------
# list_builtin —— 场景目录异常跳过（行 139-140）/ 重复 id 跳过（行 143）
# ---------------------------------------------------------------------------


def test_list_builtin_skips_scenario_with_missing_workflow(tmp_path, monkeypatch):
    """TC-WF-004 | list_builtin 跳过 workflow.json 缺失/损坏的场景目录

    输入: 场景目录列表含 good(合法 workflow.json,id=s-good) 与
          broken-scenario(无 workflow.json)；屏蔽全局目录
    预期输出: 结果只含 s-good，broken-scenario 被跳过且不抛异常
    断言点: 返回 id 集合 == {"s-good"}，不含 broken-scenario
    防回归: 若 except (OSError,ValueError) 被删，缺文件场景会让函数抛错
    """
    good = tmp_path / "good-scenario"
    good.mkdir()
    _write_wf(good / scenario_registry.SCENARIO_WORKFLOW_FILENAME,
              {"id": "s-good", "name": "S", "description": ""})
    broken = tmp_path / "broken-scenario"
    broken.mkdir()
    monkeypatch.setattr(wm, "_workflows_dir", lambda: tmp_path / "no-global")
    monkeypatch.setattr(scenario_registry, "list_scenario_dirs",
                        lambda: [good, broken])

    result = wm.list_builtin()
    assert [r["id"] for r in result] == ["s-good"]


def test_list_builtin_drops_scenario_duplicate_of_global(tmp_path, monkeypatch):
    """TC-WF-005 | 场景工作流 id 与全局重复时只保留全局项

    输入: 全局 dup.json(id=dup-id,name=GLOBAL)；场景 workflow.json(id=dup-id,name=SCENARIO)
    预期输出: 结果仅 1 项，name==GLOBAL（场景重复项被 continue 跳过）
    断言点: 结果长度==1 且 name 为 GLOBAL 而非 SCENARIO
    防回归: 若 `if wf_id in seen: continue` 被删，会追加重复项使长度==2
    """
    gsrc = tmp_path / "gsrc"
    gsrc.mkdir()
    _write_wf(gsrc / "dup.json", {"id": "dup-id", "name": "GLOBAL", "description": ""})
    scenario = tmp_path / "dup-scenario"
    scenario.mkdir()
    _write_wf(scenario / scenario_registry.SCENARIO_WORKFLOW_FILENAME,
              {"id": "dup-id", "name": "SCENARIO", "description": ""})
    monkeypatch.setattr(wm, "_workflows_dir", lambda: gsrc)
    monkeypatch.setattr(scenario_registry, "list_scenario_dirs", lambda: [scenario])

    result = wm.list_builtin()
    assert len(result) == 1
    assert result[0]["id"] == "dup-id"
    assert result[0]["name"] == "GLOBAL"


# ---------------------------------------------------------------------------
# _iter_scenario_workflows —— 非法场景工作流告警（行 100）
# ---------------------------------------------------------------------------


def test_load_builtin_falls_back_to_scenario_skipping_invalid(tmp_path, monkeypatch, caplog):
    """TC-WF-006 | load_builtin 回退场景查找时跳过非法场景工作流并告警

    输入: 全局目录不存在(回退场景)；场景列表含 good(workflow.json,id=s-good) 与
          broken-scenario(workflow.json 非法 JSON)，broken 置于列表首位以保证其被迭代
          到（good 命中后 load 即 break，否则 broken 不会被执行）
    预期输出: load_builtin("s-good") 返回该工作流；并产生一条含 broken-scenario 的告警
    断言点: 返回 id==s-good；caplog 中存在引用 broken-scenario 的 WARNING
    防回归: 若 _iter_scenario_workflows 的 except 被删，非法 JSON 会让 load 抛异常
    """
    good = tmp_path / "good-scenario"
    good.mkdir()
    _write_wf(good / scenario_registry.SCENARIO_WORKFLOW_FILENAME,
              {"id": "s-good", "name": "S", "steps": []})
    broken = tmp_path / "broken-scenario"
    broken.mkdir()
    (broken / scenario_registry.SCENARIO_WORKFLOW_FILENAME).write_text(
        "{ broken", encoding="utf-8")
    monkeypatch.setattr(scenario_registry, "list_scenario_dirs",
                        lambda: [broken, good])
    try:
        with caplog.at_level(logging.WARNING):
            wf = wm.load_builtin("s-good")
        assert wf is not None and wf["id"] == "s-good"
        assert any("broken-scenario" in r.getMessage() for r in caplog.records)
    finally:
        wm.clear_builtin_cache()


# ---------------------------------------------------------------------------
# agent_cards_for —— 缺失实例卡告警（行 181）
# ---------------------------------------------------------------------------


def test_agent_cards_for_warns_on_missing_agents(caplog):
    """TC-WF-007 | 工作流引用未在 instances 声明的 Agent 时告警且不为其生成卡

    输入: workflow 引用 Assurance Agent 与 Ghost Agent；define 只含 Assurance Agent
    预期输出: 仅返回 Assurance Agent 的卡；并产生含 Ghost Agent 的告警
    断言点: 卡名集合=={"Assurance Agent"}；caplog WARNING 含 "Ghost Agent"
    防回归: 若缺失告警分支被删，仍可由卡名集合断言拦截；双重保护
    """
    workflow_dict = {"steps": [{"subtasks": [
        {"agent": "Assurance Agent"}, {"agent": "Ghost Agent"}]}]}
    define = {"instances": [{"agentName": "Assurance Agent", "port": 9102}]}
    with caplog.at_level(logging.WARNING, logger="mockagent_engine.workflow_mode"):
        cards = wm.agent_cards_for(workflow_dict, define)
    assert [c["name"] for c in cards] == ["Assurance Agent"]
    assert cards[0]["supportedInterfaces"][0]["url"].endswith(":9102/")
    assert any("Ghost Agent" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# on_task —— 上游结果注入（行 188-191 / 212）
# ---------------------------------------------------------------------------


class _UpstreamTR:
    def __init__(self, outputs):
        self.outputs = outputs


class _Upstream:
    def __init__(self, step_name, task_results):
        self.step_name = step_name
        self.task_results = task_results


class _WorkflowInput:
    def __init__(self, upstream_results):
        self.upstream_results = upstream_results


class _TaskReq:
    def __init__(self, agent_name, skill, instruction, workflow_input):
        self.agent_name = agent_name
        self.skill = skill
        self.instruction = instruction
        self.step_name = "step3"
        self.workflow_input = workflow_input

        class _Input:
            text = instruction

        self.input = _Input


async def test_on_task_injects_upstream_summary():
    """TC-WF-008 | on_task 把上游步骤输出汇总拼进 instruction

    输入: RAN Agent 请求，workflow_input.upstream_results 含 step2 的
          task_result(outputs=["上游输出片段A"])
    预期输出: MessageContent.parts[0].text 含 "上游步骤结果"、"[step2]"、"上游输出片段A"
    断言点: 返回文本中上游片段与步名拼接正确
    防回归: 若 _summarize_upstream 循环或 instruction 拼接被删，三段关键字任一缺失
    """
    wi = _WorkflowInput([_Upstream("step2", [_UpstreamTR(["上游输出片段A"])])])
    req = _TaskReq("RAN Agent", "Network Policy Execution",
                   "执行功率提升与覆盖增强", wi)
    cp = wm.MockWorkflowControlPoint("保障赛事直播")
    mc = await cp.on_task(req)
    text = mc.parts[0].text
    assert "上游步骤结果" in text
    assert "[step2]" in text
    assert "上游输出片段A" in text


# ---------------------------------------------------------------------------
# _collect_events / run_workflow_sync —— 事件收集与终端中止（行 268-280 / 285）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("terminal", ["complete", "error"])
def test_run_workflow_sync_stops_at_terminal_event(monkeypatch, terminal):
    """TC-WF-009 | 事件流遇到 complete/error 立即停止收集

    输入: execute_psop 产出 [step_start, <terminal>, step_start(不应收集)]
    预期输出: run_workflow_sync 返回 {"events": [step_start, <terminal>]}
    断言点: 事件类型序列 == ["step_start", terminal]，terminal 之后的步骤被丢弃
    防回归: 若 break 被删，会多收集一个 step_start 使序列变长
    """

    async def fake_psop(**kwargs):
        yield {"type": "step_start", "data": {"step": "s1"}}
        if terminal == "error":
            yield {"type": "error", "data": {"error": "boom"}}
        else:
            yield {"type": "complete", "data": {}}
        yield {"type": "step_start", "data": {"step": "after"}}

    monkeypatch.setattr(wm, "execute_psop", fake_psop)
    out = wm.run_workflow_sync({"steps": []}, [], "intent")
    assert [e["type"] for e in out["events"]] == ["step_start", terminal]


# ---------------------------------------------------------------------------
# summarize_execution —— task_response 错误分支（行 325-326）
# ---------------------------------------------------------------------------


def test_summarize_execution_task_response_error_marks_failed():
    """TC-WF-010 | task_response 携带 error 时步骤标记 failed 并记录错误

    输入: 事件流 step_start(step2) → task_response(step2, error="远端执行失败") → complete
    预期输出: step2 status==failed、error=="远端执行失败"；success==True
    断言点: 步骤状态与错误文本
    防回归: 若 `if data.get("error")` 分支被删，status 停留在原始 TASK_STATE_* 且无 error
    """
    events = [
        {"type": "step_start", "data": {"step": "step2"}},
        {"type": "task_response", "data": {"step": "step2", "agent": "A",
                                            "status": "TASK_STATE_FAILED",
                                            "outputs": [], "error": "远端执行失败"}},
        {"type": "complete", "data": {}},
    ]
    summary = wm.summarize_execution({"events": events})
    step2 = next(s for s in summary["steps"] if s["step"] == "step2")
    assert step2["status"] == "failed"
    assert step2["error"] == "远端执行失败"
    assert summary["success"] is True


# ---------------------------------------------------------------------------
# summarize_execution —— step_complete dict 结果 + 首选聚合文本（行 334-338 / 347-348）
# ---------------------------------------------------------------------------


def test_summarize_execution_step_complete_dict_results_and_preferred_text():
    """TC-WF-011 | step_complete 的 dict 结果输出被聚合，且"结果聚合"步为首选 finalText

    输入: 事件流 step_start(结果聚合) → step_complete(结果=[{outputs:["聚合最终结论X"]}]) → complete
    预期输出: 该步 outputPreview=="聚合最终结论X"；finalText=="聚合最终结论X"；success==True
    断言点: 预览文本与首选聚合最终文本一致
    防回归: 若 dict 结果分支或首选步名循环被删，outputPreview/finalText 将为空
    """
    events = [
        {"type": "step_start", "data": {"step": "结果聚合"}},
        {"type": "step_complete", "data": {"step": "结果聚合",
                                            "results": [{"outputs": ["聚合最终结论X"]}]}},
        {"type": "complete", "data": {}},
    ]
    summary = wm.summarize_execution({"events": events})
    step = next(s for s in summary["steps"] if s["step"] == "结果聚合")
    assert step["status"] == "success"
    assert step["outputPreview"] == "聚合最终结论X"
    assert summary["finalText"] == "聚合最终结论X"
    assert summary["success"] is True
