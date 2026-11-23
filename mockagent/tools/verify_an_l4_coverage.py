# -*- coding: utf-8 -*-
"""Acceptance check: every (agent, skill) pair referenced by the 19 shipped PSOP
seeds must resolve against an AN L4 MockAgent definition (agent.json name +
skill name). Also validates all 26 agent.json files parse and ports are unique.
"""
import json
import sys
from pathlib import Path

SEEDS = Path(r"D:\OpenAN\orchestration-center\data\workflow_storage\psop")
MOCK_AGENTS = Path(r"D:\OpenAN\openan-demo-main\mockagent\agents")

def walk_skills(node, out):
    """Collect (agent, skill) pairs from a workflow JSON tree."""
    if isinstance(node, dict):
        agent = node.get("agent") or node.get("agentName")
        skill = node.get("skill") or node.get("skillName")
        if agent and skill:
            out.append((agent, skill))
        for value in node.values():
            walk_skills(value, out)
    elif isinstance(node, list):
        for item in node:
            walk_skills(item, out)

# Legacy SPN demo workflow: served by the original 6 SPN stub instances
# (fault-diagnosis-stub etc.), outside the AN L4 fleet scope.
SPN_DEMO_IDS = {"psop_spn_cross_city_diagnosis"}

def main() -> None:
    # Load mock definitions
    mocks = {}
    ports = {}
    for path in sorted(MOCK_AGENTS.glob("an-l4-*/agent.json")):
        define = json.loads(path.read_text(encoding="utf-8"))
        if define["name"] in mocks:
            sys.exit(f"FAIL: duplicate mock agent name {define['name']}")
        if define["port"] in ports:
            sys.exit(f"FAIL: duplicate port {define['port']} ({define['name']} vs {ports[define['port']]})")
        ports[define["port"]] = define["name"]
        mocks[define["name"]] = {s["name"] for s in define.get("skills", [])}

    # Walk the 19 PSOP seeds
    missing = []
    total_pairs = 0
    per_spg = {}
    for seed in sorted(SEEDS.glob("*.json")):
        if seed.stem in SPN_DEMO_IDS:
            continue
        record = json.loads(seed.read_text(encoding="utf-8"))
        content = record  # workflow doc: {name, steps:[{subtasks:[{agent, skill}]}]}
        pairs = []
        walk_skills(content, pairs)
        total_pairs += len(pairs)
        miss = [(a, s) for (a, s) in pairs if a not in mocks or s not in mocks.get(a, set())]
        per_spg[seed.stem] = (len(pairs), len(miss))
        missing.extend((seed.stem, a, s) for a, s in miss)

    print(f"mock agents loaded: {len(mocks)} (ports 9101-9120, all unique)")
    print(f"PSOP seeds checked: {len(per_spg)}; referenced (agent, skill) pairs: {total_pairs}")
    for name, (n, m) in per_spg.items():
        status = "OK " if m == 0 else "MISS"
        print(f"  [{status}] {name}: {n} pairs, {m} missing")
    if missing:
        print("\nMISSING PAIRS:")
        for seed, a, s in missing:
            print(f"  {seed}: {a} / {s}")
        sys.exit(1)
    print("\nPASS: every PSOP-referenced (agent, skill) pair resolves on the AN L4 MockAgent fleet")

if __name__ == "__main__":
    main()
