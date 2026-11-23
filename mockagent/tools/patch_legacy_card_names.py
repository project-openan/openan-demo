# -*- coding: utf-8 -*-
"""为 6 个 legacy SPN stub 实例补 cardName（mockagent_ 前缀）并生成 agent_card.json。

与 tools/generate_an_l4_agents.py 的卡片规则一致：name 以 mockagent_ 开头、
双 supportedInterfaces（网关前缀 + 独立端口）、四条 A2A-T 扩展能力。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from generate_an_l4_agents import GATEWAY_PORT, build_card  # noqa: E402

AGENTS = Path(__file__).resolve().parents[1] / "agents"
LEGACY_IDS = [
    "fault-diagnosis-stub",
    "recovery-stub",
    "energy-saving-stub",
    "wireless-domain-stub",
    "livestream-stub",
    "service-assurance-stub",
]

DEFAULT_STUB_SKILL = [{
    "id": "stub-responder",
    "name": "Stub responder",
    "description": "Returns stubbed business data for configured A2A-T templates",
    "tags": ["stub", "mock", "debug"],
}]


def main() -> None:
    for ident in LEGACY_IDS:
        path = AGENTS / ident / "agent.json"
        if not path.is_file():
            print(f"SKIP: {ident}（无 agent.json）")
            continue
        define = json.loads(path.read_text(encoding="utf-8"))
        card_name = f"mockagent_{ident}"
        define["cardName"] = card_name
        path.write_text(json.dumps(define, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (AGENTS / ident / "agent_card.json").write_text(
            json.dumps(build_card(card_name, define.get("description", ""), DEFAULT_STUB_SKILL,
                                  ident, int(define.get("port", 9300))),
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"  {ident}: cardName={card_name} card-file OK (port {define.get('port')})")
    print("\nOK: legacy stubs patched")


if __name__ == "__main__":
    main()
