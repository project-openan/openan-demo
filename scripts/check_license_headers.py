# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Verify that every source file carries the Apache-2.0 license header.

Mirrors the header convention used by the sibling repositories
(registry-center / orchestration-center):

    Copyright (c) 2026 Huawei Technologies Co., Ltd.
    All Rights Reserved.
    SPDX-License-Identifier: Apache-2.0

Usage:
    python scripts/check_license_headers.py            # repo root auto-detected
    python scripts/check_license_headers.py --root .   # explicit root
    python scripts/check_license_headers.py --fix      # insert missing headers

Exit code 0 when every scanned file carries a header, 1 otherwise.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

EXTS = {".py", ".js", ".jsx", ".mjs", ".css", ".sh"}
SKIP_DIRS = {
    "node_modules", ".git", "dist", "dist-plugin", "build", "__pycache__",
    ".venv", "venv", "reviews", "coverage", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "htmlcov", ".idea", ".vscode",
}

COPYRIGHT = "Copyright (c) 2026 Huawei Technologies Co., Ltd."
BODY = [
    "All Rights Reserved.",
    "",
    "SPDX-License-Identifier: Apache-2.0",
    "",
    "   Licensed under the Apache License, Version 2.0 (the \"License\"); you may",
    "   not use this file except in compliance with the License. You may obtain",
    "   a copy of the License at",
    "",
    "        http://www.apache.org/licenses/LICENSE-2.0",
    "",
    "   Unless required by applicable law or agreed to in writing, software",
    "   distributed under the License is distributed on an \"AS IS\" BASIS, WITHOUT",
    "   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the",
    "   License for the specific language governing permissions and limitations",
    "   under the License.",
]

CODING_RE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")


def build_header(ext: str, eol: str) -> str:
    lines = [COPYRIGHT, *BODY]
    if ext == ".css":
        out = ["/*"] + [f" * {line}".rstrip() for line in lines] + [" */"]
    else:
        prefix = "#" if ext in {".py", ".sh"} else "//"
        out = [f"{prefix} {line}".rstrip() if line else prefix for line in lines]
    return eol.join(out) + eol + eol


def has_header(text: str) -> bool:
    return any(
        "Copyright (c)" in line or "SPDX-License-Identifier" in line
        for line in text.splitlines()[:30]
    )


def insert_index(lines: list[str], ext: str) -> int:
    idx = 0
    if lines and lines[0].startswith("#!"):
        idx = 1
    if ext == ".py":
        for probe in range(idx, min(idx + 2, len(lines))):
            if CODING_RE.match(lines[probe]):
                idx = probe + 1
                break
    return idx


def iter_sources(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix.lower() in EXTS:
                yield path


def add_header(path: Path) -> bool:
    """Return True when a header was written, False when the file was skipped."""
    raw = path.read_bytes()
    if not raw.strip():
        # Empty package markers (``__init__.py``) still get the header so that a
        # single rule covers the whole tree.
        path.write_bytes(build_header(path.suffix.lower(), "\n").encode("utf-8"))
        return True
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    if has_header(text):
        return False

    eol = "\r\n" if text.count("\r\n") > text.count("\n") / 2 else "\n"
    lines = text.replace("\r\n", "\n").split("\n")
    idx = insert_index(lines, path.suffix.lower())
    head = "\n".join(lines[:idx])
    if idx:
        head += "\n"
    new_text = head + build_header(path.suffix.lower(), "\n").rstrip("\n")
    new_text += "\n\n" + "\n".join(lines[idx:]) if idx else "\n" + "\n".join(lines[idx:])
    if eol == "\r\n":
        new_text = new_text.replace("\n", "\r\n")
    data = new_text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    path.write_bytes(data)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--fix", action="store_true", help="insert the header when missing")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    missing: list[str] = []
    fixed = 0
    for path in iter_sources(root):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (UnicodeDecodeError, OSError):
            continue
        if has_header(text):
            continue
        if args.fix and add_header(path):
            fixed += 1
            continue
        missing.append(str(path.relative_to(root)))

    if args.fix:
        print(f"  headers added: {fixed}")
    if missing:
        print(f"  {len(missing)} file(s) missing the Apache-2.0 header:")
        for rel in missing[:40]:
            print(f"    {rel}")
        if len(missing) > 40:
            print(f"    ... and {len(missing) - 40} more")
        return 1
    print("  all scanned source files carry the Apache-2.0 header")
    return 0


if __name__ == "__main__":
    sys.exit(main())
