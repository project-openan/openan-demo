# a2at — A2A-T CLI（独立命令行客户端）

OpenAN Playground 的 A2A-T 命令行客户端。命令规范与 Playground Web 终端
（「A2A-T CLI」页）完全一致，参考官方 [A2A CLI](https://github.com/a2aproject/a2a-cli)。

## 安装

零安装：仅需 Python ≥3.10 与 httpx。

```bash
pip install httpx
# 可选：做成本机命令
# PowerShell: function a2at { python D:\path\to\tools\a2at_cli\cli.py @args }
# Bash:       alias a2at='python /path/to/tools/a2at_cli/cli.py'
```

## 命令

```
a2at help [command]                  帮助
a2at version                         版本
a2at card get [target]               发现：获取 AgentCard
a2at agent list                      Playground 目标列表（需 Playground 模式）
a2at send [-a target] [--template URI] [-m TEXT] [TEXT...] [--stream] [--async]
a2at task get <id> [-a target] [--wait]
a2at task list [-a target]
a2at task cancel <id> [-a target]
```

通用旗标：`--json`（协议原生 JSON 输出）、`--timeout <sec>`（默认 120s）、`--context <id>`。
`send --template` 会写入 `metadata.templateUri` 并自动携带 `A2A-Extensions` 头；
`send --stream` 走 `message:stream` SSE，逐事件回显。

## 两种模式

**直连模式（默认）**：本机直接与 A2A HTTP+JSON 端点通信，`-a` 需要 http(s) URL
（或环境变量 `A2AT_TARGET`）。URL 会自动规整：`.../debug/a2a/message:send`、`.../`、
`.../.well-known/agent-card.json` 均可，自动取 agent base。

**Playground 模式**：给 `--playground <URL>`（或 `OPENAN_PLAYGROUND_URL`）后，命令转发给
Playground 服务端执行引擎 `/api/v1/a2at-cli/exec` —— 行为与 Web 终端一致，额外支持
打桩实例目标（实例 id / 名称 / `@instance-id`）与 `agent list`。鉴权：
`--pg-token` / `OPENAN_PLAYGROUND_TOKEN`，或 `--pg-user`+`--pg-pass` /
`OPENAN_PLAYGROUND_USERNAME`+`OPENAN_PLAYGROUND_PASSWORD` 登录获取 token。

## 示例

```bash
# 直连：发现 + 模板消息 + 流式
python cli.py card get http://47.236.98.226:9002/openan-playground/a2a
python cli.py send -a http://47.236.98.226:9002/openan-playground/a2a \
    --template 'Task-T/network-layer/private-line-complaint/v1' "查询专线状态"
python cli.py send -a http://127.0.0.1:9100/debug/a2a --stream -m "订阅严重故障告警"

# Playground：打桩实例目标 + 任务轮询
export OPENAN_PLAYGROUND_URL=http://47.236.98.226:9002/openan-playground
export OPENAN_PLAYGROUND_TOKEN=<JWT>
python cli.py agent list
python cli.py send -a @energy-saving-stub --async -m "执行节能评估"
python cli.py task get <task-id> --wait --json

# CI 中用退出码判断（0 成功 / 1 传输或 HTTP 错误 / 2 用法错误 / 3 任务非 COMPLETED）
python cli.py send -a $A2AT_TARGET "冒烟用例" || echo "task not completed"
```

## 测试

```bash
cd server && uv run pytest ../tools/a2at_cli/test_a2at_cli.py
```
