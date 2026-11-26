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

import httpx
import pytest

from openan_debug.llm_client import LlmConfig, ask_llm, build_simulator_prompt, from_define


def _llm_cfg(**kw):
    base = dict(enabled=True, provider="openai", base_url="http://x", model="m", api_key="k", max_attempts=1)
    base.update(kw)
    return LlmConfig(**base)


# --------------------------------------------------------------------------- #
# llm_client — TC-DLLM
# --------------------------------------------------------------------------- #
def test_dllm_from_define_disabled_returns_none():
    """TC-DLLM-001 | from_define 对 None/空/未启用配置返回 None

    输入: None / {} / {"enabled": False}
    预期输出: None
    断言点: 三种输入均返回 None
    防回归: 若启用守卫被删除，会构造出 LlmConfig
    """
    assert from_define(None) is None
    assert from_define({}) is None
    assert from_define({"enabled": False}) is None


def test_dllm_from_define_enabled_reads_env(monkeypatch):
    """TC-DLLM-002 | from_define 启用时从 env 读取 apiKey 并归一字段

    输入: enabled 配置 + apiKeyEnv 指向已设环境变量
    预期输出: LlmConfig(base_url 去尾斜杠/api_key 取环境值/max_attempts 转 int)
    断言点: 各字段值精确匹配
    防回归: 若 env 读取或字段映射改坏，api_key/base_url/max_attempts 错误
    """
    monkeypatch.setenv("MY_LLM_KEY", "secret-xyz")
    cfg = from_define(
        {
            "enabled": True,
            "provider": "openai",
            "baseUrl": "http://x/",
            "model": "gpt-4",
            "apiKeyEnv": "MY_LLM_KEY",
            "maxAttempts": "3",
            "language": "en",
        }
    )
    assert cfg.enabled is True
    assert cfg.provider == "openai"
    assert cfg.base_url == "http://x"
    assert cfg.model == "gpt-4"
    assert cfg.api_key == "secret-xyz"
    assert cfg.max_attempts == 3
    assert cfg.language == "en"


def test_dllm_from_define_minimal_defaults():
    """TC-DLLM-003 | from_define 最小启用配置使用默认值

    输入: {"enabled": True}（无其它字段）
    预期输出: provider=openai/base_url=''/api_key='dummy'/max_attempts=1/language=zh-CN
    断言点: 默认值精确匹配（apiKeyEnv 缺失回落 dummy）
    防回归: 若默认值或 env 回落改坏，字段不符
    """
    cfg = from_define({"enabled": True})
    assert cfg.provider == "openai"
    assert cfg.base_url == ""
    assert cfg.model == ""
    assert cfg.api_key == "dummy"
    assert cfg.max_attempts == 1
    assert cfg.language == "zh-CN"


def test_dllm_build_simulator_prompt_zh_with_sample():
    """TC-DLLM-004 | build_simulator_prompt 含模板/样例/中文时拼出完整提示词

    输入: agent_name/template_uri/prompt_text=zh/sample_response
    预期输出: 提示词含角色/模板/样例块/中文提示
    断言点: 关键片段均在结果中
    防回归: 若任一段拼接被删除，缺失对应片段
    """
    out = build_simulator_prompt("WirelessAgent", "Task-T/x/y", "do task", "zh-CN", "sample resp")
    assert "WirelessAgent simulator" in out
    assert "Task-T/x/y" in out
    assert "sample resp" in out
    assert "请用中文回复" in out
    assert "# Expected Output Format" in out


def test_dllm_build_simulator_prompt_en_without_sample():
    """TC-DLLM-005 | build_simulator_prompt 无模板/无样例/英文时走默认分支

    输入: template_uri=None, sample=None, language=en
    预期输出: 含 'Template: (unspecified)' 与英文提示，无样例块/无中文提示
    断言点: 默认模板行 + 英文提示 + 不含样例块
    防回归: 若默认分支改坏，模板行或语言提示错误
    """
    out = build_simulator_prompt("Agent", None, "do task", "en", None)
    assert "Template: (unspecified)" in out
    assert "Respond in English" in out
    assert "请用中文回复" not in out
    assert "# Expected Output Format" not in out


def test_dllm_ask_llm_returns_content():
    """TC-DLLM-006 | ask_llm 成功返回 choices[0].message.content

    输入: 有效 cfg + MockTransport 返回 200 + choices content
    预期输出: 返回 content 文本
    断言点: 返回值 == content
    防回归: 若 content 提取改坏，返回值错误
    """

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello world"}}]})

    assert ask_llm(_llm_cfg(), "prompt", transport=httpx.MockTransport(handler)) == "hello world"


def test_dllm_ask_llm_empty_content_raises():
    """TC-DLLM-007 | ask_llm 对空白 content 抛 RuntimeError 并重试耗尽

    输入: content 为空白，max_attempts=1
    预期输出: 抛 RuntimeError 含 'empty content' 与 'failed after 1'
    断言点: 异常类型 + 消息关键字
    防回归: 若空内容守卫被删除，会返回空串
    """

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})

    with pytest.raises(RuntimeError, match="empty content"):
        ask_llm(_llm_cfg(), "prompt", transport=httpx.MockTransport(handler))


def test_dllm_ask_llm_non_dict_body_raises():
    """TC-DLLM-008 | ask_llm 对非 dict/无 choices 响应体视为空内容抛错

    输入: 响应 json 为列表 [1,2,3]
    预期输出: 抛 RuntimeError 含 'empty content'
    断言点: 异常消息关键字
    防回归: 若非 dict 分支改坏，可能取到错误 content
    """

    def handler(request):
        return httpx.Response(200, json=[1, 2, 3])

    with pytest.raises(RuntimeError, match="empty content"):
        ask_llm(_llm_cfg(), "prompt", transport=httpx.MockTransport(handler))


def test_dllm_ask_llm_http_error_retries_then_fails():
    """TC-DLLM-009 | ask_llm HTTP 错误时按 max_attempts 重试，耗尽后抛错

    输入: 始终返回 500，max_attempts=2
    预期输出: 抛 RuntimeError 含 'failed after 2'，handler 被调用 2 次
    断言点: 异常消息 + 重试次数
    防回归: 若重试被删除，handler 仅调用 1 次
    """
    state = {"calls": 0}

    def handler(request):
        state["calls"] += 1
        return httpx.Response(500, json={"error": "down"})

    with pytest.raises(RuntimeError, match="failed after 2"):
        ask_llm(_llm_cfg(max_attempts=2), "prompt", transport=httpx.MockTransport(handler))
    assert state["calls"] == 2


def test_dllm_ask_llm_no_base_url_raises():
    """TC-DLLM-010 | ask_llm 未配置 baseUrl 时立即抛错

    输入: cfg.base_url=''
    预期输出: 抛 RuntimeError 含 'baseUrl is not configured'
    断言点: 异常类型 + 消息关键字
    防回归: 若守卫删除，会拼出非法 URL 发请求
    """
    with pytest.raises(RuntimeError, match="baseUrl is not configured"):
        ask_llm(_llm_cfg(base_url=""), "prompt")


def test_dllm_ask_llm_retry_then_success():
    """TC-DLLM-011 | ask_llm 首次失败后重试成功返回 content

    输入: 首次 500、第二次 200+content，max_attempts=2
    预期输出: 返回 content，handler 调用 2 次
    断言点: 返回值 + 重试次数
    防回归: 若重试被删除，首次失败即抛错无返回
    """
    state = {"calls": 0}

    def handler(request):
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(500, json={"error": "down"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    assert ask_llm(_llm_cfg(max_attempts=2), "prompt", transport=httpx.MockTransport(handler)) == "ok"
    assert state["calls"] == 2
