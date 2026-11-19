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
import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends

from ..auth import get_current_user

router = APIRouter(prefix="/api/v1/registry", tags=["registry"])

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "data" / "registry_samples"


@lru_cache(maxsize=1)
def load_samples() -> list[dict]:
    samples = []
    for path in sorted(SAMPLES_DIR.glob("*.json")):
        samples.append(json.loads(path.read_text(encoding="utf-8")))
    return sorted(samples, key=lambda item: item.get("key", ""))


@router.get("/samples")
def list_samples(_: dict = Depends(get_current_user)):
    return load_samples()
