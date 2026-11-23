# -*- coding: utf-8 -*-
"""场景接口：场景 = 故事线描述 + PSOP 工作流 + 智能体清单。

- GET  /api/v1/scenarios                  场景列表
- GET  /api/v1/scenarios/{id}             场景详情（故事线/工作流/智能体）
- POST /api/v1/scenarios/{id}/init        场景初始化：写入 PSOP 工作流 + 拉起场景智能体进程
- GET  /api/v1/scenarios/{id}/status      场景运行状态（各智能体 running/healthy）
- POST /api/v1/scenarios/{id}/stop        停止场景（停止其全部智能体进程）
"""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import agent_registry, scenario_registry, workflow_mode
from ..auth import get_current_user, require_admin
from ..deps import get_db
from .mock_instances_router import (
    _instance_view,
    _load_define,
    ensure_instance_running,
    terminate_instance,
)

router = APIRouter(prefix="/api/v1/scenarios", tags=["scenarios"])


def _agent_brief(agent_id: str) -> dict:
    try:
        d = agent_registry.resolve_agent_dir(agent_id)
        cfg = agent_registry.load_agent(d)
        return {
            "id": agent_id,
            "name": cfg.get("agentName") or cfg.get("name"),
            "port": cfg.get("port"),
            "endpoint": f"http://127.0.0.1:{cfg.get('port')}",
            "agentType": agent_registry.load_agent_class(d).agent_type,
        }
    except (FileNotFoundError, TypeError):
        return {"id": agent_id, "name": None, "port": None, "endpoint": None, "agentType": "generic"}


@router.get("")
def list_scenarios(_: dict = Depends(get_current_user)):
    return {"scenarios": scenario_registry.list_scenarios()}


@router.get("/{scenario_id}")
def scenario_detail(scenario_id: str, _: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        d = scenario_registry.resolve_scenario_dir(scenario_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    data = scenario_registry.load_scenario(d)
    story = data["scenario"]
    agents_cfg = data["agents"]
    workflow = data["workflow"]
    detail = {
        "id": story.get("id") or d.name,
        "name": story.get("name", ""),
        "nameEn": story.get("nameEn", ""),
        "description": story.get("description", ""),
        "storyline": story.get("storyline") or {},
        "entry": story.get("entry") or {},
        "workflow": {
            "id": workflow.get("id"),
            "name": workflow.get("name", ""),
            "steps": [
                {"name": s.get("name"), "type": s.get("type"), "agent": s.get("agent")}
                for s in workflow.get("steps", [])
            ],
        },
        "agents": [
            {
                "id": a.get("id"),
                "role": a.get("role", "participant"),
                "required": bool(a.get("required", True)),
                "description": a.get("description", ""),
                "agent": _agent_brief(a.get("id")),
            }
            for a in agents_cfg.get("agents", [])
        ],
        "availableWorkflows": [w["id"] for w in workflow_mode.list_builtin()],
    }
    return detail


# ---- 场景初始化 / 运行状态 / 停止 ----


def _load_scenario_or_raise(scenario_id: str) -> tuple[Path, dict]:
    try:
        d = scenario_registry.resolve_scenario_dir(scenario_id)
        return d, scenario_registry.load_scenario(d)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _scenario_agents(data: dict) -> list[dict]:
    return data["agents"].get("agents") or []


def _workflow_target_paths(data: dict, scenario_dir: Path) -> tuple[str, list[Path]]:
    """计算 PSOP 工作流的落位：全局注册表 workflows/<id>.json + 宿主 workDir 副本。"""
    story = data["scenario"]
    workflow = data["workflow"]
    wf_id = workflow.get("id") or (story.get("entry") or {}).get("workflowId") or scenario_dir.name
    targets = [workflow_mode.workflows_dir() / f"{wf_id.replace('-', '_')}.json"]
    host_id = (story.get("entry") or {}).get("hostAgentId") or next(
        (a.get("id") for a in data["agents"].get("agents", []) if a.get("role") == "workflow-host"), None
    )
    if host_id:
        try:
            host_cfg = agent_registry.load_agent(agent_registry.resolve_agent_dir(host_id))
            if host_cfg.get("workDir"):
                targets.append(Path(host_cfg["workDir"]) / "workflow.json")
        except (FileNotFoundError, KeyError, TypeError):
            pass
    return wf_id, targets


def _write_workflow_files(data: dict, targets: list[Path]) -> None:
    text = json.dumps(data["workflow"], ensure_ascii=False, indent=2) + "\n"
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    workflow_mode.clear_builtin_cache(data["workflow"].get("id"))


@router.post("/{scenario_id}/init")
def init_scenario(scenario_id: str, request: Request, _: dict = Depends(require_admin)):
    """场景初始化：校验三类配置 → 写入 PSOP 工作流（全局注册表 + 宿主 workDir）→ 拉起场景智能体进程。"""
    scenario_dir, data = _load_scenario_or_raise(scenario_id)
    story = data["scenario"]
    wf_id, targets = _workflow_target_paths(data, scenario_dir)
    _write_workflow_files(data, targets)

    define = _load_define()
    instances_by_id = {i["id"]: i for i in define.get("instances", [])}
    agent_results = []
    for entry in _scenario_agents(data):
        agent_id = entry.get("id")
        instance = instances_by_id.get(agent_id)
        if instance is None:
            agent_results.append({"id": agent_id, "status": "failed", "error": "agents/ 下未定义该实例"})
            continue
        agent_results.append(ensure_instance_running(instance))

    ready = all(r.get("status") in ("running", "already-running") for r in agent_results)
    return {
        "scenarioId": story.get("id") or scenario_dir.name,
        "name": story.get("name", ""),
        "status": "ready" if ready else "partial",
        "workflow": {"workflowId": wf_id, "written": [str(t) for t in targets]},
        "agents": agent_results,
        "storyline": {
            "phaseCount": len((story.get("storyline") or {}).get("phases") or []),
            "expectedOutcome": (story.get("storyline") or {}).get("expectedOutcome", ""),
        },
    }


@router.get("/{scenario_id}/status")
def scenario_status(scenario_id: str, request: Request, _: dict = Depends(get_current_user)):
    scenario_dir, data = _load_scenario_or_raise(scenario_id)
    define = _load_define()
    instances_by_id = {i["id"]: i for i in define.get("instances", [])}
    agents = []
    for entry in _scenario_agents(data):
        agent_id = entry.get("id")
        instance = instances_by_id.get(agent_id)
        if instance is None:
            agents.append({"id": agent_id, "role": entry.get("role", "participant"), "status": "undefined"})
            continue
        view = _instance_view(request, define, instance)
        agents.append({
            "id": agent_id,
            "role": entry.get("role", "participant"),
            "port": view["port"],
            "running": view["running"],
            "healthy": view["healthy"],
            "pid": view["pid"],
            "status": "running" if view["running"] else "stopped",
        })
    running = [a for a in agents if a.get("status") == "running"]
    overall = "ready" if len(running) == len(agents) and agents else ("partial" if running else "stopped")
    return {"scenarioId": data["scenario"].get("id") or scenario_dir.name, "status": overall, "agents": agents}


@router.post("/{scenario_id}/stop")
def stop_scenario(scenario_id: str, _: dict = Depends(require_admin)):
    scenario_dir, data = _load_scenario_or_raise(scenario_id)
    define = _load_define()
    instances_by_id = {i["id"]: i for i in define.get("instances", [])}
    results = []
    for entry in _scenario_agents(data):
        agent_id = entry.get("id")
        instance = instances_by_id.get(agent_id)
        results.append(terminate_instance(instance) if instance else {"status": "stopped", "id": agent_id, "note": "实例未定义"})
    return {"scenarioId": data["scenario"].get("id") or scenario_dir.name, "status": "stopped", "agents": results}
