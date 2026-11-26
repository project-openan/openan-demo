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

from openan_debug import dataset_retrieval


# --------------------------------------------------------------------------- #
# dataset_retrieval — TC-DS
# --------------------------------------------------------------------------- #
def test_ds_dice_zero_on_empty():
    """TC-DS-001 | _dice 任一集合为空时返回 0.0

    输入: a=set()/b={('a','b')}；a={('a','b')}/b=set()；两者相同
    预期输出: 0.0 / 0.0 / 1.0
    断言点: 返回值
    防回归: 若空集守卫删除，除零或错误比例
    """
    assert dataset_retrieval._dice(set(), {("a", "b")}) == 0.0
    assert dataset_retrieval._dice({("a", "b")}, set()) == 0.0
    assert dataset_retrieval._dice({("a", "b")}, {("a", "b")}) == 1.0


def test_ds_bigrams_filters_non_alnum():
    """TC-DS-002 | _bigrams 仅保留字母数字与中文相邻对

    输入: 'a b' / '任务' / ''
    预期输出: {('a','b')} / {('任','务')} / set()
    断言点: 集合内容
    防回归: 若过滤逻辑改坏，集合变化
    """
    assert dataset_retrieval._bigrams("a b") == {("a", "b")}
    assert dataset_retrieval._bigrams("任务") == {("任", "务")}
    assert dataset_retrieval._bigrams("") == set()


def test_ds_extract_ids_finds_patterns():
    """TC-DS-003 | _extract_ids 抽取工单号与时间标识

    输入: 含 CMCC-GZ-TSCLX-20260924-004403 与 2026-09-22T15:25:50 的文本
    预期输出: {'ticket':[...], 'isotime':[...]}
    断言点: 类型键与值
    防回归: 若正则改坏，漏抽标识
    """
    ids = dataset_retrieval._extract_ids("工单 CMCC-GZ-TSCLX-20260924-004403 发生于 2026-09-22T15:25:50")
    assert ids["ticket"] == ["CMCC-GZ-TSCLX-20260924-004403"]
    assert ids["isotime"] == ["2026-09-22T15:25:50"]


def test_ds_search_none_on_empty_inputs():
    """TC-DS-004 | search 对空 templateUri 或空 prompt 返回 None

    输入: (None,'x') 与 ('Task-T/x','')
    预期输出: None
    断言点: 提前返回 None
    防回归: 若守卫删除，进入索引扫描
    """
    assert dataset_retrieval.search(None, "x") is None
    assert dataset_retrieval.search("Task-T/x", "") is None


def test_ds_search_exact_match_returns_result():
    """TC-DS-005 | search 对与数据集请求完全一致的 prompt 命中并返回满分结果

    输入: templateUri='Task-T/private-line-complaint/v1'，prompt=该模板首条数据请求全文
    预期输出: meta.score==1.0，responseText 含 '诊断结果'
    断言点: 分数 + 响应文本关键字
    防回归: 若 id 覆盖率或 bigram 计算改坏，分数<1.0
    """
    template = "Task-T/private-line-complaint/v1"
    prompt = dataset_retrieval.sample_request(template)
    result = dataset_retrieval.search(template, prompt)
    assert result is not None
    assert result["meta"]["score"] == 1.0
    assert "诊断结果" in result["responseText"]


def test_ds_search_none_when_template_absent():
    """TC-DS-006 | search 对数据集中不存在的模板返回 None（无候选）

    输入: templateUri='Unknown-T/foo/bar/v1'
    预期输出: None
    断言点: scored 为空 → None
    防回归: 若模板过滤删除，可能误匹配
    """
    assert dataset_retrieval.search("Unknown-T/foo/bar/v1", "任务类型") is None


def test_ds_search_none_below_threshold():
    """TC-DS-007 | search 命中候选但相似度低于阈值时返回 None

    输入: 真实模板 + 仅极小 bigram 重叠的 prompt（'任务类型'）
    预期输出: None（best_score < _MIN_SCORE）
    断言点: 返回 None
    防回归: 若阈值判定删除，返回低分误匹配
    """
    assert dataset_retrieval.search("Task-T/private-line-complaint/v1", "任务类型") is None


def test_ds_sample_response_branches():
    """TC-DS-008 | sample_response 对 None/未知模板返回 None，对存在模板返回响应文本

    输入: None / 未知模板 / 'Task-T/private-line-complaint/v1'
    预期输出: None / None / 含 '诊断结果' 的文本
    断言点: None 与非空文本
    防回归: 若首条返回改坏，返回错误文本
    """
    assert dataset_retrieval.sample_response(None) is None
    assert dataset_retrieval.sample_response("Unknown-T/x/y/v1") is None
    resp = dataset_retrieval.sample_response("Task-T/private-line-complaint/v1")
    assert resp is not None
    assert "诊断结果" in resp


def test_ds_sample_request_branches():
    """TC-DS-009 | sample_request 对 None/未知模板返回 None，对存在模板返回请求文本

    输入: None / 未知模板 / 'Task-T/private-line-complaint/v1'
    预期输出: None / None / 含 '任务类型' 的文本
    断言点: None 与非空文本
    防回归: 若首条返回改坏，返回错误文本
    """
    assert dataset_retrieval.sample_request(None) is None
    assert dataset_retrieval.sample_request("Unknown-T/x/y/v1") is None
    req = dataset_retrieval.sample_request("Task-T/private-line-complaint/v1")
    assert req is not None
    assert "任务类型" in req


def test_ds_adapt_returns_unchanged_on_empty():
    """TC-DS-010 | adapt 在响应或请求为空时原样返回响应

    输入: adapt('', 'x') 与 adapt('resp', '')
    预期输出: '' 与 'resp'
    断言点: 返回值
    防回归: 若守卫删除，空串会触发标识提取异常
    """
    assert dataset_retrieval.adapt("", "x") == ""
    assert dataset_retrieval.adapt("resp", "") == "resp"


def test_ds_adapt_replaces_matching_ids():
    """TC-DS-011 | adapt 用请求标识替换响应中同类型标识

    输入: 响应含旧 ticket/isotime，请求含新 ticket/isotime
    预期输出: 旧标识被替换为新标识
    断言点: 旧标识不存在 + 新标识存在
    防回归: 若替换逻辑改坏，标识未替换
    """
    resp = "old CMCC-AB-TSCLX-19990101-000001 at 1999-01-01T00:00:00"
    req = "new CMCC-GZ-TSCLX-20260924-004403 at 2026-09-22T15:25:50"
    out = dataset_retrieval.adapt(resp, req)
    assert "CMCC-AB-TSCLX-19990101-000001" not in out
    assert "CMCC-GZ-TSCLX-20260924-004403" in out
    assert "1999-01-01T00:00:00" not in out
    assert "2026-09-22T15:25:50" in out


def test_ds_adapt_reuses_last_request_value_when_request_shorter():
    """TC-DS-012 | adapt 响应标识多于请求时复用请求最后一个值

    输入: 响应含 2 个 isotime，请求含 1 个 isotime
    预期输出: 两个旧 isotime 均被替换为请求值（出现 2 次）
    断言点: 旧值不存在 + 新值出现 2 次
    防回归: 若越界回退改坏，第二个旧值未替换或抛错
    """
    resp = "times 1999-01-01T00:00:00 and 1999-01-02T00:00:00"
    req = "at 2026-09-22T15:25:50"
    out = dataset_retrieval.adapt(resp, req)
    assert "1999-01-01T00:00:00" not in out
    assert "1999-01-02T00:00:00" not in out
    assert out.count("2026-09-22T15:25:50") == 2


def test_ds_adapt_skips_id_type_absent_in_response():
    """TC-DS-014 | adapt 对响应中不存在的标识类型直接跳过（continue）

    输入: 请求含 ticket+isotime，响应仅含 isotime（无 ticket）
    预期输出: isotime 被替换，ticket 类型因 resp_values 空而 continue
    断言点: isotime 替换成功 + 不抛错
    防回归: 若 continue 删除，resp_values 空时 enumerate 越界或空操作出错
    """
    resp = "at 1999-01-01T00:00:00"
    req = "ticket CMCC-GZ-TSCLX-20260924-004403 at 2026-09-22T15:25:50"
    out = dataset_retrieval.adapt(resp, req)
    assert "1999-01-01T00:00:00" not in out
    assert "2026-09-22T15:25:50" in out


def test_ds_load_handles_read_errors(monkeypatch):
    """TC-DS-013 | _load 在数据集文件读取失败时返回空列表且不抛异常

    输入: _INDEX=None 且 importlib_resources.files 抛 OSError
    预期输出: _load() 返回 []
    断言点: 返回空列表
    防回归: 若 except 删除，OSError 向上抛
    """
    monkeypatch.setattr(dataset_retrieval, "_INDEX", None)

    def boom(*a, **kw):
        raise OSError("unreadable")

    monkeypatch.setattr(dataset_retrieval.importlib_resources, "files", boom)
    assert dataset_retrieval._load() == []
