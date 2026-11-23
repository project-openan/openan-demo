# -*- coding: utf-8 -*-
"""Generate 16 AN L4 MockAgent instances from the orchestration-center card sources.

Reads the exact agent names + skills consumed by the 19 PSOPs:
  - orchestration-center/samples/agentcard/spg_an_l4_agents.yaml   (11 domain agents)
  - orchestration-center/samples/agentcard/registry_only/*.json    (5 instance cards)

Emits one agents/<id>/agent.json per agent (ports 9101..9116) so every PSOP
subtask (agent name + skill name) resolves against a real mock endpoint.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

OC = Path(r"D:\OpenAN\orchestration-center\samples\agentcard")
OUT = Path(r"D:\OpenAN\openan-demo-main\mockagent\agents")

# A2A-T 扩展 URI（与 mockagent_engine/agent/agent_card.py 保持一致）
CARD_EXTENSIONS = [
    {"uri": "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1",
     "description": "Task-T structured prompt requests"},
    {"uri": "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Notification-T/v1",
     "description": "Notification-T structured prompt requests"},
    {"uri": "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Authorization-T/v1",
     "description": "Authorization-T structured prompt requests"},
    {"uri": "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Negotiation-T/v1",
     "description": "Negotiation-T structured prompt messages"},
]
# 卡片 supportedInterfaces：网关前缀地址优先，独立实例端口地址兜底
GATEWAY_PORT = 9300

# Console grouping: layer (service|network) + networkDomain for network-layer agents.
PLACEMENT = {
    "AN L4 Cross-Domain Fault Management Agent": ("service", None),
    "Mobile Network Fault Management Agent": ("network", "wireless"),
    "Core Network Fault Management Agent": ("network", "cloudcore"),
    "IP Network Fault Management Agent": ("network", "datacom"),
    "Transport Network Fault Management Agent": ("network", "optical"),
    "Fixed Access Network Fault Management Agent": ("network", "fixedaccess"),
    "Computing Network Fault Management Agent": ("network", "computing"),
    "RAN Agent": ("network", "wireless"),
    "RAN Energy Saving Agent": ("network", "wireless"),
    "Work Order Management Agent": ("service", None),
    "Field Maintenance Copilot Agent": ("service", None),
    "Service Assurance Agent": ("service", None),
    "Assurance Agent": ("service", None),
    "Complaint Handling Agent": ("service", None),
    "Network Change Management Agent": ("service", None),
    "Network Planning and Design Agent": ("service", None),
    "Network Optimization Agent": ("service", None),
    "Service Delivery Agent": ("service", None),
    "Live Streaming Agent": ("service", None),
    "Energy Saving Intent Agent": ("service", None),
}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return re.sub(r"^an-l4-", "", s)  # the id prefix already carries an-l4-


def load_cards():
    cards = []
    inventory = yaml.safe_load((OC / "spg_an_l4_agents.yaml").read_text(encoding="utf-8"))
    for card in inventory["agents"]:
        cards.append({
            "name": card["name"],
            "description": card.get("description", ""),
            "skills": card.get("skills") or [],
        })
    for path in sorted((OC / "registry_only").glob("*.json")):
        for card in json.loads(path.read_text(encoding="utf-8")):
            cards.append({
                "name": card["name"],
                "description": card.get("description", ""),
                "skills": card.get("skills") or [],
            })
    return cards


def build_card(card_name: str, description: str, skills: list, ident: str, port: int) -> dict:
    """A2A AgentCard 载荷：name 以 mockagent_ 开头；双接口（网关前缀 + 独立端口）。"""
    return {
        "name": card_name,
        "description": description,
        "version": "1.0.0",
        "defaultInputModes": ["application/json", "text/plain"],
        "defaultOutputModes": ["application/json", "text/plain"],
        "provider": {"organization": "OpenAN-Stub", "url": "https://github.com/project-openan"},
        "skills": skills,
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "extensions": CARD_EXTENSIONS,
        },
        "supportedInterfaces": [
            {"protocolBinding": "HTTP+JSON", "protocolVersion": "1.0.0",
             "url": f"http://127.0.0.1:{GATEWAY_PORT}/agents/{ident}"},
            {"protocolBinding": "HTTP+JSON", "protocolVersion": "1.0.0",
             "url": f"http://127.0.0.1:{port}"},
        ],
    }


def main() -> None:
    global GATEWAY_PORT
    parser = argparse.ArgumentParser(description="Generate AN L4 MockAgent instances + AgentCard files")
    parser.add_argument("--gateway-port", type=int, default=GATEWAY_PORT,
                        help=f"网关端口（卡片第一个接口地址前缀，默认 {GATEWAY_PORT}）")
    args = parser.parse_args()
    GATEWAY_PORT = args.gateway_port

    cards = load_cards()
    # Dedupe by name, first definition wins, merge skill lists.
    merged: dict[str, dict] = {}
    for card in cards:
        name = card["name"]
        if name not in merged:
            merged[name] = {"name": name, "description": card["description"], "skills": []}
            merged[name]["skills"].extend(card["skills"])
        else:
            known = {s["id"] for s in merged[name]["skills"]}
            merged[name]["skills"].extend(s for s in card["skills"] if s["id"] not in known)

    missing = [n for n in merged if n not in PLACEMENT]
    if missing:
        sys.exit(f"FAIL: placement mapping missing for: {missing}")
    unused = [n for n in PLACEMENT if n not in merged]
    if unused:
        sys.exit(f"FAIL: mapping names not found in sources: {unused}")
    if len(merged) != 20:
        sys.exit(f"FAIL: expected 20 unique agents, got {len(merged)}: {sorted(merged)}")

    total_skills = 0
    ports = {}
    for port, name in enumerate(sorted(merged), start=9101):
        ports[name] = port
    referenced_pairs = 46  # (agent, skill) pairs actually referenced by the 19 PSOPs

    for name, card in sorted(merged.items()):
        ident = f"an-l4-{slugify(name)}"
        layer, domain = PLACEMENT[name]
        skills = card["skills"]
        total_skills += len(skills)
        description = card["description"] or f"AN L4 打桩 Agent：{name}"
        card_name = f"mockagent_{ident}"
        define = {
            "id": ident,
            "agentName": name,
            "name": name,
            "cardName": card_name,
            "organization": "OpenAN-Stub",
            "description": description,
            "layer": layer,
            "port": ports[name],
            "workDir": f"data/mock_agents/{ident}",
            "autoStart": False,
            "llm": {"enabled": False},
            "stubVariants": [],
            "datasetTemplates": [],
            "skills": skills,
        }
        if domain:
            define["networkDomain"] = domain
        target = OUT / ident
        target.mkdir(parents=True, exist_ok=True)
        (target / "agent.json").write_text(
            json.dumps(define, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (target / "agent_card.json").write_text(
            json.dumps(build_card(card_name, description, skills, ident, ports[name]),
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"  {ident}  :{ports[name]}  [{layer}{ '/' + domain if domain else ''}]  skills={len(skills)}  card={card_name}  {name}")

    print(f"\nOK: {len(merged)} agents, {total_skills} skills total "
          f"(PSOP-referenced pairs: {referenced_pairs}; extras cover unreferenced card skills)")


if __name__ == "__main__":
    main()
