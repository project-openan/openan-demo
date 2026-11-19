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
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_admin
from ..db import SERVICE_URL_DEFAULTS
from ..deps import get_db
from ..models import ServiceSettings
from ..schemas import ServiceUrlsUpdate

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

FIELD_TO_KEY = {
    "registryUrl": "registry_url",
    "orchestrationUrl": "orchestration_url",
    "executionHostUrl": "execution_host_url",
    "ontologyUrl": "ontology_url",
}


def _get_url(session: Session, key: str, default: str) -> str:
    row = session.scalar(select(ServiceSettings).where(ServiceSettings.key == key))
    return row.value if row is not None else default


def _service_urls_view(session: Session) -> dict:
    return {field: _get_url(session, key, SERVICE_URL_DEFAULTS[key]) for field, key in FIELD_TO_KEY.items()}


@router.get("/service-urls")
def get_service_urls(db: Session = Depends(get_db), _: dict = Depends(get_current_user)):
    return _service_urls_view(db)


@router.put("/service-urls")
def put_service_urls(
    body: ServiceUrlsUpdate,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
):
    for field, value in body.model_dump().items():
        if value is None:
            continue
        key = FIELD_TO_KEY[field]
        row = db.scalar(select(ServiceSettings).where(ServiceSettings.key == key))
        if row is None:
            db.add(ServiceSettings(key=key, value=value))
        else:
            row.value = value
    db.commit()
    return _service_urls_view(db)
