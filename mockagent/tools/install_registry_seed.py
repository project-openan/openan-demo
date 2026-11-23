# -*- coding: utf-8 -*-
"""把 MockAgent 种子卡片安装为注册中心的初始化数据（文件后端）。

注册中心（/opt/src-registry）的持久化即初始化数据：
  data/agentcard.json     —— AgentCard 数组（snake_case 字段）
  data/agentregistry.json —— 每卡状态元数据（status/owner/layer/timestamps）

本脚本：
  1. 读取种子文件（registry_seed/agentcard.json，camelCase AgentCard JSON）
  2. 转换为注册中心文件格式（snake_case）
  3. 备份现有数据文件（时间戳后缀）
  4. 按 (name, provider.organization) 去重合并，原子写回（保留权限）
  5. 为新卡片追加 published 状态元数据
  6. 可选重启 openan-registry 服务使内存态生效

用法（在注册中心所在服务器上）：
  python3 install_registry_seed.py --seed-file /tmp/mockagent_registry_seed.json
  python3 install_registry_seed.py --seed-file ... --dry-run
  python3 install_registry_seed.py --seed-file ... --restart
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DATA_DIR = "/opt/src-registry/data"
DEFAULT_SERVICE = "openan-registry.service"


def card_to_registry_format(card: dict) -> dict:
    """AgentCard camelCase JSON -> 注册中心文件后端的 snake_case 形态。"""
    out = json.loads(json.dumps(card, ensure_ascii=False))  # deep copy
    if "defaultInputModes" in out:
        out["default_input_modes"] = out.pop("defaultInputModes")
    if "defaultOutputModes" in out:
        out["default_output_modes"] = out.pop("defaultOutputModes")
    if "supportedInterfaces" in out:
        interfaces = out.pop("supportedInterfaces")
        for item in interfaces:
            if "protocolBinding" in item:
                item["protocol_binding"] = item.pop("protocolBinding")
            if "protocolVersion" in item:
                item["protocol_version"] = item.pop("protocolVersion")
        out["supported_interfaces"] = interfaces
    caps = out.get("capabilities")
    if isinstance(caps, dict) and "pushNotifications" in caps:
        caps["push_notifications"] = caps.pop("pushNotifications")
    return out


def card_key(card: dict) -> tuple:
    org = (card.get("provider") or {}).get("organization", "")
    return card.get("name", ""), org


def load_json(path: Path, fallback):
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"FAIL: {path} 不是合法 JSON：{exc}")


def atomic_write(path: Path, payload, mode: int) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install MockAgent seed cards as registry init data")
    parser.add_argument("--seed-file", required=True, help="registry_seed/agentcard.json 路径")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="注册中心数据目录")
    parser.add_argument("--service", default=DEFAULT_SERVICE, help="注册中心 systemd 服务名")
    parser.add_argument("--restart", action="store_true", help="安装前停服务、安装后启动（推荐，避免 shutdown flush 覆盖）")
    parser.add_argument("--stop-first", action="store_true", help="仅先停服务并在安装后启动，等价 --restart")
    parser.add_argument("--dry-run", action="store_true", help="只打印将安装的卡片")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    cards_path = data_dir / "agentcard.json"
    meta_path = data_dir / "agentregistry.json"

    seed_cards = [card_to_registry_format(c)
                  for c in load_json(Path(args.seed_file), [])]
    if not seed_cards:
        sys.exit("FAIL: 种子文件为空")
    live_cards = load_json(cards_path, [])
    live_meta = load_json(meta_path, [])

    existing_keys = {card_key(c) for c in live_cards}
    new_cards = [c for c in seed_cards if card_key(c) not in existing_keys]
    skipped = len(seed_cards) - len(new_cards)
    print(f"种子 {len(seed_cards)} 张；已存在 {skipped} 张；将安装 {len(new_cards)} 张")
    for card in new_cards:
        name, org = card_key(card)
        print(f"  + {name} (org={org}, skills={len(card.get('skills') or [])})")

    if args.dry_run:
        print("dry-run：未修改任何文件")
        return

    # 关键顺序：必须先停服务再写文件。注册中心在 shutdown 时会把内存态
    # 全量写回 data/agentcard.json，运行中改文件会被 shutdown flush 覆盖。
    stopped = False
    if args.restart or args.stop_first:
        subprocess.run(["systemctl", "stop", args.service], check=True)
        stopped = True
        print(f"OK: 已停止 {args.service}（避免 shutdown flush 覆盖种子）")

    try:
        if new_cards:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            for path in (cards_path, meta_path):
                if path.is_file():
                    backup = path.with_suffix(path.suffix + f".pre-mockagent-{stamp}")
                    backup.write_bytes(path.read_bytes())
                    os.chmod(backup, 0o600)
                    print(f"  备份: {backup}")

            merged = live_cards + new_cards
            atomic_write(cards_path, merged, cards_path.stat().st_mode & 0o777 if cards_path.is_file() else 0o600)

            now = datetime.now(timezone.utc).isoformat()
            meta_keys = {(m.get("organization", ""), m.get("agent_name", "")) for m in live_meta}
            new_meta = []
            for card in new_cards:
                name, org = card_key(card)
                if (org, name) in meta_keys:
                    continue
                new_meta.append({
                    "organization": org,
                    "agent_name": name,
                    "status": "published",
                    "owner": None,
                    "tags": [],
                    "layer": "unknown",
                    "created_at": now,
                    "updated_at": now,
                    "status_history": [],
                })
            if new_meta:
                atomic_write(meta_path, live_meta + new_meta,
                             meta_path.stat().st_mode & 0o777 if meta_path.is_file() else 0o600)

            print(f"OK: agentcard.json {len(live_cards)} -> {len(merged)}；元数据 +{len(new_meta)}")
        else:
            print("没有新卡片需要安装")
    finally:
        if stopped:
            subprocess.run(["systemctl", "start", args.service], check=True)
            print(f"OK: 已启动 {args.service}")


if __name__ == "__main__":
    main()
