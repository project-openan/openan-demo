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
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from starlette.applications import Starlette

from .agent_card import build_agent_card
from .executor import MockAgentExecutor


class EchoExtensionsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        extension_values = [value for key, value in scope["headers"] if key == b"a2a-extensions"]
        extension_header = b", ".join(extension_values)

        async def send_wrapper(message):
            if message["type"] == "http.response.start" and extension_header:
                response_headers = message.setdefault("headers", [])
                if all(key != b"a2a-extensions" for key, _ in response_headers):
                    response_headers.append((b"a2a-extensions", extension_header))
            await send(message)

        await self.app(scope, receive, send_wrapper)


def build_a2a_app(
    public_url: str,
    executor: MockAgentExecutor,
    *,
    agent_name: str | None = None,
    agent_description: str | None = None,
    skills: list | None = None,
):
    agent_card = build_agent_card(
        public_url, name=agent_name, description=agent_description, skills=skills
    )
    handler = DefaultRequestHandler(
        agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=agent_card
    )
    routes = [*create_agent_card_routes(agent_card), *create_rest_routes(handler)]
    return EchoExtensionsMiddleware(Starlette(routes=routes))
