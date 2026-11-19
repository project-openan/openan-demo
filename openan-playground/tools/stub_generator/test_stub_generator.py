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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from cli import build_messages, parse_variants, run_generation


class FakeCompletion:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class FakeClient:
    def __init__(self, content):
        self.chat = type("C", (), {"completions": type("X", (), {"create": lambda self, **kw: FakeCompletion(content)})()})()


def test_parse_variants_handles_fences():
    content = '```json\n[{"a": 1}, {"a": 2}]\n```'
    assert parse_variants(content) == [{"a": 1}, {"a": 2}]


def test_parse_variants_rejects_non_array():
    import pytest

    with pytest.raises(ValueError):
        parse_variants('{"a": 1}')


def test_build_messages_contains_seed_and_count():
    messages = build_messages({"faultManagement.Incident": {"csn": "INC-1"}}, "Task-T/x/v1", 5)
    text = json.dumps(messages, ensure_ascii=False)
    assert "INC-1" in text and "5" in text and "Task-T/x/v1" in text


def test_run_generation_writes_output(tmp_path):
    payload = [{"faultManagement.Incident": {"csn": "INC-2"}}]
    client = FakeClient(json.dumps(payload, ensure_ascii=False))
    out = tmp_path / "out.json"
    result = run_generation(client, "gpt-x", {"faultManagement.Incident": {"csn": "INC-1"}}, "Task-T/x/v1", 1, out)
    assert result["templateUri"] == "Task-T/x/v1"
    assert result["variants"] == payload
    assert json.loads(out.read_text(encoding="utf-8")) == result
