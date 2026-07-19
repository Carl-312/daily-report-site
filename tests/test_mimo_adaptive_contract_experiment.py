from __future__ import annotations

import json

from scripts.mimo_adaptive_contract_experiment import (
    evaluate_adaptive_gate,
    evaluate_atomic_gate,
)


VALID_SUMMARIES = [
    "小米发布新一代人工智能模型，重点提升工具调用能力并降低企业部署成本。",
    "OpenAI推出企业智能代理平台，帮助开发团队统一管理模型调用与权限审计。",
    "谷歌开放多模态模型新接口，支持开发者同时处理长文本、图像与音频内容。",
    "Anthropic更新代码助手功能，可在大型软件仓库中执行跨文件分析和修改。",
    "Meta公布开源模型训练方案，计划降低研究机构开展多语言实验的资源门槛。",
    "英伟达发布推理加速组件，为数据中心部署生成式人工智能服务减少延迟。",
    "微软扩展云端人工智能工具链，为企业应用增加评测、监控与安全控制能力。",
    "苹果测试端侧智能功能，让部分文本处理任务无需连接云端即可完成。",
    "亚马逊上线新型模型托管服务，允许团队按业务负载自动调整推理资源规模。",
    "字节跳动升级视频生成模型，改善复杂镜头中的人物一致性和运动表现。",
    "阿里云推出轻量化语言模型，面向客服和办公场景降低实时推理成本。",
    "腾讯开源智能搜索组件，支持开发者结合私有知识库构建问答应用。",
]
SHORT = "小米发布新一代人工智能模型。"


def _content(summaries: list[str]) -> str:
    return json.dumps(
        {
            "items": [
                {"article_id": f"a{index}", "summary": summary}
                for index, summary in enumerate(summaries, 1)
            ],
            "discussion_topic": "你最关注哪项人工智能进展？",
        },
        ensure_ascii=False,
    )


def test_adaptive_gate_recovers_seven_valid_items_from_one_short_item() -> None:
    content = _content(VALID_SUMMARIES[:7] + [SHORT])
    article_ids = {f"a{index}" for index in range(1, 15)}

    atomic = evaluate_atomic_gate(
        content, article_ids=article_ids, max_items=10
    )
    adaptive = evaluate_adaptive_gate(
        content,
        article_ids=article_ids,
        source_count=14,
        max_items=10,
    )

    assert atomic.status == "failed"
    assert adaptive.status == "publishable"
    assert adaptive.accepted_items == 7
    assert adaptive.quarantined_items == 1
    assert "quality_length:item=8" in adaptive.diagnostics[0]


def test_adaptive_gate_still_fails_below_large_input_coverage_threshold() -> None:
    content = _content(VALID_SUMMARIES[:6] + [SHORT, SHORT])
    result = evaluate_adaptive_gate(
        content,
        article_ids={f"a{index}" for index in range(1, 15)},
        source_count=14,
        max_items=10,
    )

    assert result.status == "failed"
    assert result.accepted_items == 6
    assert any("quality_item_coverage" in item for item in result.diagnostics)


def test_adaptive_gate_caps_excess_items_without_weakening_item_quality() -> None:
    content = _content(VALID_SUMMARIES)
    result = evaluate_adaptive_gate(
        content,
        article_ids={f"a{index}" for index in range(1, 15)},
        source_count=14,
        max_items=10,
    )

    assert result.status == "publishable"
    assert result.received_items == 12
    assert result.accepted_items == 10
    assert result.capped_items == 2
    assert "items_capped:count=2" in result.diagnostics


def test_adaptive_gate_keeps_unknown_source_as_a_batch_failure() -> None:
    payload = json.loads(_content(VALID_SUMMARIES[:7]))
    payload["items"][0]["article_id"] = "a999"
    result = evaluate_adaptive_gate(
        json.dumps(payload, ensure_ascii=False),
        article_ids={f"a{index}" for index in range(1, 15)},
        source_count=14,
        max_items=10,
    )

    assert result.status == "failed"
    assert result.accepted_items == 0
    assert result.diagnostics == ("unknown_article_id:item=1",)


def test_adaptive_gate_keeps_public_link_as_a_batch_failure() -> None:
    summaries = VALID_SUMMARIES[:7].copy()
    summaries[0] = "小米发布新一代人工智能模型，详情可访问https://example.test查看完整说明。"
    result = evaluate_adaptive_gate(
        _content(summaries),
        article_ids={f"a{index}" for index in range(1, 15)},
        source_count=14,
        max_items=10,
    )

    assert result.status == "failed"
    assert result.accepted_items == 0
    assert result.diagnostics == ("quality_public_safety:item=1",)
