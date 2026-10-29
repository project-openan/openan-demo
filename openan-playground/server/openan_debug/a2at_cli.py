"""A2A-T CLI 命令引擎（纯逻辑，无 IO）。

参考官方 A2A CLI（a2aproject/a2a-cli）的命令规范，为 OpenAN Playground 提供
A2A-T 语境下的命令行能力：card get / agent list / send(--stream|--async) /
task get(--wait|list|cancel) / help / version，支持 --json 协议原生输出与
可预测退出码（0 成功 / 1 传输或 HTTP 错误 / 2 用法错误 / 3 任务非 COMPLETED）。

本模块只负责：argv 解析、请求体/请求头构造、响应的 CLI 风格渲染；
HTTP IO 与目标解析在 routers/a2at_cli_router.py 完成。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from .agent.flow_env import ext_uri_for

CLI_NAME = "a2at"
CLI_VERSION = "1.0.0"

EXIT_OK = 0
EXIT_TRANSPORT = 1
EXIT_USAGE = 2
EXIT_TASK_FAILED = 3

SEND_SUFFIXES = ("/message:send", "/message:stream")
CARD_SUFFIX = "/.well-known/agent-card.json"
DEFAULT_EXTENSION = "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1"

TERMINAL_STATES = {
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_REJECTED",
}

_BUILTIN_TARGETS = {"default", "builtin", ""}

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class ParsedCommand:
    name: str                      # 主命令：help/version/card/agent/send/task
    args: list[str] = field(default_factory=list)
    flags: dict = field(default_factory=dict)   # 长选项 -> 值(True 为开关)
    raw: str = ""


@dataclass
class CliOutcome:
    exit_code: int
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    json: dict | list | None = None
    meta: dict = field(default_factory=dict)


class CliUsageError(Exception):
    """用法错误（exit 2）。"""


def error_outcome(message: str, exit_code: int = EXIT_TRANSPORT) -> CliOutcome:
    return CliOutcome(exit_code=exit_code, stderr=[message])


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

_SEND_FLAGS_WITH_VALUE = {"-a", "--agent", "--template", "-m", "--message", "--timeout", "--context"}
_TASK_FLAGS_WITH_VALUE = {"-a", "--agent", "--timeout", "--limit"}


def parse_argv(argv: list[str]) -> ParsedCommand:
    if not argv:
        raise CliUsageError("缺少命令，输入 'a2at help' 查看用法")
    # 与官方 A2A CLI 一致：命令行通常以二进制名开头（a2at ...）；输入框中也允许省略
    if argv[0].lower() == CLI_NAME:
        argv = argv[1:]
        if not argv:
            argv = ["help"]
    name = argv[0].lower()
    rest = argv[1:]
    if name in ("help", "--help", "-h"):
        return ParsedCommand(name="help", args=rest, raw=" ".join(argv))
    if name in ("version", "--version", "-V"):
        return ParsedCommand(name="version", raw=" ".join(argv))
    if name == "card":
        if not rest or rest[0].lower() != "get":
            raise CliUsageError("card 仅支持 'a2at card get [target]'")
        flags, positional = _collect_flags(rest[1:], {"-a", "--agent"})
        target = positional[0] if positional else flags.get("-a") or flags.get("--agent")
        if len(positional) > 1:
            raise CliUsageError("card get 只接受一个目标参数")
        return ParsedCommand(name="card", args=["get"], flags={**flags, "__target": target}, raw=" ".join(argv))
    if name == "agent":
        if not rest or rest[0].lower() != "list":
            raise CliUsageError("agent 仅支持 'a2at agent list'")
        flags, _positional = _collect_flags(rest[1:], set())
        return ParsedCommand(name="agent", args=["list"], flags=flags, raw=" ".join(argv))
    if name == "send":
        flags, positional = _collect_flags(rest, _SEND_FLAGS_WITH_VALUE)
        text_parts = list(positional)
        if flags.get("-m") is not None:
            text_parts.insert(0, flags.pop("-m"))
        if flags.get("--message") is not None:
            text_parts.insert(0, flags.pop("--message"))
        if not text_parts:
            raise CliUsageError("send 缺少消息文本：a2at send [-a target] \"文本\" 或 -m \"文本\"")
        flags["__text"] = " ".join(text_parts)
        flags["__target"] = flags.get("-a") or flags.get("--agent")
        return ParsedCommand(name="send", flags=flags, raw=" ".join(argv))
    if name == "task":
        if not rest:
            raise CliUsageError("task 需要 子命令 get|list|cancel，输入 'a2at help task' 查看用法")
        sub = rest[0].lower()
        if sub not in ("get", "list", "cancel"):
            raise CliUsageError(f"未知 task 子命令 {sub!r}（支持 get|list|cancel）")
        flags, positional = _collect_flags(rest[1:], _TASK_FLAGS_WITH_VALUE)
        if sub in ("get", "cancel") and not positional:
            raise CliUsageError(f"task {sub} 缺少任务 ID")
        if sub in ("get", "cancel") and len(positional) > 1:
            raise CliUsageError(f"task {sub} 只接受一个任务 ID")
        flags["__task_id"] = positional[0] if positional else None
        flags["__target"] = flags.get("-a") or flags.get("--agent")
        return ParsedCommand(name="task", args=[sub], flags=flags, raw=" ".join(argv))
    raise CliUsageError(f"未知命令 {argv[0]!r}，输入 'a2at help' 查看支持的命令")


def _collect_flags(argv: list[str], value_flags: set[str]) -> tuple[dict, list[str]]:
    flags: dict = {}
    positional: list[str] = []
    index = 0
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
            index += 1
            continue
        if token in ("--stream", "-s"):
            flags["--stream"] = True
            index += 1
            continue
        if token == "--async":
            flags["--async"] = True
            index += 1
            continue
        if token == "--wait":
            flags["--wait"] = True
            index += 1
            continue
        if token.startswith("--") or (token.startswith("-") and len(token) > 1):
            raise CliUsageError(f"未知选项 {token}")
        positional.append(token)
        index += 1
    return flags, positional


# ---------------------------------------------------------------------------
# 目标 / 请求构造
# ---------------------------------------------------------------------------


def normalize_agent_base(target: str | None) -> str | None:
    """URL 目标规整为 agent base（去掉路径上已带的端点后缀）；非 URL 返回 None。"""
    if not target:
        return None
    candidate = target.strip().rstrip("/")
    lower = candidate.lower()
    if not lower.startswith(("http://", "https://")):
        return None
    for suffix in SEND_SUFFIXES:
        if lower.endswith(suffix):
            candidate = candidate[: -len(suffix)]
            lower = candidate.lower()
    if lower.endswith(CARD_SUFFIX):
        candidate = candidate[: -len(CARD_SUFFIX)]
    return candidate.rstrip("/")


def is_builtin_target(target: str | None) -> bool:
    return (target or "").strip().lower() in _BUILTIN_TARGETS


def default_agent_base(agent_internal_url: str) -> str:
    base = agent_internal_url.strip().rstrip("/")
    if base.lower().endswith(SEND_SUFFIXES[0]):
        base = base[: -len(SEND_SUFFIXES[0])]
    return base.rstrip("/")


def build_send_body(
    text: str,
    template_uri: str | None = None,
    context_id: str | None = None,
) -> tuple[dict, str | None]:
    """构造 A2A SendMessageRequest body；返回 (body, 扩展头 URI)。"""
    metadata: dict = {}
    extension_header: str | None = None
    if template_uri:
        metadata["templateUri"] = template_uri
        ext_uri = ext_uri_for(template_uri)
        # 与前端 buildExampleRequest 对齐：Negotiation-T 模板 prompt 走 negotiationContext，不内嵌 ext 键
        if ext_uri and not template_uri.startswith("Negotiation-T"):
            metadata[ext_uri] = text
        extension_header = ext_uri or DEFAULT_EXTENSION
    message: dict = {
        "messageId": str(uuid.uuid4()),
        "role": "ROLE_USER",
        "parts": [{"text": text, "metadata": {}}],
    }
    if metadata:
        message["metadata"] = metadata
    if context_id:
        message["contextId"] = context_id
    return {"message": message}, extension_header


def build_headers(extension_uri: str | None) -> dict:
    headers = {"A2A-Version": "1.0", "Content-Type": "application/json"}
    if extension_uri:
        headers["A2A-Extensions"] = extension_uri
    return headers


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------


def _parts_text(parts) -> str:
    texts = []
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        if isinstance(part.get("text"), str):
            texts.append(part["text"])
        elif "data" in part:
            texts.append(json.dumps(part["data"], ensure_ascii=False))
    return "\n".join(t for t in texts if t)


def _first_artifact_text(task: dict) -> str:
    for artifact in task.get("artifacts") or []:
        text = _parts_text(artifact.get("parts"))
        if text:
            return text
    return ""


def render_card(card: dict) -> list[str]:
    capabilities = card.get("capabilities") or {}
    extensions = capabilities.get("extensions") or []
    interfaces = card.get("supportedInterfaces") or card.get("url") and [{"url": card.get("url")}] or []
    lines = [
        f"name          {card.get('name', '-')}",
        f"organization  {(card.get('provider') or {}).get('organization', '-')}",
        f"version       {card.get('version', '-')}",
        f"interface     {interfaces[0].get('url', '-') if interfaces else '-'}"
        + (f"  ({interfaces[0].get('protocolBinding', 'HTTP+JSON')})" if interfaces else ""),
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


def render_task(task: dict, *, latency_ms: int | None = None) -> list[str]:
    status = task.get("status") or {}
    state = status.get("state", "-")
    lines = [
        f"task          {task.get('id', '-')}",
        f"context       {task.get('contextId', '-')}",
        f"state         {state}",
    ]
    agent_text = _parts_text((status.get("message") or {}).get("parts"))
    if agent_text:
        first = agent_text if "\n" not in agent_text else agent_text.splitlines()[0] + " …"
        lines.append(f"agent message {first}")
    artifact_text = _first_artifact_text(task)
    if artifact_text:
        lines.append("artifact")
        for line in artifact_text.splitlines() or [""]:
            lines.append(f"  {line}")
    if latency_ms is not None:
        lines.append(f"latency       {latency_ms}ms")
    return lines


def render_task_summary(task: dict) -> list[str]:
    status = task.get("status") or {}
    return [
        f"task          {task.get('id', '-')}",
        f"state         {status.get('state', '-')}",
    ]


def render_task_list(payload) -> list[str]:
    if isinstance(payload, dict):
        tasks = payload.get("tasks") or payload.get("items") or []
        total = payload.get("totalSize", payload.get("total", len(tasks)))
    elif isinstance(payload, list):
        tasks, total = payload, len(payload)
    else:
        tasks, total = [], 0
    lines = [f"tasks         {total}"]
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = task.get("status") or {}
        lines.append(f"  {task.get('id', '-')}  {status.get('state', '-')}  context={task.get('contextId', '-')}")
    return lines


def parse_stream_event(event):
    """解析一条 SSE 事件，返回 (输出行, task_id, state, final)。

    兼容 a2a-sdk REST 流的两种形态：
    - 信封式：{"task": {...}} / {"statusUpdate": {...}} / {"artifactUpdate": {...}}
    - 裸事件式：Task / TaskStatusUpdateEvent / TaskArtifactUpdateEvent / Message
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


def render_stream_event(event: dict) -> list[str]:
    lines, _task_id, _state, _final = parse_stream_event(event)
    return lines


def extract_task(payload) -> dict | None:
    """message:send / tasks 响应中提取 Task 对象（兼容 {task:...} 与裸 Task 两种形态）。"""
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("task"), dict):
        return payload["task"]
    if payload.get("id") is not None and "status" in payload:
        return payload
    return None


# ---------------------------------------------------------------------------
# 帮助文本
# ---------------------------------------------------------------------------

_HELP_OVERVIEW = f"""{CLI_NAME} {CLI_VERSION} — A2A-T CLI（OpenAN Playground，命令规范参考官方 A2A CLI）

Usage:
  a2at <command> [flags] [args]

Commands:
  card get [target]                     获取目标 Agent 卡片（A2A 发现）
  agent list                            列出 Playground 内可用的 Mock Agent 目标
  send [-a target] [--template URI]     发送 A2A-T 消息并等待结果
        [-m TEXT] [TEXT...] [--stream] [--async]
  task get <id> [-a target] [--wait]    查询任务（--wait 轮询至终态）
  task list [-a target]                 列出目标任务的任务
  task cancel <id> [-a target]          取消任务
  help [command]                        查看帮助
  version                               查看版本

Targets:
  （缺省）/ default / builtin           内置 Mock Agent（/openan-playground/a2a）
  @<instance-id> 或 <instance-id|name>  打桩实例（MockAgent 管理中的实例）
  http(s)://host[:port][/path]          任意 A2A HTTP+JSON 端点（自动规整 base）

Flags:
  -a, --agent <target>   目标 Agent（见 Targets）
      --template <uri>   A2A-T 模板 URI（写入 metadata.templateUri 并携带 A2A-Extensions 头）
  -m, --message <text>   消息文本（也可用位置参数给出）
  -s, --stream           经 message:stream 以 SSE 流式接收事件
      --async            仅返回任务句柄（task id/state），不渲染完整结果
      --wait             task get 轮询至终态（默认 60s，可用 --timeout 调整）
      --timeout <sec>    请求超时（默认 120s；--wait 模式默认 60s）
      --context <id>     为消息附加 contextId
      --json             输出协议原生 JSON（而非渲染视图）

Exit codes:
  0 成功   1 传输/HTTP 错误   2 用法错误   3 任务以非 COMPLETED 终态结束

Examples:
  a2at card get
  a2at agent list
  a2at send -a default --template 'Task-T/network-layer/private-line-complaint/v1' "查询专线状态"
  a2at send -s -m "订阅严重故障告警"
  a2at task get <task-id> --wait"""

_HELP_BY_COMMAND = {
    "card": "Usage: a2at card get [target]\n\n获取目标 Agent 的 AgentCard（GET /.well-known/agent-card.json）。\ntarget 缺省为内置 Mock Agent；可为实例 id/名称或任意 URL。",
    "agent": "Usage: a2at agent list\n\n列出 Playground 可用目标：内置 Mock Agent + 打桩实例（含运行状态与端口）。",
    "send": "Usage: a2at send [-a target] [--template URI] [-m TEXT] [TEXT...] [--stream] [--async] [--json] [--timeout SEC] [--context ID]\n\n发送 A2A-T 消息：POST {target}/message:send（或 --stream 时 message:stream SSE）。\n--template 设置 metadata.templateUri 并自动携带 A2A-Extensions 头；\n--async 只输出任务句柄；--json 输出协议原生 JSON。",
    "task": "Usage: a2at task get <id> [-a target] [--wait] [--timeout SEC]\n       a2at task list [-a target]\n       a2at task cancel <id> [-a target]\n\n任务查询/列表/取消。get --wait 每 1s 轮询直至终态（默认 60s 超时）。",
    "help": "Usage: a2at help [command]\n\n显示总览或指定命令的帮助。",
    "version": f"Usage: a2at version\n\n输出 {CLI_NAME} {CLI_VERSION}。",
}


def help_text(command: str | None) -> str:
    if not command:
        return _HELP_OVERVIEW
    key = command.lower().lstrip("-")
    if key in _HELP_BY_COMMAND:
        return _HELP_BY_COMMAND[key]
    return f"未知命令 {command!r}\n\n{_HELP_OVERVIEW}"


def version_text() -> str:
    return f"{CLI_NAME} {CLI_VERSION} (OpenAN Playground A2A-T CLI; spec modeled on a2aproject/a2a-cli)"
