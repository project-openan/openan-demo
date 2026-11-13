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
import os
from dataclasses import dataclass, field
from pathlib import Path
from secrets import token_urlsafe

from dotenv import dotenv_values


@dataclass(slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 9000
    db_path: Path = Path("data/mockagent.db")
    jwt_secret: str = field(default_factory=lambda: token_urlsafe(32), repr=False)
    jwt_expire_minutes: int = 720
    admin_password: str | None = None
    public_agent_url: str = "http://127.0.0.1:9000/debug/a2a"
    agent_internal_url: str = "http://127.0.0.1:9000/debug/a2a/message:send"
    stub_fallback: bool = True
    dataset_search: bool = True
    language: str = "zh-CN"
    env_path: Path = Path(".env")

    def __post_init__(self) -> None:
        validate_jwt_secret(self.jwt_secret)


def validate_jwt_secret(secret: str) -> None:
    if len(secret.strip().encode("utf-8")) < 32:
        raise ValueError("MOCK_AGENT_JWT_SECRET must contain at least 32 bytes")


def load_settings(env_path: Path | None = None) -> Settings:
    env_path = env_path or Path(os.environ.get("MOCK_AGENT_ENV", ".env"))
    file_values = dotenv_values(env_path) if env_path.exists() else {}

    def resolve(key: str, default: str) -> str:
        return os.environ.get(key) or file_values.get(key) or default

    stub_raw = resolve("MOCK_AGENT_STUB_FALLBACK", "on")
    ds_raw = resolve("MOCK_AGENT_DATASET_SEARCH", "on")
    return Settings(
        host=resolve("MOCK_AGENT_HOST", "127.0.0.1"),
        port=int(resolve("MOCK_AGENT_PORT", "9000")),
        db_path=Path(resolve("MOCK_AGENT_DB_PATH", "data/mockagent.db")),
        jwt_secret=resolve("MOCK_AGENT_JWT_SECRET", "") or token_urlsafe(32),
        jwt_expire_minutes=int(resolve("MOCK_AGENT_JWT_EXPIRE_MINUTES", "720")),
        admin_password=resolve("MOCK_AGENT_ADMIN_PASSWORD", "") or None,
        public_agent_url=resolve("MOCK_AGENT_PUBLIC_URL", "http://127.0.0.1:9000/debug/a2a"),
        agent_internal_url=resolve(
            "MOCK_AGENT_AGENT_INTERNAL_URL", "http://127.0.0.1:9000/debug/a2a/message:send"
        ),
        stub_fallback=stub_raw.strip().lower() in {"", "on", "1", "true", "yes"},
        dataset_search=ds_raw.strip().lower() in {"", "on", "1", "true", "yes"},
        language=resolve("A2AT_LANGUAGE", "zh-CN"),
        env_path=env_path,
    )
