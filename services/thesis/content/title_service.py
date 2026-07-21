"""根据用户研究描述生成论文题目候选。"""

import json
import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable
from pydantic import ValidationError

from llm.client import create_configured_llm
from llm.prompts.thesis_title_prompt import THESIS_TITLE_RECOMMENDATION_PROMPT
from schemas.thesis import TitleRecommendationPayload
from services.thesis.generation.concurrency import text_short_slot

# 题目推荐接口固定返回的候选数量。
TITLE_RECOMMENDATION_COUNT = 20


# 构建复用大纲模型配置的题目推荐调用链。
async def _build_title_recommendation_chain() -> Runnable[dict[str, str], str]:
    """构建题目推荐调用链。

    Returns:
        使用短文本模型的 LangChain 调用链。
    """

    llm = await create_configured_llm(
        "outline",
        temperature=0.7,
        max_tokens=1536,
    )
    return THESIS_TITLE_RECOMMENDATION_PROMPT | llm | StrOutputParser()


# 清理部分模型可能额外包裹的 JSON 代码块。
def _strip_json_fence(text: str) -> str:
    """移除模型响应外层的 JSON 代码块。

    Args:
        text: 模型原始文本。

    Returns:
        可交给 JSON 解析器处理的文本。
    """

    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s*```$", "", cleaned).strip()


# 校验模型必须返回恰好二十个互不重复的题目。
def _parse_title_recommendations(raw: str) -> list[str]:
    """解析并校验模型返回的题目列表。

    Args:
        raw: 模型返回的 JSON 文本。

    Returns:
        二十个规范化后的论文题目。

    Raises:
        RuntimeError: 模型响应不是合法 JSON、数量不正确或包含重复题目。
    """

    cleaned = _strip_json_fence(raw)
    parsed: object | None = None

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # 部分模型会在 JSON 前后附加说明，从首个对象或数组标记处提取完整载荷。
        decoder = json.JSONDecoder()
        for match in re.finditer(r"[\[{]", cleaned):
            try:
                parsed, _ = decoder.raw_decode(cleaned[match.start() :])
                break
            except json.JSONDecodeError:
                continue

    # 个别模型会忽略 JSON 要求，降级兼容二十项编号列表。
    if parsed is None:
        numbered_titles = []
        for line in cleaned.splitlines():
            numbered_match = re.match(r"^\s*\d{1,2}[.、．)]\s*(.+?)\s*$", line)
            if numbered_match:
                numbered_titles.append(numbered_match.group(1))
        if numbered_titles:
            parsed = numbered_titles

    if isinstance(parsed, list):
        parsed = {"titles": parsed}

    try:
        payload = TitleRecommendationPayload.model_validate(parsed)
    except ValidationError as exc:
        raise RuntimeError("模型返回的论文题目格式无效，请重试") from exc

    if len(set(payload.titles)) != TITLE_RECOMMENDATION_COUNT:
        raise RuntimeError("模型返回的论文题目存在重复，请重试")
    return payload.titles


# 调用短文本模型生成论文题目推荐结果。
async def generate_recommended_titles(content: str) -> list[str]:
    """根据用户描述生成二十个论文题目。

    Args:
        content: 用户提供的研究方向或需求描述。

    Returns:
        二十个互不重复的论文题目。

    Raises:
        RuntimeError: 模型服务调用失败或返回结果不符合接口契约。
    """

    try:
        chain = await _build_title_recommendation_chain()
        async with text_short_slot():
            raw = await chain.ainvoke({"content": content})
    except Exception as exc:  # 外部模型可能抛出多种 SDK 异常，统一转换为稳定业务错误。
        raise RuntimeError("论文题目推荐服务调用失败，请稍后重试") from exc
    return _parse_title_recommendations(raw)
