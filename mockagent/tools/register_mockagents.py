# -*- coding: utf-8 -*-
"""把全部 MockAgent 卡片幂等注册到运行中的注册中心。

语义与 orchestration-center samples/start_agents_server.py 的
register_or_update_agent 一致：
  GET  /rest/v1/registry-center/agent-cards/{organization}/{name}  查询
  POST /rest/v1/registry-center/agent-cards                        新注册
  PUT  /rest/v1/registry-center/agent-cards/{organization}/{name}  内容变化时更新
  未变化则跳过（幂等，可重复执行）。

仅用标准库（urllib），便于在服务器上直接运行：
  python3 tools/register_mockagents.py --registry-url http://127.0.0.1:5000
  python3 tools/register_mockagents.py --registry-url http://127.0.0.1:5000 --dry-run
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MOCKAGENT_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = MOCKAGENT_ROOT / "agents"
API = "/rest/v1/registry-center/agent-cards"


def _request(method: str, url: str, payload: dict | None = None, timeout: int = 30):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
        try:
            return resp.status, json.loads(body)
        except json.JSONDecodeError:
            return resp.status, body


def load_cards(agents_dir: Path, only: list[str] | None) -> list[dict]:
    cards = []
    for path in sorted(agents_dir.glob("*/agent_card.json")):
        card = json.loads(path.read_text(encoding="utf-8"))
        name = card.get("name", "")
        if not name.startswith("mockagent_"):
            continue
        if only and name not in only:
            continue
        cards.append(card)
    return cards


def register_one(base: str, card: dict, dry_run: bool) -> str:
    name = card["name"]
    org = (card.get("provider") or {}).get("organization", "")
    quoted_name = urllib.parse.quote(name, safe="")
    quoted_org = urllib.parse.quote(org, safe="")

    try:
        status, existing = _request("GET", f"{base}{API}/{quoted_org}/{quoted_name}")
        if status != 200:
            existing = None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            existing = None
        else:
            raise

    if dry_run:
        return f"[dry-run] {'UPDATE' if existing else 'REGISTER'} {name} (org={org})"

    if existing is not None:
        remote = existing.get("agentCards") or []
        if remote:
            local_json = json.dumps(card, ensure_ascii=False, sort_keys=True)
            remote_json = json.dumps(remote[0], ensure_ascii=False, sort_keys=True)
            if local_json == remote_json:
                return f"UNCHANGED {name} (org={org}) — skipped"
            status, _ = _request("PUT", f"{base}{API}/{quoted_org}/{quoted_name}", {"agentCards": [card]})
            if status not in (200, 201, 204):
                return f"FAIL update {name}: HTTP {status}"
            return f"UPDATED {name} (org={org})"

    status, _ = _request("POST", base + API, {"agentCards": [card]})
    if status not in (200, 201):
        return f"FAIL register {name}: HTTP {status}"
    return f"REGISTERED {name} (org={org})"


def main() -> None:
    parser = argparse.ArgumentParser(description="Register all MockAgent cards into the registry center")
    parser.add_argument("--registry-url", default="http://127.0.0.1:5000",
                        help="注册中心地址（默认 http://127.0.0.1:5000）")
    parser.add_argument("--agents-dir", default=str(AGENTS_DIR), help="agents 目录")
    parser.add_argument("--seed-file", default=None,
                        help="直接使用 registry_seed/agentcard.json 数组文件（无需 agents 目录）")
    parser.add_argument("--only", default=None, help="仅注册这些卡片名，逗号分隔")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的动作（不访问注册中心）")
    args = parser.parse_args()

    only = [n.strip() for n in args.only.split(",") if n.strip()] if args.only else None
    if args.seed_file:
        cards = [c for c in json.loads(Path(args.seed_file).read_text(encoding="utf-8"))
                 if not only or c.get("name") in only]
    else:
        cards = load_cards(Path(args.agents_dir), only)
    if not cards:
        sys.exit("FAIL: 没有找到 mockagent_* 卡片（agents/*/agent_card.json）")

    base = args.registry_url.rstrip("/")
    print(f"注册 {len(cards)} 张卡片 -> {base}{API}")
    failures = 0
    for card in cards:
        line = register_one(base, card, args.dry_run)
        print(f"  {line}")
        if line.startswith("FAIL"):
            failures += 1
    if failures:
        sys.exit(f"FAIL: {failures} 张卡片注册失败")
    print("OK: 全部卡片已注册/已同步")


if __name__ == "__main__":
    main()
