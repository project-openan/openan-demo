# -*- coding: utf-8 -*-
"""场景一键部署：每个场景独立拉起一套 Portal 栈。

组件（每场景）：
  1. mockagent 实例 ×N   —— 场景 agents.json 清单（scenario init，端口 9005-9010）
  2. 注册中心副本         —— registry-center 仓库副本，场景端口，HTTP 模式
  3. 编排中心后台副本     —— orchestration-center 仓库副本，场景端口，指向场景注册中心
  4. Portal 门户网关     —— 静态托管 portal/dist + API 反代（mockagent_engine.portal_gateway）

用法（在 mockagent/ 项目根，用带依赖的 Python）：
  python scripts/deploy_scenario_portal.py                          # 部署配置里的全部场景
  python scripts/deploy_scenario_portal.py --scenario live-assurance-demo
  python scripts/deploy_scenario_portal.py --status                 # 查看部署状态
  python scripts/deploy_scenario_portal.py --stop all               # 停止全部场景栈
  python scripts/deploy_scenario_portal.py --stop live-assurance-demo

配置：deploy/scenarios-portal.json（见文件内说明）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_CONFIG = PROJECT_ROOT / "deploy" / "scenarios-portal.json"
COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "node_modules", ".venv", ".venv*", "docs", "tests", "*.log", "data")
HTTPS_RE = re.compile(r"^(\s*enable_https\s*=\s*).*$", re.MULTILINE)
CONF_KEYS = {"ip": re.compile(r"^(\s*[Ii][Pp]\s*=\s*).*$", re.MULTILINE), "port": re.compile(r"^(\s*[Pp][Oo][Rr][Tt]\s*=\s*).*$", re.MULTILINE)}


# ---------------------------------------------------------------- 配置

def load_config(config_path: Path | None = None) -> dict:
    path = Path(config_path or DEFAULT_CONFIG)
    data = json.loads(path.read_text(encoding="utf-8"))
    defaults = data.get("defaults") or {}
    scenarios = data.get("scenarios") or []
    if not scenarios:
        raise SystemExit(f"{path}：scenarios 为空")
    merged = []
    for item in scenarios:
        entry = {**defaults, **item}
        for key in ("orchestrationCenterRepo", "registryCenterRepo", "portalDist", "runtimeRoot"):
            entry[key] = str(Path(_env_or(entry.get(key), key)).resolve())
        for key in ("registryPort", "orchPort", "portalPort"):
            if key not in entry:
                raise SystemExit(f"{path}：场景 {entry.get('scenarioId')} 缺少 {key}")
        merged.append(entry)
    return {"scenarios": merged, "defaults": defaults}


def _env_or(value: str, key: str) -> str:
    env_map = {"orchestrationCenterRepo": "OC_REPO", "registryCenterRepo": "REGISTRY_REPO", "portalDist": "PORTAL_DIST", "runtimeRoot": None}
    env_key = env_map.get(key)
    if env_key and os.environ.get(env_key):
        return os.environ[env_key]
    return value


def python_exe(entry: dict) -> str:
    return entry.get("pythonExe") or sys.executable


# ---------------------------------------------------------------- 卡片生成与导入

def build_agent_cards(define: dict) -> list[dict]:
    """从 agents/ 聚合定义生成 a2a-sdk 1.1.2 兼容 AgentCard（与 workflow_mode.agent_cards_for 同 schema）。"""
    cards = []
    for inst in define.get("instances", []):
        port = int(inst.get("port", 9300))
        cards.append({
            "name": inst.get("agentName") or inst.get("name"),
            "description": inst.get("description", ""),
            "version": "1.0",
            "provider": {"organization": inst.get("organization", "OpenAN")},
            "capabilities": {"streaming": False},
            "supportedInterfaces": [{
                "url": f"http://127.0.0.1:{port}/",
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.1",
            }],
        })
    return cards


def write_agent_cards(runtime_dir: Path, cards: list[dict]) -> Path:
    cards_dir = runtime_dir / "agent-cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    target = cards_dir / "agents.json"
    target.write_text(json.dumps({"agents": cards}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def import_cards_to_registry(registry_url: str, cards: list[dict], timeout: float = 15.0) -> None:
    """向场景注册中心导入 AgentCard（POST /rest/v1/registry-center/agent-cards）。"""
    import httpx

    resp = httpx.post(
        f"{registry_url.rstrip('/')}/rest/v1/registry-center/agent-cards",
        json={"agentCards": cards}, timeout=timeout, verify=False,
    )
    if resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"注册中心导入卡片失败 HTTP {resp.status_code}: {resp.text[:200]}")


# ---------------------------------------------------------------- server.conf 改写与副本

def rewrite_server_conf(conf_path: Path, replacements: dict[str, str]) -> None:
    """按键改写 server.conf（键名按原文件大小写），保留注释与其余行；无该键则追加。"""
    text = conf_path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*).*$", re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(lambda m: m.group(1) + value, text, count=1)
        else:
            text += f"\n{key}={value}\n"
    conf_path.write_text(text, encoding="utf-8")


def patch_registry_name_validation(registry_copy: Path) -> bool:
    """场景注册中心副本补丁：放宽 AgentCard name 校验以支持中文 Agent 名。

    上游校验只允许 ASCII（字母/数字/-/_/空格），而 PSOP 工作流按中文名
    （如"无线域打桩 Agent"）解析目标 Agent——副本是本脚本生成的运行时
    产物，就地打补丁，不影响上游仓库。
    """
    target = registry_copy / "agent_registry" / "model" / "validated_agentcard.py"
    if not target.is_file():
        return False
    text = target.read_text(encoding="utf-8")
    original = "_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+(?:\\s+[a-zA-Z0-9_-]+)*$')"
    patched = (
        "_NAME_PATTERN = re.compile(r'^[\\w][\\w\\- ]*$')  # scenario-deploy patch: allow CJK agent names"
    )
    if patched in text:
        return True
    if original not in text:
        return False
    target.write_text(text.replace(original, patched, 1), encoding="utf-8")
    return True


def copy_repo_subset(repo: Path, target: Path) -> Path:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(repo, target, ignore=COPY_IGNORE)
    return target


# ---------------------------------------------------------------- 进程管理

def _log_file(runtime_dir: Path, name: str):
    logs = runtime_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return open(logs / f"{name}.log", "ab")


def spawn_component(name: str, cmd: list[str], cwd: Path, runtime_dir: Path, env: dict | None = None) -> subprocess.Popen:
    log = _log_file(runtime_dir, name)
    merged_env = {**os.environ, **(env or {})}
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=merged_env, stdout=log, stderr=subprocess.STDOUT)
    return proc


def wait_http(url: str, timeout: float, expect: tuple[int, ...] | None = None) -> bool:
    """轮询 HTTP 探测：拿到任何 HTTP 响应（<500）即视为组件存活（/docs 等可能被禁用）。"""
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(url, timeout=2.0, verify=False, follow_redirects=True)
            if resp.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.8)
    return False


def ensure_component_venv(component_dir: Path, python_exe: str = "") -> str:
    """为组件副本准备独立 venv（避免与宿主环境依赖版本冲突），返回 venv python 路径。

    优先用 uv（快）；无 uv 时回退 python -m venv + pip。依赖来自副本内 requirements.txt。
    """
    venv_dir = component_dir / ".venv"
    venv_python = venv_dir / ("Scripts\\python.exe" if os.name == "nt" else "bin/python")
    if venv_python.exists():
        return str(venv_python)
    uv = shutil.which("uv")
    if uv:
        subprocess.run([uv, "venv", str(venv_dir), "--python", (python_exe or sys.executable)], check=True, capture_output=True)
    else:
        subprocess.run([python_exe or sys.executable, "-m", "venv", str(venv_dir)], check=True)
    requirements = component_dir / "requirements.txt"
    if requirements.exists():
        base_cmd = [uv, "pip", "install", "--python", str(venv_python)] if uv else [str(venv_python), "-m", "pip", "install"]
        result = subprocess.run([*base_cmd, "-r", str(requirements)], capture_output=True, text=True)
        if result.returncode != 0:
            # 换清华镜像重试一次
            result2 = subprocess.run([*base_cmd, "-r", str(requirements), "--default-index", "https://pypi.tuna.tsinghua.edu.cn/simple"], capture_output=True, text=True)
            if result2.returncode != 0:
                tail = (result2.stderr or result.stderr or "")[-800:]
                raise RuntimeError(f"组件依赖安装失败（{component_dir.name}）：{tail}")
    return str(venv_python)


def log_tail(runtime_dir: Path, name: str, lines: int = 30) -> str:
    log = runtime_dir / "logs" / f"{name}.log"
    if not log.exists():
        return ""
    return "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def stop_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
    else:
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def save_state(runtime_dir: Path, state: dict) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "deploy-state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state(runtime_dir: Path) -> dict | None:
    path = runtime_dir / "deploy-state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ---------------------------------------------------------------- 场景部署

def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=10).stdout
            return str(pid) in out
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def scenario_init(entry: dict) -> dict:
    """拉起场景 mockagent 实例（写入 PSOP 工作流 + spawn，复用引擎逻辑）。"""
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    from mockagent_engine import scenario_registry
    from mockagent_engine.routers.mock_instances_router import ensure_instance_running

    scenario_dir = scenario_registry.resolve_scenario_dir(entry["scenarioId"])
    data = scenario_registry.load_scenario(scenario_dir)
    define = __import__("mockagent_engine.agent_registry", fromlist=["load_define"]).load_define()
    instances_by_id = {i["id"]: i for i in define.get("instances", [])}
    results = []
    for agent in data["agents"].get("agents", []):
        instance = instances_by_id.get(agent.get("id"))
        results.append(ensure_instance_running(instance) if instance else {"id": agent.get("id"), "status": "failed", "error": "agents/ 未定义"})
    return {"agents": results, "workflow": data["workflow"].get("id")}


def deploy_scenario(entry: dict, spawn_timeout: float | None = None) -> dict:
    scenario_id = entry["scenarioId"]
    runtime_dir = Path(entry["runtimeRoot"]) / scenario_id
    timeout = float(spawn_timeout or entry.get("spawnTimeoutSeconds", 40))
    print(f"\n=== 场景部署 {scenario_id} ===")
    state = {"scenarioId": scenario_id, "components": {}, "startedAt": time.strftime("%Y-%m-%d %H:%M:%S")}

    # 1) mockagent 实例（含 PSOP 工作流写入）
    init = scenario_init(entry)
    state["components"]["mockagents"] = {"agents": init["agents"], "workflowId": init["workflow"]}
    ok_agents = all(a.get("status") in ("running", "already-running") for a in init["agents"])
    print(f"  [1/6] mockagent 实例：{'OK' if ok_agents else 'PARTIAL/FAILED'}（工作流 {init['workflow']}）")
    _persist_mockagent_pids(runtime_dir, init["agents"])

    # 2) 注册中心副本
    reg_repo = Path(entry["registryCenterRepo"])
    reg_dir = copy_repo_subset(reg_repo, runtime_dir / "registry-center")
    patch_ok = patch_registry_name_validation(reg_dir)
    conf = reg_dir / "etc" / "conf" / "server.conf"
    if conf.exists():
        rewrite_server_conf(conf, {
            "IP": "127.0.0.1",
            "PORT": str(entry["registryPort"]),
            "enable_https": "false" if entry.get("registry", {}).get("enableHttps") is False else "true",
            # 场景演示栈默认关闭卡片签名校验（导入的是本地生成的卡片）
            "signature_validation_enabled": "false" if entry.get("registry", {}).get("signatureValidation", False) is False else "true",
        })
    registry_url = f"http://127.0.0.1:{entry['registryPort']}"
    use_venv = entry.get("componentVenv", True)
    reg_python = ensure_component_venv(reg_dir, python_exe(entry)) if use_venv else python_exe(entry)
    print(f"  [2/6] 注册中心环境：{'独立 venv ' + Path(reg_python).parent.parent.name if use_venv else '宿主 Python'}")
    reg_proc = spawn_component("registry-center", [reg_python, "-m", "agent_registry.start"], reg_dir, runtime_dir)
    state["components"]["registry-center"] = {"pid": reg_proc.pid, "port": entry["registryPort"]}
    reg_ok = wait_http(f"{registry_url}/rest/v1/registry-center/agent-cards", timeout)
    print(f"  [2/6] 注册中心 ：{'OK' if reg_ok else 'FAILED'} http://127.0.0.1:{entry['registryPort']} (pid={reg_proc.pid})")

    # 3) AgentCard 导入
    from mockagent_engine import agent_registry

    cards = build_agent_cards(agent_registry.load_define())
    cards_file = write_agent_cards(runtime_dir, cards)
    cards_ok = False
    if reg_ok:
        try:
            import_cards_to_registry(registry_url, cards)
            cards_ok = True
        except Exception as error:
            print(f"  [3/6] 卡片导入失败：{error}")
    print(f"  [3/6] AgentCard 导入：{'OK' if cards_ok else 'SKIPPED/FAILED'}（{cards_file}，{len(cards)} 张）")
    state["components"]["agent-cards"] = {"file": str(cards_file), "count": len(cards), "imported": cards_ok}

    # 4) 编排中心后台副本
    orch_repo = Path(entry["orchestrationCenterRepo"])
    orch_dir = copy_repo_subset(orch_repo, runtime_dir / "orchestration-center")
    orch_conf = orch_dir / "etc" / "conf" / "server.conf"
    if orch_conf.exists():
        rewrite_server_conf(orch_conf, {
            "port": str(entry["orchPort"]),
            "enable_https": "false" if entry.get("orch", {}).get("enableHttps") is False else "true",
            "agent_registry_url": registry_url,
        })
    orch_env = {**(entry.get("orch", {}).get("env") or {}), "PYTHONIOENCODING": "utf-8"}
    orch_python = ensure_component_venv(orch_dir, python_exe(entry)) if use_venv else python_exe(entry)
    orch_proc = spawn_component("orchestration-center", [orch_python, "-m", "orchestrate.start"], orch_dir, runtime_dir, env=orch_env)
    state["components"]["orchestration-center"] = {"pid": orch_proc.pid, "port": entry["orchPort"], "registryUrl": registry_url}
    orch_ok = wait_http(f"http://127.0.0.1:{entry['orchPort']}/", timeout)
    print(f"  [4/6] 编排中心 ：{'OK' if orch_ok else 'FAILED'} http://127.0.0.1:{entry['orchPort']} (pid={orch_proc.pid})")

    # 5) Portal 门户网关
    routes = [
        {**r, "upstream": f"http://127.0.0.1:{entry[r['target'] + 'Port']}"}
        for r in (entry.get("gateway", {}).get("routes") or [])
    ]
    gateway_env = {"PORTAL_DIST_DIR": entry["portalDist"], "PORTAL_ROUTES_JSON": json.dumps(routes), "PORTAL_PORT": str(entry["portalPort"]), "PYTHONIOENCODING": "utf-8"}
    gw_proc = spawn_component("portal-gateway", [python_exe(entry), "-m", "mockagent_engine.portal_gateway"], PROJECT_ROOT, runtime_dir, env=gateway_env)
    state["components"]["portal-gateway"] = {"pid": gw_proc.pid, "port": entry["portalPort"], "routes": routes, "dist": entry["portalDist"]}
    gw_ok = wait_http(f"http://127.0.0.1:{entry['portalPort']}/healthz", timeout)
    print(f"  [5/6] Portal   ：{'OK' if gw_ok else 'FAILED'} http://127.0.0.1:{entry['portalPort']} (pid={gw_proc.pid})")

    # 6) 汇总
    state["status"] = "ready" if (ok_agents and reg_ok and cards_ok and orch_ok and gw_ok) else "partial"
    state["urls"] = {
        "portal": f"http://127.0.0.1:{entry['portalPort']}/",
        "orchestrationCenter": f"http://127.0.0.1:{entry['orchPort']}/docs",
        "registry": registry_url,
    }
    save_state(runtime_dir, state)
    print(f"  [6/6] 部署状态：{state['status']} → 访问 {state['urls']['portal']}")
    return state


def _persist_mockagent_pids(runtime_dir: Path, agent_results: list[dict]) -> None:
    """把本进程拉起的 mockagent 实例 pid 写入各实例 workDir 的 instance.pid，供 --stop 回收。"""
    from mockagent_engine import agent_registry

    instances_by_id = {i["id"]: i for i in agent_registry.load_define().get("instances", [])}
    for result in agent_results:
        if result.get("status") != "running" or not result.get("pid"):
            continue
        instance = instances_by_id.get(result["id"])
        if not instance:
            continue
        try:
            pid_file = Path(instance["workDir"]) / "instance.pid"
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            pid_file.write_text(str(result["pid"]), encoding="utf-8")
        except OSError:
            pass


def stop_scenario(entry: dict) -> dict:
    runtime_dir = Path(entry["runtimeRoot"]) / entry["scenarioId"]
    state = load_state(runtime_dir)
    if not state:
        return {"scenarioId": entry["scenarioId"], "status": "not-deployed"}
    # mockagent 实例：pid 已持久化到 workDir/instance.pid，用引擎 terminate_instance 回收（含孤儿清理）
    try:
        from mockagent_engine import agent_registry
        from mockagent_engine.routers.mock_instances_router import terminate_instance

        instances_by_id = {i["id"]: i for i in agent_registry.load_define().get("instances", [])}
        for result in (state.get("components", {}).get("mockagents", {}) or {}).get("agents", []):
            instance = instances_by_id.get(result.get("id"))
            if instance:
                terminate_instance(instance)
    except Exception as error:
        print(f"  mockagent 回收异常（忽略）：{error}")
    for name, comp in state.get("components", {}).items():
        if name == "mockagents":
            continue
        pid = comp.get("pid")
        if pid and _pid_alive(pid):
            stop_tree(pid)
            print(f"  stopped {name} (pid={pid})")
    save_state(runtime_dir, {**state, "status": "stopped", "components": {
        k: {**v, "pid": None} for k, v in state.get("components", {}).items()
    }})
    return {"scenarioId": entry["scenarioId"], "status": "stopped"}


def status_scenario(entry: dict) -> dict:
    runtime_dir = Path(entry["runtimeRoot"]) / entry["scenarioId"]
    state = load_state(runtime_dir)
    if not state:
        return {"scenarioId": entry["scenarioId"], "status": "not-deployed"}
    components = {}
    for name, comp in state.get("components", {}).items():
        pid = comp.get("pid")
        components[name] = {**{k: v for k, v in comp.items() if k != "pid"}, "pid": pid, "alive": bool(pid and _pid_alive(pid))}
    return {"scenarioId": entry["scenarioId"], "status": state.get("status"), "components": components, "urls": state.get("urls", {})}


# ---------------------------------------------------------------- CLI

def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="场景一键部署：mockagent 实例 + 注册中心 + 编排中心后台 + Portal 门户")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--scenario", help="只部署/停止指定场景（默认全部）")
    parser.add_argument("--status", action="store_true", help="查看部署状态")
    parser.add_argument("--stop", nargs="?", const="all", help="停止指定场景或 all")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    entries = config["scenarios"]
    if args.scenario:
        entries = [e for e in entries if e["scenarioId"] == args.scenario]
        if not entries:
            raise SystemExit(f"配置中无场景 {args.scenario}")

    if args.status:
        for entry in entries:
            print(json.dumps(status_scenario(entry), ensure_ascii=False, indent=2))
        return
    if args.stop:
        targets = entries if args.stop == "all" else [e for e in entries if e["scenarioId"] == args.stop]
        for entry in targets:
            stop_scenario(entry)
        return

    summary = []
    try:
        for entry in entries:
            summary.append(deploy_scenario(entry))
    except KeyboardInterrupt:
        print("\n中断：回滚已拉起进程…")
        for entry in entries:
            stop_scenario(entry)
        raise
    print("\n===== 部署汇总 =====")
    for item in summary:
        print(f"{item['scenarioId']}: {item['status']}  portal={item['urls']['portal']}")
    if any(item["status"] != "ready" for item in summary):
        sys.exit(1)


if __name__ == "__main__":
    main()
