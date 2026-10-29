# -*- coding: utf-8 -*-
"""tools/a2at_cli 直连与转发模式测试（httpx MockTransport，无真实网络）。"""
import json
import sys
from pathlib import Path

import httpx
import pytest

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import cli  # noqa: E402  (tools/a2at_cli/cli.py)

CARD = {
    "name": "OpenAN Debug Mock Agent",
    "version": "1.0.0",
    "provider": {"organization": "OpenAN"},
    "capabilities": {"streaming": True, "extensions": [{"uri": "https://x/Task-T/v1"}]},
    "skills": [{"id": "stub", "name": "Stub"}],
    "supportedInterfaces": [{"url": "http://h:1/debug/a2a", "protocolBinding": "HTTP+JSON"}],
}
TASK_OK = {"id": "t-1", "contextId": "c-1", "status": {"state": "TASK_STATE_COMPLETED", "message": {"parts": [{"text": "done"}]}}}
TEMPLATE_URI = "Task-T/network-layer/private-line-complaint/v1"
TASK_T_URI = "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1"


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------


def test_parse_tolerates_leading_binary_name():
    assert cli.parse_argv(["a2at", "help"])["name"] == "help"
    assert cli.parse_argv(["help", "send"])["args"] == ["send"]
    with pytest.raises(cli.CliUsageError):
        cli.parse_argv([])


def test_parse_send_flags():
    parsed = cli.parse_argv(["send", "-a", "http://h:1/a2a", "--template", TEMPLATE_URI, "-m", "查询"])
    assert parsed["flags"]["__text"] == "查询"
    assert parsed["flags"]["__target"] == "http://h:1/a2a"


def test_parse_task_requires_id():
    with pytest.raises(cli.CliUsageError):
        cli.parse_argv(["task", "get"])
    assert cli.parse_argv(["task", "get", "t-1"])["flags"]["__task_id"] == "t-1"


def test_normalize_base():
    assert cli.normalize_agent_base("http://h:1/debug/a2a/message:send") == "http://h:1/debug/a2a"
    assert cli.normalize_agent_base("https://h") == "https://h"
    assert cli.normalize_agent_base("no-such") is None


def test_build_body_ext():
    body, ext = cli.build_send_body("hi", TEMPLATE_URI)
    assert body["message"]["metadata"][TASK_T_URI] == "hi" and ext == TASK_T_URI
    body2, ext2 = cli.build_send_body("hi")
    assert "metadata" not in body2["message"] and ext2 is None


# ---------------------------------------------------------------------------
# 直连模式
# ---------------------------------------------------------------------------


def _patch_transport(monkeypatch, handler):
    real = httpx.Client

    def factory(**kwargs):
        return real(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(cli.httpx, "Client", factory)
    monkeypatch.setattr(cli.httpx, "HTTPError", httpx.HTTPError)


def test_main_card_get_direct(monkeypatch, capsys):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=CARD)

    _patch_transport(monkeypatch, handler)
    code = cli.main(["card", "get", "http://h:1/debug/a2a/message:send"])
    assert code == 0
    out = capsys.readouterr().out
    assert "OpenAN Debug Mock Agent" in out
    assert seen["url"] == "http://h:1/debug/a2a/.well-known/agent-card.json"


def test_main_send_with_template_headers(monkeypatch, capsys):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json=TASK_OK)

    _patch_transport(monkeypatch, handler)
    code = cli.main(["send", "-a", "http://h:1/a2a", "--template", TEMPLATE_URI, "查询专线"])
    assert code == 0
    assert seen["headers"]["a2a-version"] == "1.0"
    assert seen["headers"]["a2a-extensions"] == TASK_T_URI
    assert seen["body"]["message"]["metadata"]["templateUri"] == TEMPLATE_URI
    out = capsys.readouterr().out
    assert "t-1" in out and "TASK_STATE_COMPLETED" in out


def test_main_send_missing_target_env(monkeypatch):
    monkeypatch.delenv("A2AT_TARGET", raising=False)
    _patch_transport(monkeypatch, lambda request: httpx.Response(200, json=TASK_OK))
    assert cli.main(["send", "-m", "hi"]) == cli.EXIT_USAGE


def test_main_send_target_from_env(monkeypatch, capsys):
    monkeypatch.setenv("A2AT_TARGET", "http://h:1/a2a")
    _patch_transport(monkeypatch, lambda request: httpx.Response(200, json=TASK_OK))
    assert cli.main(["send", "-m", "hi", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "t-1"


def test_main_task_get_wait_json(monkeypatch, capsys):
    _patch_transport(monkeypatch, lambda request: httpx.Response(200, json=TASK_OK))
    assert cli.main(["task", "get", "t-1", "-a", "http://h:1/a2a", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "t-1"


def test_main_transport_error_exit_code(monkeypatch, capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    _patch_transport(monkeypatch, handler)
    assert cli.main(["card", "get", "http://h:1/a2a"]) == cli.EXIT_TRANSPORT
    assert "获取卡片失败" in capsys.readouterr().err


def test_main_stream_sse(monkeypatch, capsys):
    sse = (
        'data: {"id":"s1","status":{"state":"TASK_STATE_SUBMITTED"}}\n\n'
        'data: {"taskId":"s1","artifact":{"name":"stub.x","parts":[{"text":"结果"}]},"lastChunk":true}\n\n'
        'data: {"taskId":"s1","status":{"state":"TASK_STATE_COMPLETED"},"final":true}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/message:stream")
        return httpx.Response(200, content=sse.encode("utf-8"), headers={"content-type": "text/event-stream"})

    _patch_transport(monkeypatch, handler)
    assert cli.main(["send", "-a", "http://h:1/a2a", "--stream", "hi"]) == 0
    out = capsys.readouterr().out
    assert "[stream] status  TASK_STATE_SUBMITTED" in out and "结果" in out and "s1" in out


def test_main_task_failed_exit_code(monkeypatch):
    failed = {"id": "t2", "status": {"state": "TASK_STATE_FAILED"}}
    _patch_transport(monkeypatch, lambda request: httpx.Response(200, json=failed))
    assert cli.main(["send", "-a", "http://h:1/a2a", "hi"]) == cli.EXIT_TASK_FAILED


# ---------------------------------------------------------------------------
# Playground 转发模式
# ---------------------------------------------------------------------------


def test_agent_list_requires_playground(monkeypatch):
    monkeypatch.delenv("OPENAN_PLAYGROUND_URL", raising=False)
    assert cli.main(["agent", "list"]) == cli.EXIT_USAGE


def test_playground_forward(monkeypatch, capsys):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization", "")
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"token": "tok-1", "role": "admin"})
        body = json.loads(request.read())
        assert body == {"command": "agent list"}
        return httpx.Response(200, json={"exitCode": 0, "stdout": ["targets 2"], "stderr": [], "json": None, "durationMs": 5})

    _patch_transport(monkeypatch, handler)
    monkeypatch.setenv("OPENAN_PLAYGROUND_USERNAME", "admin")
    monkeypatch.setenv("OPENAN_PLAYGROUND_PASSWORD", "admin-pass-01")
    code = cli.main(["agent", "list", "--playground", "http://pg:9002/openan-playground/"])
    assert code == 0
    assert seen["auth"] == "Bearer tok-1"
    assert "targets 2" in capsys.readouterr().out


def test_playground_token_env(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer env-tok"
        return httpx.Response(200, json={"exitCode": 0, "stdout": ["ok"], "stderr": [], "json": None, "durationMs": 1})

    _patch_transport(monkeypatch, handler)
    monkeypatch.setenv("OPENAN_PLAYGROUND_TOKEN", "env-tok")
    assert cli.main(["task", "list", "--playground", "http://pg"]) == 0


def test_help_and_version(capsys):
    assert cli.main(["help"]) == 0 and "Usage" in capsys.readouterr().out
    assert cli.main(["version"]) == 0 and "1.0.0" in capsys.readouterr().out
    assert cli.main(["help", "send"]) == 0
