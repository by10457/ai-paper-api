"""论文大纲密度与事实边界测试。"""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from langchain_core.prompts import PromptTemplate
from langchain_core.prompts.chat import SystemMessagePromptTemplate

from llm.prompts.thesis_outline_prompt import THESIS_OUTLINE_PROMPT
from services.thesis.content import outline_service


class _FakeOutlineChain:
    def __init__(self, responses: Iterator[str]) -> None:
        self.responses = responses
        self.inputs: list[dict[str, Any]] = []

    async def ainvoke(self, inputs: dict[str, Any]) -> str:
        self.inputs.append(inputs)
        return next(self.responses)


def _dense_outline() -> str:
    """构造七章、每章三节、每节两个三级小节的大纲。"""

    return json.dumps(
        {
            "outline": [
                {
                    "chapter": f"第{chapter}章 章节标题{chapter}",
                    "sections": [
                        {
                            "name": f"{chapter}.{section} 二级标题",
                            "abstract": "写作要点",
                            "subsections": [
                                {"name": f"三级标题{subsection}", "abstract": "三级要点"}
                                for subsection in range(1, 3)
                            ],
                        }
                        for section in range(1, 4)
                    ],
                }
                for chapter in range(1, 8)
            ],
            "abstract": "摘要",
            "keywords": "关键词",
        },
        ensure_ascii=False,
    )


def test_short_paper_outline_density_is_bounded() -> None:
    """3000 字三级大纲不能产生足以挤占正文的数十个受保护标题。"""

    payload = outline_service._parse_and_validate_outline(
        _dense_outline(),
        target_word_count=3000,
    )
    sections = [section for chapter in payload["outline"] for section in chapter["sections"]]

    assert len(sections) == 12
    assert sum(len(section["subsections"]) for section in sections) == 12


def test_outline_prompt_respects_user_fact_boundaries() -> None:
    """大纲和摘要阶段也必须禁止把缺失的实现与实测信息写成事实。"""

    system_message = THESIS_OUTLINE_PROMPT.messages[0]
    assert isinstance(system_message, SystemMessagePromptTemplate)
    assert isinstance(system_message.prompt, PromptTemplate)
    system_prompt = str(system_message.prompt.template)

    assert "不得在摘要或大纲中写成已经完成" in system_prompt
    assert "不得擅自添加用户没有确认的框架" in system_prompt


def test_outline_abstract_sanitizes_unconfirmed_implementation_facts() -> None:
    """大纲摘要不能把模型擅自补充的数据库和实现状态作为既成事实。"""

    raw = json.dumps(
        {
            "outline": [
                {"chapter": "绪论", "sections": [{"name": "背景", "abstract": "简述MyBatis数据访问实现"}]}
            ],
            "abstract": "本文设计并实现了一个平台，系统采用前后端分离架构，后端使用Spring Boot，数据库选用MySQL数据库，并对系统进行了测试。",
            "keywords": "平台",
        },
        ensure_ascii=False,
    )

    payload = outline_service._parse_and_validate_outline(
        raw,
        target_word_count=3000,
        title="基于Spring Boot与Vue的平台设计",
        aboutmsg="未提供真实实现材料",
    )

    assert "设计并实现" not in payload["abstract"]
    assert "系统采用" not in payload["abstract"]
    assert "后端使用" not in payload["abstract"]
    assert "进行了测试" not in payload["abstract"]
    assert "待确认" in payload["abstract"]
    assert "MyBatis" not in payload["outline"][0]["sections"][0]["abstract"]
    assert "用户未提供系统源码" not in payload["outline"][0]["sections"][0]["abstract"]


async def test_two_level_outline_is_accepted_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模型选择两级结构时应直接交付，不强制重试补齐三级。"""

    no_subsections = json.loads(_dense_outline())
    for chapter in no_subsections["outline"]:
        for section in chapter["sections"]:
            section["subsections"] = []
    chain = _FakeOutlineChain(iter([json.dumps(no_subsections, ensure_ascii=False), _dense_outline()]))

    async def fake_build_chain() -> _FakeOutlineChain:
        return chain

    monkeypatch.setattr(outline_service, "_build_outline_chain", fake_build_chain)

    payload = await outline_service.generate_outline("测试论文题目", target_word_count=3000)

    assert len(chain.inputs) == 1
    assert sum(
        len(section["subsections"])
        for chapter in payload["outline"]
        for section in chapter["sections"]
    ) == 0

# 自动层级应保留有意义的混合结构，而不是把所有二级节统一升降级
@pytest.mark.parametrize("word_count", [3000, 8000, 20000, 30000])
def test_auto_outline_preserves_mixed_levels(word_count: int) -> None:
    """验证 word_count 不决定强制层级，模型返回的局部三级可正常保留。"""
    raw = json.dumps({
        "outline": [{
            "chapter": "研究设计",
            "sections": [
                {"name": "研究背景", "abstract": "背景", "subsections": []},
                {"name": "研究方法", "abstract": "方法", "subsections": [
                    {"name": "资料收集", "abstract": "收集方法"},
                    {"name": "分析方法", "abstract": "分析思路"},
                ]},
            ],
        }],
    }, ensure_ascii=False)
    payload = outline_service._parse_and_validate_outline(raw, target_word_count=word_count)
    sections = payload["outline"][0]["sections"]
    assert sections[0]["subsections"] == []
    assert [item["name"] for item in sections[1]["subsections"]] == ["资料收集", "分析方法"]


# 提示词需完整格式化，不能残留旧开关变量
def test_auto_outline_prompt_formats_without_level_switch() -> None:
    """验证模型收到两级优先与局部三级规则，不依赖接口布尔参数。"""
    messages = THESIS_OUTLINE_PROMPT.format_messages(
        title="跨学科研究", target_word_count=8000,
        **outline_service._build_outline_instructions(10, 2, ""),
    )
    text = "\n".join(str(item.content) for item in messages)
    assert "默认采用章、节两级结构" in text
    assert "允许同一大纲混合" in text
    assert "three_level" not in text
