"""a2at — A2A-T 独立命令行客户端（OpenAN Playground）。

命令规范与 Playground Web 终端（server/openan_debug/a2at_cli.py）保持一致，
参考官方 A2A CLI（a2aproject/a2a-cli）：

    a2at card get [target]
    a2at agent list
    a2at send [-a target] [--template URI] [-m TEXT] [TEXT...] [--stream] [--async]
    a2at task get <id> [-a target] [--wait]
    a2at task list [-a target]
    a2at task cancel <id> [-a target]
    a2at help [command] / a2at version

两种工作模式：
- Playground 模式（配置 OPENAN_PLAYGROUND_URL 或 --playground）：
  命令转发给 Playground 服务端执行引擎（/api/v1/a2at-cli/exec），
  行为与 Web 终端完全一致（支持实例名目标与 @instance-id）。
- 直连模式（默认）：本机直接与 A2A HTTP+JSON 端点通信
  （card/send/task，自动携带 A2A-Version / A2A-Extensions 头）；
  目标取 -a 参数或环境变量 A2AT_TARGET。

退出码：0 成功 / 1 传输或 HTTP 错误 / 2 用法错误 / 3 任务非 COMPLETED 终态。

用法：
    python tools/a2at_cli/cli.py card get http://host:port/debug/a2a
    python tools/a2at_cli/cli.py send -a http://host:port/debug/a2a --stream "订阅告警"
"""
from __future__ import annotations

import json
import os
import shlex
import sys
import time
import uuid

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None

CLI_NAME = "a2at"
CLI_VERSION = "1.0.0"

EXIT_OK, EXIT_TRANSPORT, EXIT_USAGE, EXIT_TASK_FAILED = 0, 1, 2, 3
SEND_SUFFIXES = ("/message:send", "/message:stream")
CARD_SUFFIX = "/.well-known/agent-card.json"
DEFAULT_EXTENSION = "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1"
EXT_URI_BY_PREFIX = {
    "Task-T": "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1",
    "Notification-T": "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Notification-T/v1",
    "Authorization-T": "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Authorization-T/v1",
    "Negotiation-T": "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Negotiation-T/v1",
}
TERMINAL_STATES = {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"}

_BUILTIN_TARGETS = {"default", "builtin", ""}
_SEND_VALUE_FLAGS = {"-a", "--agent", "--template", "-m", "--message", "--timeout", "--context"}
_TASK_VALUE_FLAGS = {"-a", "--agent", "--timeout", "--limit"}


class CliUsageError(Exception):
    pass


# ---------------------------------------------------------------------------
# 解析（与 server/openan_debug/a2at_cli.py 同规范）
# ---------------------------------------------------------------------------


def parse_argv(argv):
    if not argv:
        raise CliUsageError("缺少命令，输入 'a2at help' 查看用法")
    if argv[0].lower() == CLI_NAME:
        argv = argv[1:]
        if not argv:
            argv = ["help"]
    name = argv[0].lower()
    rest = argv[1:]
    if name in ("help", "--help", "-h"):
        return {"name": "help", "args": rest, "flags": {}}
    if name in ("version", "--version", "-V"):
        return {"name": "version", "args": [], "flags": {}}
    if name == "card":
        if not rest or rest[0].lower() != "get":
            raise CliUsageError("card 仅支持 'a2at card get [target]'")
        flags, positional = _collect_flags(rest[1:], {"-a", "--agent"})
        flags["__target"] = positional[0] if positional else flags.get("-a") or flags.get("--agent")
        return {"name": "card", "args": ["get"], "flags": flags}
    if name == "agent":
        if not rest or rest[0].lower() != "list":
            raise CliUsageError("agent 仅支持 'a2at agent list'（需 Playground 模式）")
        flags, _ = _collect_flags(rest[1:], set())
        return {"name": "agent", "args": ["list"], "flags": flags}
    if name == "send":
        flags, positional = _collect_flags(rest, _SEND_VALUE_FLAGS)
        text_parts = list(positional)
        if flags.get("-m") is not None:
            text_parts.insert(0, flags.pop("-m"))
        if flags.get("--message") is not None:
            text_parts.insert(0, flags.pop("--message"))
        if not text_parts:
            raise CliUsageError('send 缺少消息文本：a2at send [-a target] "文本" 或 -m "文本"')
        flags["__text"] = " ".join(text_parts)
        flags["__target"] = flags.get("-a") or flags.get("--agent")
        return {"name": "send", "args": [], "flags": flags}
    if name == "task":
        if not rest:
            raise CliUsageError("task 需要 子命令 get|list|cancel，输入 'a2at help task' 查看用法")
        sub = rest[0].lower()
        if sub not in ("get", "list", "cancel"):
            raise CliUsageError(f"未知 task 子命令 {sub!r}（支持 get|list|cancel）")
        flags, positional = _collect_flags(rest[1:], _TASK_VALUE_FLAGS)
        if sub in ("get", "cancel") and not positional:
            raise CliUsageError(f"task {sub} 缺少任务 ID")
        flags["__task_id"] = positional[0] if positional else None
        flags["__target"] = flags.get("-a") or flags.get("--agent")
        return {"name": "task", "args": [sub], "flags": flags}
    raise CliUsageError(f"未知命令 {argv[0]!r}，输入 'a2at help' 查看支持的命令")


def _collect_flags(argv, value_flags):
    flags, positional, index = {}, [], 0
    while index < len(argv):
        token = argv[index]
        if token in value_flags:
            if index + 1 >= len(argv):
                raise CliUsageError(f"选项 {token} 缺少取值")
            flags[token] = argv[index + 1]
            index += 2
            continue
        if token == "--json":
            flags["--json"] = True
        elif token in ("--stream", "-s"):
            flags["--stream"] = True
        elif token == "--async":
            flags["--async"] = True
        elif token == "--wait":
            flags["--wait"] = True
        elif token.startswith("--") or (token.startswith("-") and len(token) > 1):
            raise CliUsageError(f"未知选项 {token}")
        else:
            positional.append(token)
        index += 1
    return flags, positional


# ---------------------------------------------------------------------------
# 目标 / 请求构造
# ---------------------------------------------------------------------------


def normalize_agent_base(target):
    if not target:
        return None
    candidate = target.strip().rstrip("/")
    lower = candidate.lower()
    if not lower.startswith(("http://", "https://")):
        return None
    for suffix in SEND_SUFFIXES:
        if lower.endswith(suffix):
            candidate, lower = candidate[: -len(suffix)], candidate[: -len(suffix)].lower()
    if lower.endswith(CARD_SUFFIX):
        candidate = candidate[: -len(CARD_SUFFIX)]
    return candidate.rstrip("/")


def ext_uri_for(template_uri):
    if not template_uri:
        return None
    return EXT_URI_BY_PREFIX.get(str(template_uri).split("/", 1)[0])


def build_send_body(text, template_uri=None, context_id=None):
    metadata = {}
    extension_header = None
    if template_uri:
        metadata["templateUri"] = template_uri
        ext_uri = ext_uri_for(template_uri)
        if ext_uri and not template_uri.startswith("Negotiation-T"):
            metadata[ext_uri] = text
        extension_header = ext_uri or DEFAULT_EXTENSION
    message = {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": [{"text": text, "metadata": {}}]}
    if metadata:
        message["metadata"] = metadata
    if context_id:
        message["contextId"] = context_id
    return {"message": message}, extension_header


def build_headers(extension_uri):
    headers = {"A2A-Version": "1.0", "Content-Type": "application/json"}
    if extension_uri:
        headers["A2A-Extensions"] = extension_uri
    return headers


def flag_timeout(flags, default):
    raw = flags.get("--timeout")
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise CliUsageError(f"--timeout 需要数字秒数，收到 {raw!r}") from exc
    if value <= 0 or value > 600:
        raise CliUsageError("--timeout 需在 (0, 600] 秒范围内")
    return value


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------


def _parts_text(parts):
    texts = []
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        if isinstance(part.get("text"), str):
            texts.append(part["text"])
        elif "data" in part:
            texts.append(json.dumps(part["data"], ensure_ascii=False))
    return "\n".join(t for t in texts if t)


def render_card(card):
    capabilities = card.get("capabilities") or {}
    extensions = capabilities.get("extensions") or []
    interfaces = card.get("supportedInterfaces") or []
    lines = [
        f"name          {card.get('name', '-')}",
        f"organization  {(card.get('provider') or {}).get('organization', '-')}",
        f"version       {card.get('version', '-')}",
        f"interface     {interfaces[0].get('url', '-') if interfaces else '-'}",
        f"streaming     {'true' if capabilities.get('streaming') else 'false'}",
        f"extensions    {len(extensions)}",
    ]
    for ext in extensions:
        lines.append(f"  - {ext.get('uri', '-')}" + (f"  {ext.get('description')}" if ext.get("description") else ""))
    skills = card.get("skills") or []
    lines.append(f"skills        {len(skills)}")
    for skill in skills:
        lines.append(f"  - {skill.get('id', '-')}  {skill.get('name', '')}")
    return lines


def render_task(task, latency_ms=None):
    status = task.get("status") or {}
    lines = [
        f"task          {task.get('id', '-')}",
        f"context       {task.get('contextId', '-')}",
        f"state         {status.get('state', '-')}",
    ]
    agent_text = _parts_text((status.get("message") or {}).get("parts"))
    if agent_text:
        first_line = agent_text.splitlines()[0] + " …" if "\n" in agent_text else agent_text
        lines.append(f"agent message {first_line}")
    for artifact in task.get("artifacts") or []:
        text = _parts_text(artifact.get("parts"))
        if text:
            lines.append(f"artifact      {artifact.get('name', '-')}")
            lines.extend(f"  {line}" for line in text.splitlines() or [""])
            break
    if latency_ms is not None:
        lines.append(f"latency       {latency_ms}ms")
    return lines


def render_task_summary(task):
    return [
        f"task          {task.get('id', '-')}",
        f"state         {(task.get('status') or {}).get('state', '-')}",
    ]


def render_task_list(payload):
    if isinstance(payload, dict):
        tasks = payload.get("tasks") or payload.get("items") or []
        total = payload.get("totalSize", payload.get("total", len(tasks)))
    elif isinstance(payload, list):
        tasks, total = payload, len(payload)
    else:
        tasks, total = [], 0
    lines = [f"tasks         {total}"]
    for task in tasks:
        if isinstance(task, dict):
            lines.append(f"  {task.get('id', '-')}  {(task.get('status') or {}).get('state', '-')}  context={task.get('contextId', '-')}")
    return lines


def parse_stream_event(event):
    """解析一条 SSE 事件，返回 (输出行, task_id, state, final)。

    兼容 a2a-sdk REST 流的两种形态：信封式（task/statusUpdate/artifactUpdate）
    与裸事件式（Task/TaskStatusUpdateEvent/TaskArtifactUpdateEvent/Message）。
    """
    if not isinstance(event, dict):
        return [f"[stream] {event}"], None, None, False
    if "artifactUpdate" in event or "artifact" in event:
        update = event.get("artifactUpdate") if isinstance(event.get("artifactUpdate"), dict) else {}
        artifact = update.get("artifact") or event.get("artifact") or {}
        text = _parts_text(artifact.get("parts"))
        last_chunk = bool(update.get("lastChunk") or event.get("lastChunk"))
        lines = [f"[stream] artifact  {artifact.get('name', '-')}" + ("  (last chunk)" if last_chunk else "")]
        lines.extend(f"  {line}" for line in text.splitlines() or [""])
        return lines, update.get("taskId") or event.get("taskId"), None, False
    if "statusUpdate" in event or "status" in event:
        update = event.get("statusUpdate") if isinstance(event.get("statusUpdate"), dict) else {}
        status = update.get("status") or event.get("status") or {}
        state = status.get("state")
        final = bool(update.get("final") or event.get("final"))
        text = _parts_text((status.get("message") or {}).get("parts"))
        suffix = f"  {text}" if text else ""
        final_mark = "  [final]" if final else ""
        lines = [f"[stream] status  {state or '-'}{suffix}{final_mark}"]
        task_id = update.get("taskId") or event.get("taskId") or event.get("id")
        return lines, task_id, state, final
    if isinstance(event.get("task"), dict):
        task = event["task"]
        status = task.get("status") or {}
        return [f"[stream] task  {task.get('id', '-')}  {status.get('state', '-')}"], task.get("id"), status.get("state"), False
    if event.get("parts"):
        return [f"[stream] message  {_parts_text(event.get('parts'))}"], event.get("messageId"), None, False
    return ["[stream] event  " + json.dumps(event, ensure_ascii=False)[:200]], None, None, False


def render_stream_event(event):
    lines, _task_id, _state, _final = parse_stream_event(event)
    return lines


def extract_task(payload):
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("task"), dict):
        return payload["task"]
    if payload.get("id") is not None and "status" in payload:
        return payload
    return None


# ---------------------------------------------------------------------------
# 直连模式执行
# ---------------------------------------------------------------------------


class DirectClient:
    def __init__(self):
        self.client = httpx.Client(timeout=120)
        # a2a-sdk REST 路由要求携带 A2A-Version 头（GET /tasks 缺失时返回 400）
        self.base_headers = {"A2A-Version": "1.0"}

    def close(self):
        self.client.close()

    def card_get(self, base, timeout, as_json):
        url = f"{base}/.well-known/agent-card.json"
        try:
            response = self.client.get(url, timeout=timeout, headers=self.base_headers)
        except httpx.HTTPError as exc:
            return _transport_error(f"获取卡片失败（{url}）：{exc}")
        if response.status_code != 200:
            return _transport_error(f"获取卡片失败：HTTP {response.status_code}（{url}）")
        if as_json:
            return _json_outcome(response)
        return {"exitCode": EXIT_OK, "stdout": render_card(response.json()), "stderr": [], "json": None}

    def send(self, base, parsed, as_json):
        flags = parsed["flags"]
        body, ext_uri = build_send_body(flags["__text"], flags.get("--template"), flags.get("--context"))
        headers = build_headers(ext_uri)
        timeout = flag_timeout(flags, 120.0)
        if flags.get("--stream") or flags.get("-s"):
            return self._send_stream(base, body, headers, timeout, as_json)
        url = f"{base}/message:send"
        started = time.monotonic()
        try:
            response = self.client.post(url, json=body, headers=headers, timeout=timeout)
        except httpx.HTTPError as exc:
            return _transport_error(f"发送失败（{url}）：{exc}")
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code != 200:
            return _transport_error(f"发送失败：HTTP {response.status_code} {response.text[:300]}（{url}）")
        try:
            payload = response.json()
        except ValueError:
            return _transport_error("响应不是合法 JSON")
        task = extract_task(payload)
        if as_json:
            return {"exitCode": EXIT_OK, "stdout": [], "stderr": [], "json": payload}
        if flags.get("--async"):
            out = render_task_summary(task or {}) + [f"latency       {latency_ms}ms"]
            return {"exitCode": EXIT_OK, "stdout": out, "stderr": [], "json": None}
        if task is None:
            out = render_card(payload) if isinstance(payload, dict) and payload.get("name") else [json.dumps(payload, ensure_ascii=False)[:400]]
            return {"exitCode": EXIT_OK, "stdout": out, "stderr": [], "json": None}
        state = ((task.get("status") or {}).get("state"))
        exit_code = EXIT_OK
        if state in TERMINAL_STATES and state != "TASK_STATE_COMPLETED":
            exit_code = EXIT_TASK_FAILED
        return {"exitCode": exit_code, "stdout": render_task(task, latency_ms), "stderr": [], "json": None}

    def _send_stream(self, base, body, headers, timeout, as_json):
        url = f"{base}/message:stream"
        lines, task_id, final_state = [], None, None
        try:
            with self.client.stream("POST", url, json=body, headers=headers, timeout=timeout) as response:
                if response.status_code != 200:
                    return _transport_error(f"流式发送失败：HTTP {response.status_code}（{url}）")
                for raw_line in response.iter_lines():
                    line = raw_line.strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        event = json.loads(payload)
                    except ValueError:
                        lines.append(f"[stream] {payload[:200]}")
                        continue
                    event_lines, ev_task_id, ev_state, ev_final = parse_stream_event(event)
                    lines.extend(event_lines)
                    if ev_task_id:
                        task_id = ev_task_id
                    if ev_state and (ev_final or ev_state in TERMINAL_STATES):
                        final_state = ev_state
        except httpx.HTTPError as exc:
            return _transport_error(f"流式传输失败（{url}）：{exc}")
        if final_state:
            lines += [f"task          {task_id or '-'}", f"state         {final_state}"]
        exit_code = EXIT_OK if final_state in (None, "TASK_STATE_COMPLETED") else EXIT_TASK_FAILED
        if as_json and exit_code == EXIT_OK:
            return {"exitCode": exit_code, "stdout": [], "stderr": [], "json": {"taskId": task_id, "taskState": final_state, "eventLines": len(lines)}}
        return {"exitCode": exit_code, "stdout": lines, "stderr": [], "json": None}

    def task(self, base, parsed, as_json):
        sub = parsed["args"][0]
        flags = parsed["flags"]
        task_id = flags.get("__task_id")
        wait = bool(flags.get("--wait")) and sub == "get"
        timeout = flag_timeout(flags, 60.0 if wait else 120.0)
        if sub == "get":
            url = f"{base}/tasks/{task_id}"
            deadline = time.monotonic() + timeout
            while True:
                try:
                    response = self.client.get(url, timeout=min(timeout, 30.0), headers=self.base_headers)
                except httpx.HTTPError as exc:
                    return _transport_error(f"任务查询失败（{url}）：{exc}")
                if response.status_code != 200:
                    return _transport_error(f"任务查询失败：HTTP {response.status_code}（{url}）")
                task = extract_task(response.json()) or response.json()
                state = (task.get("status") or {}).get("state")
                if not wait or state in TERMINAL_STATES or time.monotonic() >= deadline:
                    if as_json:
                        return {"exitCode": EXIT_OK, "stdout": [], "stderr": [], "json": task}
                    exit_code = EXIT_OK
                    if state in TERMINAL_STATES and state != "TASK_STATE_COMPLETED":
                        exit_code = EXIT_TASK_FAILED
                    return {"exitCode": exit_code, "stdout": render_task(task), "stderr": [], "json": None}
                time.sleep(1.0)
        if sub == "list":
            url = f"{base}/tasks"
            try:
                response = self.client.get(url, timeout=min(timeout, 30.0), headers=self.base_headers)
            except httpx.HTTPError as exc:
                return _transport_error(f"任务列表获取失败（{url}）：{exc}")
            if response.status_code != 200:
                return _transport_error(f"任务列表获取失败：HTTP {response.status_code}（{url}）")
            if as_json:
                return {"exitCode": EXIT_OK, "stdout": [], "stderr": [], "json": response.json()}
            return {"exitCode": EXIT_OK, "stdout": render_task_list(response.json()), "stderr": [], "json": None}
        url = f"{base}/tasks/{task_id}:cancel"
        try:
            response = self.client.post(url, json={}, timeout=min(timeout, 30.0), headers=self.base_headers)
        except httpx.HTTPError as exc:
            return _transport_error(f"任务取消失败（{url}）：{exc}")
        if response.status_code not in (200, 202):
            return _transport_error(f"任务取消失败：HTTP {response.status_code}（{url}）")
        if as_json:
            return {"exitCode": EXIT_OK, "stdout": [], "stderr": [], "json": _safe_json(response)}
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        task = extract_task(payload)
        out = render_task_summary(task) if task else [f"cancel        已发送取消请求（{task_id}，HTTP {response.status_code}）"]
        return {"exitCode": EXIT_OK, "stdout": out, "stderr": [], "json": None}


def _safe_json(response):
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text[:400]}


def _json_outcome(response):
    try:
        return {"exitCode": EXIT_OK, "stdout": [], "stderr": [], "json": response.json()}
    except ValueError:
        return _transport_error("响应不是合法 JSON")


def _transport_error(message):
    return {"exitCode": EXIT_TRANSPORT, "stdout": [], "stderr": [message], "json": None}


# ---------------------------------------------------------------------------
# Playground 模式（转发到服务端执行引擎）
# ---------------------------------------------------------------------------


def playground_base(args):
    base = (args.playground or os.environ.get("OPENAN_PLAYGROUND_URL") or "").strip().rstrip("/")
    if base and not base.startswith(("http://", "https://")):
        raise CliUsageError(f"--playground 需要 http(s) URL，收到 {base!r}")
    return base or None


def playground_token(client, base, args):
    token = args.token or os.environ.get("OPENAN_PLAYGROUND_TOKEN") or ""
    if token:
        return token
    username = args.username or os.environ.get("OPENAN_PLAYGROUND_USERNAME")
    password = args.password or os.environ.get("OPENAN_PLAYGROUND_PASSWORD")
    if not username or not password:
        raise CliUsageError(
            "Playground 鉴权缺失：设置 --token / OPENAN_PLAYGROUND_TOKEN，"
            "或 --username/--password（也可用环境变量 OPENAN_PLAYGROUND_USERNAME/PASSWORD）"
        )
    try:
        response = client.post(f"{base}/api/v1/auth/login", json={"username": username, "password": password})
    except httpx.HTTPError as exc:
        raise CliUsageError(f"Playground 登录失败：{exc}")
    if response.status_code != 200:
        raise CliUsageError(f"Playground 登录失败：HTTP {response.status_code}")
    return response.json().get("token", "")


def run_via_playground(base, token, argv):
    command = " ".join(shlex.quote(part) for part in argv)
    with httpx.Client(timeout=600) as client:
        try:
            response = client.post(
                f"{base}/api/v1/a2at-cli/exec",
                json={"command": command},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            return _transport_error(f"Playground 请求失败：{exc}")
    if response.status_code == 401:
        return _transport_error("Playground 鉴权失败（401）：token 无效或过期，请重新提供 --token/--username")
    if response.status_code != 200:
        return _transport_error(f"Playground 返回 HTTP {response.status_code}: {response.text[:300]}")
    result = response.json()
    return {
        "exitCode": int(result.get("exitCode", 1)),
        "stdout": list(result.get("stdout") or []),
        "stderr": list(result.get("stderr") or []),
        "json": result.get("json"),
    }


# ---------------------------------------------------------------------------
# 帮助
# ---------------------------------------------------------------------------

_HELP_OVERVIEW = f"""{CLI_NAME} {CLI_VERSION} — A2A-T CLI（OpenAN Playground 独立客户端，命令规范参考官方 A2A CLI）

Usage:
  a2at <command> [flags] [args]

Commands:
  card get [target]                     获取目标 Agent 卡片（A2A 发现）
  agent list                            列出 Playground 目标（需 Playground 模式）
  send [-a target] [--template URI]     发送 A2A-T 消息并等待结果
        [-m TEXT] [TEXT...] [--stream] [--async]
  task get <id> [-a target] [--wait]    查询任务（--wait 轮询至终态）
  task list [-a target]                 列出目标任务的任务
  task cancel <id> [-a target]          取消任务
  help [command]                        查看帮助
  version                               查看版本

Targets:
  （缺省）/ default / builtin           环境变量 A2AT_TARGET 指定的端点
  http(s)://host[:port][/path]          任意 A2A HTTP+JSON 端点（自动规整 base）
  Playground 模式（--playground）       额外支持实例 id/名称与 @instance-id

Modes:
  Playground 模式：--playground <URL>（或 OPENAN_PLAYGROUND_URL）时命令转发给
  Playground 服务端执行引擎，与 Web 终端行为一致；鉴权用 --token /
  OPENAN_PLAYGROUND_TOKEN 或 --username/--password。
  直连模式（默认）：本机直接与目标 A2A 端点通信。

Flags:
  -a, --agent <target>   目标 Agent（见 Targets）
      --template <uri>   A2A-T 模板 URI（写入 metadata.templateUri 并携带 A2A-Extensions 头）
  -m, --message <text>   消息文本（也可用位置参数给出）
  -s, --stream           经 message:stream 以 SSE 流式接收事件
      --async            仅返回任务句柄（task id/state）
      --wait             task get 轮询至终态（默认 60s）
      --timeout <sec>    请求超时（默认 120s）
      --context <id>     为消息附加 contextId
      --json             输出协议原生 JSON

Exit codes:
  0 成功   1 传输/HTTP 错误   2 用法错误   3 任务以非 COMPLETED 终态结束

Examples:
  a2at card get http://47.236.98.226:9002/openan-playground/a2a
  a2at send -a http://127.0.0.1:9100/debug/a2a --template 'Task-T/network-layer/private-line-complaint/v1' "查询专线状态"
  a2at send -s -m "订阅严重故障告警"
  OPENAN_PLAYGROUND_URL=http://47.236.98.226:9002/openan-playground a2at agent list"""

_HELP_BY_COMMAND = {
    "card": "Usage: a2at card get [target]\n\n获取目标 Agent 的 AgentCard（GET /.well-known/agent-card.json）。",
    "agent": "Usage: a2at agent list\n\n列出 Playground 可用目标（内置 Mock Agent + 打桩实例）；需 Playground 模式。",
    "send": "Usage: a2at send [-a target] [--template URI] [-m TEXT] [TEXT...] [--stream] [--async] [--json] [--timeout SEC] [--context ID]\n\n发送 A2A-T 消息：POST {target}/message:send（或 --stream 时 message:stream SSE）。",
    "task": "Usage: a2at task get <id> [-a target] [--wait] [--timeout SEC]\n       a2at task list [-a target]\n       a2at task cancel <id> [-a target]",
    "help": "Usage: a2at help [command]",
    "version": f"Usage: a2at version\n\n输出 {CLI_NAME} {CLI_VERSION}。",
}


def help_text(command=None):
    if not command:
        return _HELP_OVERVIEW
    key = command.lower().lstrip("-")
    return _HELP_BY_COMMAND.get(key, f"未知命令 {command!r}\n\n{_HELP_OVERVIEW}")


def version_text():
    return f"{CLI_NAME} {CLI_VERSION} (OpenAN Playground A2A-T CLI; spec modeled on a2aproject/a2a-cli)"


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # 独立模式专用全局选项（不参与命令规范解析）
    playground = None
    token = None
    username = password = None
    filtered = []
    index = 0
    while index < len(argv):
        token_arg = argv[index]
        if token_arg == "--playground":
            playground, index = argv[index + 1], index + 2
            continue
        if token_arg == "--pg-token":
            token, index = argv[index + 1], index + 2
            continue
        if token_arg == "--pg-user":
            username, index = argv[index + 1], index + 2
            continue
        if token_arg == "--pg-pass":
            password, index = argv[index + 1], index + 2
            continue
        filtered.append(token_arg)
        index += 1

    class _Args:
        pass

    args = _Args()
    args.playground, args.token, args.username, args.password = playground, token, username, password

    try:
        parsed = parse_argv(filtered)
    except CliUsageError as exc:
        print(f"a2at: {exc}", file=sys.stderr)
        print("输入 'a2at help' 查看用法", file=sys.stderr)
        return EXIT_USAGE

    if parsed["name"] == "help":
        print(help_text(parsed["args"][0] if parsed["args"] else None))
        return EXIT_OK
    if parsed["name"] == "version":
        print(version_text())
        return EXIT_OK

    if httpx is None:
        print("a2at: 需要 httpx 依赖（pip install httpx）", file=sys.stderr)
        return EXIT_TRANSPORT

    pg_base = playground_base(args)
    if parsed["name"] == "agent" and not pg_base:
        print("a2at: agent list 需要 Playground 模式：--playground <URL> 或环境变量 OPENAN_PLAYGROUND_URL", file=sys.stderr)
        return EXIT_USAGE

    if pg_base:
        try:
            pg_token = playground_token(httpx.Client(timeout=30), pg_base, args)
        except CliUsageError as exc:
            print(f"a2at: {exc}", file=sys.stderr)
            return EXIT_USAGE
        result = run_via_playground(pg_base, pg_token, filtered)
    else:
        target = parsed["flags"].get("__target")
        if parsed["name"] == "send" and (target or "").lower() in _BUILTIN_TARGETS:
            target = target or os.environ.get("A2AT_TARGET", "")
            if not target:
                print("a2at: send 缺少目标：用 -a <url> 或设置 A2AT_TARGET 环境变量（Playground 模式可用实例名）", file=sys.stderr)
                return EXIT_USAGE
        base = normalize_agent_base(target)
        if base is None:
            print(f"a2at: 目标 {target!r} 不是 http(s) URL；直连模式需 URL 目标（Playground 模式用 --playground）", file=sys.stderr)
            return EXIT_USAGE
        direct = DirectClient()
        try:
            if parsed["name"] == "card":
                result = direct.card_get(base, flag_timeout(parsed["flags"], 30.0), bool(parsed["flags"].get("--json")))
            elif parsed["name"] == "send":
                result = direct.send(base, parsed, bool(parsed["flags"].get("--json")))
            else:
                result = direct.task(base, parsed, bool(parsed["flags"].get("--json")))
        finally:
            direct.close()

    for line in result["stdout"]:
        print(line)
    for line in result["stderr"]:
        print(line, file=sys.stderr)
    if result.get("json") is not None:
        print(json.dumps(result["json"], ensure_ascii=False, indent=2))
    return result["exitCode"]


if __name__ == "__main__":
    sys.exit(main())
