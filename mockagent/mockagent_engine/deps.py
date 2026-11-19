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
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from .config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_agent_id(request: Request) -> int:
    agent_id = request.app.state.runtime["agent_id"]
    if agent_id is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return agent_id


def get_db(request: Request):
    engine = request.app.state.engine
    with Session(engine) as session:
        yield session
