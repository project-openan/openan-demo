# -*- coding: utf-8 -*-
"""Print the aggregated MockAgent registry summary."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mockagent_engine.agent_registry import load_define

define = load_define()
instances = define["instances"]
an_l4 = [i for i in instances if i["id"].startswith("an-l4-")]
legacy = [i for i in instances if not i["id"].startswith("an-l4-")]
ports = sorted(i["port"] for i in instances)
skills = sum(len(i.get("skills") or []) for i in an_l4)
cards = sum(1 for i in instances if (i.get("cardName") or "").startswith("mockagent_"))
card_files = len(list((Path(__file__).resolve().parents[1] / "agents").glob("*/agent_card.json")))
print(f"instances: {len(instances)} total = {len(legacy)} legacy + {len(an_l4)} an-l4")
print(f"ports: {ports[0]}..{ports[-1]} unique={len(set(ports))}")
print(f"an-l4 card skills total: {skills}")
print(f"cardName mockagent_*: {cards}/{len(instances)}; agent_card.json files: {card_files}")
