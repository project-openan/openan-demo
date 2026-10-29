"""A2A-T CLI 执行 API。

POST /api/v1/a2at-cli/exec：接收一条 a2at 命令行，服务端解析并在目标 Agent 上执行，
返回 CLI 风格输出（stdout/stderr/exitCode/json），命令规范参考官方 A2A CLI
（a2aproject/a2a-cli）。目标解析：

- 缺省 / default / builtin → 内置 Mock Agent（settings.agent_internal_url）
- @<instance-id> 或实例 id/名称 → 打桩实例（须已运行）
- http(s)://... → 任意 A2A HTTP+JSON 端点

执行记录写入 RequestLog（feature=a2at-cli，direction=cli），可在请求历史中检索。
"""
from __future__ import annotations

import asyncio
import json
import shlex
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import a2at_cli as cli
from ..auth import get_current_user
from ..deps import get_db, get_settings
from ..models import Agent, RequestLog
from ..schemas import A2atCliExecRequest
from .mock_instances_router import _load_define, resolve_define_path

try:
    # 部署基线：实例进程内挂载（单进程单端口），可用性以挂载状态为准
    from ..instance_runtime import instance_mount_path, is_mounted, service_base_url
except ImportError:  # 仓库基线：standalone 子进程实例，按端口健康探测
    instance_mount_path = is_mounted = service_base_url = None

router = APIRouter(prefix="/api/v1/a2at-cli", tags=["a2at-cli"])

TASK_POLL_INTERVAL = 1.0
# a2a-sdk REST 路由要求携带 A2A-Version 头（GET /tasks 缺失时返回 400）
BASE_HEADERS = {"A2A-Version": "1.0"}


def _health_probe(port: int, timeout: float = 1.0) -> bool:
    try:
        response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 目标解析
# ---------------------------------------------------------------------------


def _find_instance(target: str) -> dict | None:
    define = _load_define(resolve_define_path())
    wanted = target.lstrip("@").strip().lower()
    for item in define.get("instances", []):
        instance_id = str(item.get("id", "")).lower()
        name = str(item.get("agentName") or item.get("name") or "").lower()
        if wanted == instance_id or wanted == name:
            return item
    return None


def _agent_id_for_instance(db: Session, instance: dict) -> int | None:
    organization = instance.get("organization", "OpenAN")
    name = instance.get("agentName") or instance.get("name")
    agent = db.execute(
        select(Agent).where(Agent.organization == organization, Agent.name == name, Agent.enabled == True)  # noqa: E712
    ).scalars().first()
    return agent.id if agent is not None else None


async def _resolve_target(
    request: Request, db: Session, settings, target: str | None
) -> tuple[str, int | None]:
    """返回 (agent_base, agent_row_id)。目标非法抛 CliUsageError，实例未运行抛 RuntimeError。"""
    raw = (target or "").strip()
    if cli.is_builtin_target(raw):
        return cli.default_agent_base(settings.agent_internal_url), request.app.state.default_agent_id
    url_base = cli.normalize_agent_base(raw)
    if url_base is not None:
        return url_base, None
    instance = _find_instance(raw)
    if instance is None:
        raise cli.CliUsageError(f"目标 {raw!r} 不是 URL，也未匹配到任何打桩实例（可用 'a2at agent list' 查看）")
    instance_id = str(instance.get("id"))
    if is_mounted is not None:
        # 部署基线：实例 A2A 应用挂载在主服务 /api/v1/mock-instances/{id}/a2a
        if not is_mounted(instance_id):
            raise RuntimeError(
                f"打桩实例 {instance_id} 未挂载，请先在 设置>MockAgent 中启动"
            )
        base = f"{service_base_url(settings)}{instance_mount_path(instance_id)}"
    else:
        port = int(instance.get("port") or 0)
        if port <= 0 or not _health_probe(port):
            raise RuntimeError(
                f"打桩实例 {instance_id}（:{port}）未运行，请先在 设置>MockAgent 中启动"
            )
        base = f"http://127.0.0.1:{port}"
    return base, _agent_id_for_instance(db, instance)


# ---------------------------------------------------------------------------
# 子命令执行
# ---------------------------------------------------------------------------


async def _exec_card(client: httpx.AsyncClient, base: str, timeout: float, *, as_json: bool) -> cli.CliOutcome:
    url = f"{base}/.well-known/agent-card.json"
    try:
        response = await client.get(url, timeout=timeout, headers=BASE_HEADERS)
    except httpx.HTTPError as exc:
        return cli.error_outcome(f"获取卡片失败（{url}）：{exc}")
    if response.status_code != 200:
        return cli.error_outcome(f"获取卡片失败：HTTP {response.status_code}（{url}）")
    try:
        card = response.json()
    except ValueError:
        return cli.error_outcome("卡片响应不是合法 JSON")
    outcome = cli.CliOutcome(exit_code=cli.EXIT_OK)
    if as_json:
        outcome.json = card
    else:
        outcome.stdout = cli.render_card(card)
    outcome.meta = {"target": base, "agentName": card.get("name")}
    return outcome


async def _exec_agent_list(*, as_json: bool) -> cli.CliOutcome:
    define = _load_define(resolve_define_path())
    rows = []
    for item in define.get("instances", []):
        port = int(item.get("port") or 0)
        if is_mounted is not None:
            healthy = is_mounted(str(item.get("id")))
        else:
            healthy = port > 0 and _health_probe(port)
        rows.append({
            "id": item.get("id"),
            "name": item.get("agentName") or item.get("name"),
            "organization": item.get("organization", "OpenAN"),
            "port": port,
            "layer": item.get("layer", "service"),
            "networkDomain": item.get("networkDomain"),
            "running": healthy,
            "target": f"@{item.get('id')}",
        })
    rows.sort(key=lambda r: (not r["running"], str(r["id"])))
    outcome = cli.CliOutcome(exit_code=cli.EXIT_OK)
    if as_json:
        outcome.json = {"instances": rows}
    else:
        outcome.stdout = [f"targets       {len(rows)} 个打桩实例（另有内置 Mock Agent 目标「default」）"]
        for row in rows:
            state = "运行中" if row["running"] else "未运行"
            domain = f"  domain={row['networkDomain']}" if row.get("networkDomain") else ""
            outcome.stdout.append(f"  {row['target']}  {row['name']}  :{row['port']}  {state}  [{row['layer']}]{domain}")
    outcome.meta = {"instances": len(rows)}
    return outcome


async def _read_stream(client: httpx.AsyncClient, base: str, body: dict, headers: dict, timeout: float) -> cli.CliOutcome:
    url = f"{base}/message:stream"
    lines: list[str] = []
    task_id = None
    final_state = None
    try:
        async with client.stream("POST", url, json=body, headers=headers, timeout=timeout) as response:
            if response.status_code != 200:
                text = (await response.aread()).decode("utf-8", "replace")
                return cli.error_outcome(f"流式发送失败：HTTP {response.status_code} {text[:300]}（{url}）")
            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    event = json.loads(payload)
                except ValueError:
                    lines.append(f"[stream] {payload[:200]}")
                    continue
                event_lines, ev_task_id, ev_state, ev_final = cli.parse_stream_event(event)
                lines.extend(event_lines)
                if ev_task_id:
                    task_id = ev_task_id
                if ev_state and (ev_final or ev_state in cli.TERMINAL_STATES):
                    final_state = ev_state
    except httpx.HTTPError as exc:
        return cli.error_outcome(f"流式传输失败（{url}）：{exc}")
    outcome = cli.CliOutcome(exit_code=cli.EXIT_OK, stdout=lines)
    if task_id:
        outcome.meta["taskId"] = task_id
    if final_state:
        outcome.meta["taskState"] = final_state
        outcome.stdout.append(f"task          {task_id or '-'}")
        outcome.stdout.append(f"state         {final_state}")
        if final_state != "TASK_STATE_COMPLETED":
            outcome.exit_code = cli.EXIT_TASK_FAILED
    return outcome


def _flag_timeout(flags: dict, default: float) -> float:
    raw = flags.get("--timeout")
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise cli.CliUsageError(f"--timeout 需要数字秒数，收到 {raw!r}") from exc
    if value <= 0 or value > 600:
        raise cli.CliUsageError("--timeout 需在 (0, 600] 秒范围内")
    return value


async def _exec_send(
    client: httpx.AsyncClient,
    base: str,
    parsed: cli.ParsedCommand,
    *,
    as_json: bool,
) -> cli.CliOutcome:
    text = parsed.flags.get("__text", "")
    template_uri = parsed.flags.get("--template")
    context_id = parsed.flags.get("--context")
    body, extension_uri = cli.build_send_body(text, template_uri, context_id)
    headers = cli.build_headers(extension_uri)
    timeout = _flag_timeout(parsed.flags, default=120.0)
    if parsed.flags.get("--stream") or parsed.flags.get("-s"):
        outcome = await _read_stream(client, base, body, headers, timeout)
        if as_json and outcome.exit_code == cli.EXIT_OK:
            outcome.json = {
                "taskId": outcome.meta.get("taskId"),
                "taskState": outcome.meta.get("taskState"),
                "eventLines": len(outcome.stdout),
            }
        return outcome
    url = f"{base}/message:send"
    started = time.monotonic()
    try:
        response = await client.post(url, json=body, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        return cli.error_outcome(f"发送失败（{url}）：{exc}")
    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code != 200:
        return cli.error_outcome(f"发送失败：HTTP {response.status_code} {response.text[:300]}（{url}）")
    try:
        payload = response.json()
    except ValueError:
        return cli.error_outcome("响应不是合法 JSON")
    task = cli.extract_task(payload)
    outcome = cli.CliOutcome(exit_code=cli.EXIT_OK)
    outcome.meta = {
        "target": base,
        "templateUri": template_uri,
        "latencyMs": latency_ms,
        "taskId": (task or {}).get("id"),
        "taskState": (((task or {}).get("status") or {}).get("state")),
    }
    if as_json:
        outcome.json = payload
        return outcome
    if parsed.flags.get("--async"):
        outcome.stdout = cli.render_task_summary(task or {})
        outcome.stdout.append(f"latency       {latency_ms}ms")
        return outcome
    if task is None:
        if isinstance(payload, dict) and payload.get("name"):
            outcome.stdout = cli.render_card(payload)
        else:
            outcome.stdout = [json.dumps(payload, ensure_ascii=False)[:400]]
        return outcome
    outcome.stdout = cli.render_task(task, latency_ms=latency_ms)
    state = outcome.meta.get("taskState")
    if state and state in cli.TERMINAL_STATES and state != "TASK_STATE_COMPLETED":
        outcome.exit_code = cli.EXIT_TASK_FAILED
    return outcome


async def _exec_task(
    client: httpx.AsyncClient,
    base: str,
    parsed: cli.ParsedCommand,
    *,
    as_json: bool,
) -> cli.CliOutcome:
    sub = parsed.args[0]
    task_id = parsed.flags.get("__task_id")
    wait = bool(parsed.flags.get("--wait")) and sub == "get"
    timeout = _flag_timeout(parsed.flags, default=60.0 if wait else 120.0)
    if sub == "get":
        url = f"{base}/tasks/{task_id}"
        deadline = time.monotonic() + timeout
        first = True
        while True:
            try:
                response = await client.get(url, timeout=min(timeout, 30.0), headers=BASE_HEADERS)
            except httpx.HTTPError as exc:
                return cli.error_outcome(f"任务查询失败（{url}）：{exc}")
            if response.status_code != 200:
                return cli.error_outcome(f"任务查询失败：HTTP {response.status_code}（{url}）")
            try:
                payload = response.json()
            except ValueError:
                return cli.error_outcome("任务响应不是合法 JSON")
            task = cli.extract_task(payload) or payload
            if not isinstance(task, dict):
                return cli.error_outcome("任务响应格式异常")
            state = (task.get("status") or {}).get("state")
            if not wait or state in cli.TERMINAL_STATES or time.monotonic() >= deadline:
                outcome = cli.CliOutcome(exit_code=cli.EXIT_OK)
                if as_json:
                    outcome.json = task
                else:
                    outcome.stdout = cli.render_task(task)
                    if wait and state not in cli.TERMINAL_STATES:
                        outcome.stdout.append(f"[wait] 已达超时（{timeout:.0f}s），以上为当前快照")
                    elif wait and not first:
                        outcome.stdout.append("[wait] 任务已达终态")
                outcome.meta = {"target": base, "taskId": task.get("id"), "taskState": state}
                if state and state in cli.TERMINAL_STATES and state != "TASK_STATE_COMPLETED":
                    outcome.exit_code = cli.EXIT_TASK_FAILED
                return outcome
            first = False
            await asyncio.sleep(TASK_POLL_INTERVAL)
    if sub == "list":
        url = f"{base}/tasks"
        try:
            response = await client.get(url, timeout=min(timeout, 30.0), headers=BASE_HEADERS)
        except httpx.HTTPError as exc:
            return cli.error_outcome(f"任务列表获取失败（{url}）：{exc}")
        if response.status_code != 200:
            return cli.error_outcome(f"任务列表获取失败：HTTP {response.status_code}（{url}）")
        try:
            payload = response.json()
        except ValueError:
            return cli.error_outcome("任务列表响应不是合法 JSON")
        outcome = cli.CliOutcome(exit_code=cli.EXIT_OK)
        if as_json:
            outcome.json = payload
        else:
            outcome.stdout = cli.render_task_list(payload)
        return outcome
    # cancel
    url = f"{base}/tasks/{task_id}:cancel"
    try:
        response = await client.post(url, json={}, timeout=min(timeout, 30.0), headers=BASE_HEADERS)
    except httpx.HTTPError as exc:
        return cli.error_outcome(f"任务取消失败（{url}）：{exc}")
    if response.status_code not in (200, 202):
        return cli.error_outcome(f"任务取消失败：HTTP {response.status_code}（{url}）")
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    task = cli.extract_task(payload) if isinstance(payload, dict) else None
    outcome = cli.CliOutcome(exit_code=cli.EXIT_OK)
    if as_json:
        outcome.json = payload
    elif task:
        outcome.stdout = cli.render_task_summary(task)
    else:
        outcome.stdout = [f"cancel        已发送取消请求（{task_id}，HTTP {response.status_code}）"]
    outcome.meta = {"target": base, "taskId": task_id}
    return outcome


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


async def _dispatch(request: Request, db: Session, settings, parsed: cli.ParsedCommand) -> cli.CliOutcome:
    as_json = bool(parsed.flags.get("--json"))
    if parsed.name == "help":
        return cli.CliOutcome(exit_code=cli.EXIT_OK, stdout=[cli.help_text(parsed.args[0] if parsed.args else None)])
    if parsed.name == "version":
        return cli.CliOutcome(exit_code=cli.EXIT_OK, stdout=[cli.version_text()])
    if parsed.name == "agent":
        return await _exec_agent_list(as_json=as_json)
    target = parsed.flags.get("__target")
    async with httpx.AsyncClient(timeout=120) as client:
        base, agent_row_id = await _resolve_target(request, db, settings, target)
        if parsed.name == "card":
            outcome = await _exec_card(client, base, _flag_timeout(parsed.flags, default=30.0), as_json=as_json)
        elif parsed.name == "send":
            outcome = await _exec_send(client, base, parsed, as_json=as_json)
        elif parsed.name == "task":
            outcome = await _exec_task(client, base, parsed, as_json=as_json)
        else:
            outcome = cli.error_outcome(f"未知命令 {parsed.name!r}", cli.EXIT_USAGE)
    outcome.meta["agentRowId"] = agent_row_id
    return outcome


@router.post("/exec")
async def exec_command(
    body: A2atCliExecRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
    settings=Depends(get_settings),
):
    started = time.monotonic()
    argv: list[str] | None
    try:
        argv = shlex.split(body.command)
        outcome = None
    except ValueError as exc:
        argv = None
        outcome = cli.error_outcome(f"命令解析失败（引号不配对等）：{exc}", cli.EXIT_USAGE)

    if argv is not None:
        try:
            parsed = cli.parse_argv(argv)
            outcome = await _dispatch(request, db, settings, parsed)
        except cli.CliUsageError as exc:
            outcome = cli.error_outcome(f"{exc}\n输入 'a2at help' 查看用法", cli.EXIT_USAGE)
        except RuntimeError as exc:
            outcome = cli.error_outcome(str(exc), cli.EXIT_TRANSPORT)
        except HTTPException as exc:
            outcome = cli.error_outcome(str(exc.detail), cli.EXIT_TRANSPORT)

    duration_ms = int((time.monotonic() - started) * 1000)
    try:
        db.add(
            RequestLog(
                agent_id=outcome.meta.get("agentRowId") or request.app.state.default_agent_id,
                template_uri=outcome.meta.get("templateUri"),
                direction="cli",
                feature="a2at-cli",
                request_body={"command": body.command, "argv": argv or [], "target": outcome.meta.get("target")},
                response_body={
                    "exitCode": outcome.exit_code,
                    "stdout": "\n".join(outcome.stdout)[:8000],
                    "stderr": "\n".join(outcome.stderr)[:4000],
                },
                task_state=outcome.meta.get("taskState"),
                negotiated=False,
                latency_ms=duration_ms,
                user_id=user.get("id"),
            )
        )
        db.commit()
    except Exception:
        db.rollback()
    return {
        "exitCode": outcome.exit_code,
        "stdout": outcome.stdout,
        "stderr": outcome.stderr,
        "json": outcome.json,
        "meta": outcome.meta,
        "durationMs": duration_ms,
    }
