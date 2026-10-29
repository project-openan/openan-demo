import httpx
import pytest

from openan_debug import a2at_cli as cli
from openan_debug.routers import a2at_cli_router
from tests.conftest import auth_header

TEMPLATE_URI = "Task-T/network-layer/private-line-complaint/v1"
TASK_T_URI = "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1"

CARD = {
    "name": "OpenAN Debug Mock Agent",
    "description": "mock",
    "version": "1.0.0",
    "provider": {"organization": "OpenAN", "url": "https://example.com"},
    "capabilities": {"streaming": True, "extensions": [{"uri": TASK_T_URI, "description": "Task-T"}]},
    "skills": [{"id": "stub-responder", "name": "Stub responder"}],
    "supportedInterfaces": [{"url": "http://127.0.0.1:9000/debug/a2a", "protocolBinding": "HTTP+JSON"}],
}

TASK_COMPLETED = {
    "id": "task-1",
    "contextId": "ctx-1",
    "status": {
        "state": "TASK_STATE_COMPLETED",
        "message": {"parts": [{"text": "done"}]},
    },
    "artifacts": [{"name": "stub.private-line-complaint", "parts": [{"text": "端口正常"}]}],
}


def _install_mock_backend(monkeypatch, handler):
    real_client_factory = httpx.AsyncClient

    def fake_client_factory(**kwargs):
        return real_client_factory(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(a2at_cli_router.httpx, "AsyncClient", fake_client_factory)


def _exec(client, admin_token, command):
    resp = client.post(
        "/api/v1/a2at-cli/exec", json={"command": command}, headers=auth_header(admin_token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# 纯解析
# ---------------------------------------------------------------------------


def test_parse_send_with_flags():
    parsed = cli.parse_argv(["send", "-a", "default", "--template", TEMPLATE_URI, "-m", "查询专线"])
    assert parsed.name == "send"
    assert parsed.flags["--template"] == TEMPLATE_URI
    assert parsed.flags["__text"] == "查询专线"
    assert parsed.flags["__target"] == "default"


def test_parse_errors():
    with pytest.raises(cli.CliUsageError):
        cli.parse_argv([])
    with pytest.raises(cli.CliUsageError):
        cli.parse_argv(["send"])
    with pytest.raises(cli.CliUsageError):
        cli.parse_argv(["frobnicate"])
    with pytest.raises(cli.CliUsageError):
        cli.parse_argv(["task"])


def test_normalize_agent_base():
    assert cli.normalize_agent_base("http://h:1/debug/a2a/message:send") == "http://h:1/debug/a2a"
    assert cli.normalize_agent_base("http://h:1/") == "http://h:1"
    assert cli.normalize_agent_base("ftp://h") is None


def test_build_send_body_sets_template_and_ext():
    body, ext = cli.build_send_body("hi", TEMPLATE_URI)
    assert body["message"]["metadata"]["templateUri"] == TEMPLATE_URI
    assert body["message"]["metadata"][TASK_T_URI] == "hi"
    assert ext == TASK_T_URI
    body2, ext2 = cli.build_send_body("hi")
    assert "metadata" not in body2["message"] and ext2 is None


# ---------------------------------------------------------------------------
# exec API
# ---------------------------------------------------------------------------


def test_exec_help_and_version(client, admin_token):
    result = _exec(client, admin_token, "a2at help")
    assert result["exitCode"] == 0
    assert any("Usage" in line for line in result["stdout"])
    result = _exec(client, admin_token, "help send")
    assert any("message:send" in line for line in result["stdout"])
    result = _exec(client, admin_token, "a2at version")
    assert result["exitCode"] == 0
    assert any("a2at 1.0.0" in line for line in result["stdout"])


def test_exec_unknown_command_and_bad_quotes(client, admin_token):
    result = _exec(client, admin_token, "frobnicate now")
    assert result["exitCode"] == 2
    assert result["stderr"]
    result = _exec(client, admin_token, 'send "未闭合')
    assert result["exitCode"] == 2


def test_exec_card_get_default(client, admin_token, monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=CARD)

    _install_mock_backend(monkeypatch, handler)
    result = _exec(client, admin_token, "a2at card get")
    assert result["exitCode"] == 0
    assert captured["url"].endswith("/debug/a2a/.well-known/agent-card.json")
    assert any("OpenAN Debug Mock Agent" in line for line in result["stdout"])
    # --json 形态
    result = _exec(client, admin_token, "a2at card get --json")
    assert result["json"]["name"] == "OpenAN Debug Mock Agent"


def test_exec_send_default_with_template(client, admin_token, monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.read()
        return httpx.Response(200, json=TASK_COMPLETED)

    _install_mock_backend(monkeypatch, handler)
    command = f'a2at send --template "{TEMPLATE_URI}" "查询专线状态"'
    result = _exec(client, admin_token, command)
    assert result["exitCode"] == 0
    assert captured["url"].endswith("/debug/a2a/message:send")
    assert captured["headers"]["a2a-version"] == "1.0"
    assert captured["headers"]["a2a-extensions"] == TASK_T_URI
    import json as jsonlib

    body = jsonlib.loads(captured["body"])
    assert body["message"]["metadata"]["templateUri"] == TEMPLATE_URI
    assert body["message"]["metadata"][TASK_T_URI] == "查询专线状态"
    assert any("task-1" in line for line in result["stdout"])
    assert any("端口正常" in line for line in result["stdout"])
    assert result["meta"]["taskId"] == "task-1"
    assert result["meta"]["taskState"] == "TASK_STATE_COMPLETED"
    assert result["meta"]["templateUri"] == TEMPLATE_URI


def test_exec_send_plain_text_and_json(client, admin_token, monkeypatch):
    _install_mock_backend(monkeypatch, lambda request: httpx.Response(200, json=TASK_COMPLETED))
    result = _exec(client, admin_token, 'a2at send -m "hello" --json')
    assert result["exitCode"] == 0
    assert result["json"]["id"] == "task-1"


def test_exec_send_async_summary(client, admin_token, monkeypatch):
    _install_mock_backend(monkeypatch, lambda request: httpx.Response(200, json=TASK_COMPLETED))
    result = _exec(client, admin_token, "a2at send --async hello")
    assert result["exitCode"] == 0
    text = "\n".join(result["stdout"])
    assert "task-1" in text and "TASK_STATE_COMPLETED" in text
    assert "端口正常" not in text


def test_exec_send_task_failed_exit_code(client, admin_token, monkeypatch):
    failed = {"id": "t2", "status": {"state": "TASK_STATE_FAILED", "message": {"parts": [{"text": "boom"}]}}}
    _install_mock_backend(monkeypatch, lambda request: httpx.Response(200, json=failed))
    result = _exec(client, admin_token, "a2at send hi")
    assert result["exitCode"] == 3
    assert result["meta"]["taskState"] == "TASK_STATE_FAILED"


def test_exec_send_transport_error(client, admin_token, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    _install_mock_backend(monkeypatch, handler)
    result = _exec(client, admin_token, "a2at send hi")
    assert result["exitCode"] == 1
    assert "发送失败" in result["stderr"][0]


def test_exec_task_get_list_cancel(client, admin_token, monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["url"] = request.method, str(request.url)
        if request.url.path.endswith(":cancel"):
            return httpx.Response(200, json=TASK_COMPLETED)
        if request.url.path.endswith("/tasks"):
            return httpx.Response(200, json={"tasks": [TASK_COMPLETED], "totalSize": 1})
        return httpx.Response(200, json=TASK_COMPLETED)

    _install_mock_backend(monkeypatch, handler)
    result = _exec(client, admin_token, "a2at task get task-1 --json")
    assert result["json"]["id"] == "task-1"
    result = _exec(client, admin_token, "a2at task list")
    assert any("task-1" in line for line in result["stdout"])
    result = _exec(client, admin_token, "a2at task cancel task-1")
    assert result["exitCode"] == 0
    assert seen["url"].endswith("/tasks/task-1:cancel")


def test_exec_agent_list(client, admin_token, monkeypatch):
    monkeypatch.setattr(a2at_cli_router, "_health_probe", lambda port, timeout=1.0: False)
    result = _exec(client, admin_token, "a2at agent list")
    assert result["exitCode"] == 0
    text = "\n".join(result["stdout"])
    assert "default" in text and "fault-diagnosis-stub" in text and "未运行" in text
    result = _exec(client, admin_token, "a2at agent list --json")
    assert isinstance(result["json"]["instances"], list)


def test_exec_unknown_instance_target(client, admin_token):
    result = _exec(client, admin_token, "a2at card get @no-such-instance")
    assert result["exitCode"] == 2
    assert "a2at agent list" in result["stderr"][0]


def test_exec_instance_not_running(client, admin_token, monkeypatch):
    monkeypatch.setattr(a2at_cli_router, "_health_probe", lambda port, timeout=1.0: False)
    result = _exec(client, admin_token, "a2at card get fault-diagnosis-stub")
    assert result["exitCode"] == 1
    assert "未运行" in result["stderr"][0]


def test_exec_send_stream_reads_sse(client, admin_token, monkeypatch):
    # a2a-sdk REST 流的真实信封形态：task / statusUpdate / artifactUpdate
    sse = (
        'data: {"task":{"id":"s1","contextId":"c1","status":{"state":"TASK_STATE_SUBMITTED"}}}\n'
        "\n"
        'data: {"statusUpdate":{"taskId":"s1","contextId":"c1","status":{"state":"TASK_STATE_WORKING","message":{"parts":[{"text":"processing"}]}}}}\n'
        "\n"
        'data: {"artifactUpdate":{"taskId":"s1","artifact":{"name":"stub.x","parts":[{"text":"结果数据"}]},"lastChunk":true}}\n'
        "\n"
        'data: {"statusUpdate":{"taskId":"s1","contextId":"c1","status":{"state":"TASK_STATE_COMPLETED"},"final":true}}\n'
        "\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/message:stream")
        return httpx.Response(200, content=sse.encode("utf-8"), headers={"content-type": "text/event-stream"})

    _install_mock_backend(monkeypatch, handler)
    result = _exec(client, admin_token, "a2at send --stream hello")
    assert result["exitCode"] == 0
    text = "\n".join(result["stdout"])
    assert "[stream] task  s1  TASK_STATE_SUBMITTED" in text
    assert "[stream] status  TASK_STATE_WORKING  processing" in text
    assert "[stream] artifact  stub.x" in text
    assert "结果数据" in text
    assert "[stream] status  TASK_STATE_COMPLETED  [final]" in text
    assert result["meta"]["taskId"] == "s1"
    assert result["meta"]["taskState"] == "TASK_STATE_COMPLETED"


def test_exec_url_target(client, admin_token, monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=CARD)

    _install_mock_backend(monkeypatch, handler)
    result = _exec(client, admin_token, "a2at card get http://10.1.1.1:8080/debug/a2a/message:send")
    assert result["exitCode"] == 0
    assert captured["url"] == "http://10.1.1.1:8080/debug/a2a/.well-known/agent-card.json"


def test_exec_logged_to_history(client, admin_token, monkeypatch):
    _install_mock_backend(monkeypatch, lambda request: httpx.Response(200, json=CARD))
    _exec(client, admin_token, "a2at card get")
    history = client.get("/api/v1/history?feature=a2at-cli", headers=auth_header(admin_token)).json()
    assert history["total"] >= 1
    item = history["items"][0]
    assert item["direction"] == "cli"
    assert item["requestBody"]["command"].startswith("a2at")
