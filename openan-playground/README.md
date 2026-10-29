# OpenAN-Debug

OpenAN 对接联调系统：A2A-T Mock Agent（完整协议流程 + 打桩数据）+ 调试 Web（登录/种子变体管理/联调调试台/请求历史）。

## 结构

- `server/`：FastAPI 单体（Debug API `/api/v1/*` + Mock Agent `/debug/a2a/*`），SQLite。
- `frontend/`：React + Vite，构建后部署 `/OpenA2A-T/openan-debug-frontend`，访问路径 `/debug/`。
- `tools/stub_generator/`：本地 LLM 泛化 CLI（种子 → 变体 JSON）。
- `tools/a2at_cli/`：A2A-T 独立命令行客户端（`a2at`，与 Web 终端命令规范一致，参考官方 A2A CLI）。
- `deploy/`：阿里云 47.236.98.226 部署脚本与配置（nginx 独立 server 块，端口 9004）。

## 本地开发

cd server && uv sync && uv run pytest
cd server && OPENAN_DEBUG_ADMIN_PASSWORD=admin-pass-01 uv run uvicorn "openan_debug.main:create_app" --factory --port 9000
cd frontend && npm install && npm run dev    # http://localhost:5180/debug/

## A2A-T CLI

Playground 内置 A2A-T CLI 能力（命令规范参考官方 [A2A CLI](https://github.com/a2aproject/a2a-cli)），
两种形态共享同一命令规范与执行引擎：

- **Web 终端页**（`/cli` 路由，导航「A2A-T CLI」）：浏览器内直接敲 `a2at` 命令，
  服务端执行并回显 CLI 风格输出；支持 ↑/↓ 历史与 Tab 补全，执行记录写入请求历史（feature=a2at-cli）。
- **独立 Python CLI**（`tools/a2at_cli/cli.py`）：真实终端 / CI 可用；Playground 模式转发到
  服务端执行引擎（与 Web 终端行为一致），直连模式直接与任意 A2A HTTP+JSON 端点通信。

```bash
# Web 终端页与独立 CLI 共用的命令规范（服务端执行引擎 /api/v1/a2at-cli/exec）
a2at help [command]                  # 帮助
a2at version                         # 版本
a2at card get [target]               # 发现：获取 AgentCard
a2at agent list                      # Playground 目标列表（内置 Agent + 打桩实例）
a2at send [-a target] [--template URI] [-m TEXT] [TEXT...] [--stream] [--async]
a2at task get <id> [-a target] [--wait]
a2at task list [-a target]
a2at task cancel <id> [-a target]

# 目标 target：缺省/default/builtin=内置 Mock Agent；@实例ID或实例名=打桩实例；http(s)://=任意端点
# 通用旗标：--json 输出协议原生 JSON；--timeout 秒
# 退出码：0 成功 / 1 传输或 HTTP 错误 / 2 用法错误 / 3 任务非 COMPLETED 终态
```

独立 CLI 示例（依赖 httpx）：

```bash
# 直连模式：直接与 A2A-T 端点通信
python tools/a2at_cli/cli.py card get http://47.236.98.226:9002/openan-playground/a2a
python tools/a2at_cli/cli.py send -a http://47.236.98.226:9002/openan-playground/a2a \
    --template 'Task-T/network-layer/private-line-complaint/v1' "查询专线状态"

# Playground 模式：与 Web 终端完全一致（可用实例名目标与 agent list）
export OPENAN_PLAYGROUND_URL=http://47.236.98.226:9002/openan-playground
export OPENAN_PLAYGROUND_TOKEN=<JWT>          # 或 --username/--password 登录
python tools/a2at_cli/cli.py agent list
python tools/a2at_cli/cli.py send -a @energy-saving-stub --stream -m "执行节能评估"
```

## 打桩数据流

1. 页面上传种子（或 API POST /api/v1/seeds）。
2. 本地：python tools/stub_generator/cli.py --seed seed.json --template-uri "..." --count 5 --base-url ... --api-key ... --model ...
3. 页面"导入泛化变体"上传 variants.json。

## 联调

- Mock Agent 卡片：http://47.236.98.226:9004/debug/a2a/.well-known/agent-card.json
- 请求端点：POST http://47.236.98.226:9004/debug/a2a/message:send（HTTP+JSON binding），流式 /message:stream
- OpenAN 侧把 AgentCard supportedInterfaces[0].url 指向上址，或注册进 registry-center。
- 服务器 .env 配好 A2AT_LLM_* 后启用完整协议（协商分支）；未配置时自动降级直接打桩。

## 部署

cd frontend && npm run build
python deploy/deploy.py     # 打包上传 + 远端 uv 安装 + systemd + nginx + 健康检查
cd server && uv run python ../deploy/verify_remote_e2e.py
