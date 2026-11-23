# -*- coding: utf-8 -*-
"""聚合全部 MockAgent 卡片为注册中心初始化数据（seed 文件）。

扫描 agents/*/agent_card.json，输出 registry_seed/agentcard.json —— 与注册中心
文件后端（/opt/src-registry/data/agentcard.json，config file.path）同构的
AgentCard JSON 数组，可直接作为注册中心的初始化数据落盘，也可经
register_mockagents.py 在线注册到运行中的注册中心。
"""
import json
import sys
from pathlib import Path

MOCKAGENT_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = MOCKAGENT_ROOT / "agents"
SEED_PATH = MOCKAGENT_ROOT / "registry_seed" / "agentcard.json"


def main() -> None:
    cards = []
    for path in sorted(AGENTS_DIR.glob("*/agent_card.json")):
        card = json.loads(path.read_text(encoding="utf-8"))
        if not card.get("name", "").startswith("mockagent_"):
            print(f"SKIP（name 未以 mockagent_ 开头）: {path}", file=sys.stderr)
            continue
        cards.append(card)

    if not cards:
        sys.exit("FAIL: 没有可用的 agent_card.json（先运行 generate_an_l4_agents.py / patch_legacy_card_names.py）")

    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEED_PATH.write_text(
        json.dumps(cards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    skills = sum(len(c.get("skills") or []) for c in cards)
    print(f"OK: {len(cards)} 张卡片 -> {SEED_PATH}")
    print(f"    技能总数 {skills}；name 全部以 mockagent_ 开头")


if __name__ == "__main__":
    main()
