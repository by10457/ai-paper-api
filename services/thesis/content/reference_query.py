"""参考文献检索关键词的通用解析与清洗规则。"""

import json
import re
from typing import Any, cast

# 英文查询中的通用论文措辞不能单独构成可用检索主题。
_GENERIC_ENGLISH_QUERY_TERMS = {
    "analysis",
    "application",
    "approach",
    "design",
    "development",
    "effect",
    "efficacy",
    "framework",
    "implementation",
    "method",
    "paper",
    "platform",
    "research",
    "study",
    "system",
    "technology",
    "vs",
    "web",
}
# 常见开发框架只能作为技术限定词，不能在中文业务题目翻译失败时替代研究主题。
_TECHNOLOGY_ONLY_TERMS = {
    "angular",
    "boot",
    "django",
    "fastapi",
    "java",
    "javascript",
    "mysql",
    "nginx",
    "python",
    "react",
    "redis",
    "spring",
    "typescript",
    "vue",
}


# 从模型输出中提取 JSON 对象，兼容代码围栏和前后说明。
def parse_keyword_json(raw: object) -> dict[str, Any]:
    """解析参考文献关键词模型输出。

    Args:
        raw: 模型返回的原始对象。

    Returns:
        关键词 JSON 对象。

    Raises:
        ValueError: 响应中不存在合法 JSON 对象或顶层不是对象。
    """

    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw).strip(), flags=re.IGNORECASE)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("文献检索关键词响应不包含 JSON 对象")
    parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("文献检索关键词响应不是 JSON 对象")
    return cast(dict[str, Any], parsed)


# 合并字符串或字符串列表字段，并按输入顺序去重截断。
def collect_keyword_queries(
    keyword_data: dict[str, Any],
    fields: tuple[str, ...],
    *,
    limit: int,
    fallback: str = "",
) -> list[str]:
    """收集模型输出中的多组检索词。

    Args:
        keyword_data: 已解析的关键词对象。
        fields: 按优先级读取的字段名。
        limit: 最多保留的查询数量。
        fallback: 无有效查询时使用的兜底值；空值表示不兜底。

    Returns:
        去重后的检索查询列表。
    """

    candidates: list[str] = []
    for field in fields:
        value = keyword_data.get(field)
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, str))
    queries: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        query = re.sub(r"\s+", " ", candidate).strip()
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        queries.append(query)
        if len(queries) >= limit:
            break
    if not queries and fallback:
        fallback_query = re.sub(r"\s+", " ", fallback).strip()
        if fallback_query:
            queries.append(fallback_query)
    return queries


# 仅保留独立英文主题查询；中文题目翻译失败时宁可报告外文不足，也不使用技术栈冒充主题。
def normalize_english_queries(queries: list[str], *, title: str, limit: int) -> list[str]:
    """清洗英文文献查询词。

    Args:
        queries: 模型生成的英文查询。
        title: 论文题目，仅在其自身为英文时用于兜底。
        limit: 最多保留的查询数量。

    Returns:
        不包含中文、具有研究主题含义的英文查询列表。
    """

    candidates = [*queries]
    if not re.search(r"[\u4e00-\u9fff]", title):
        candidates.append(title)

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        query = re.sub(r"\s+", " ", candidate).strip()
        if not query or re.search(r"[\u4e00-\u9fff]", query):
            continue
        tokens = [token.casefold() for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]*", query)]
        subject_tokens = [
            token
            for token in tokens
            if token not in _GENERIC_ENGLISH_QUERY_TERMS and token not in _TECHNOLOGY_ONLY_TERMS
        ]
        if len(subject_tokens) < 2:
            continue
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(query)
        if len(normalized) >= limit:
            break
    return normalized


__all__ = ["collect_keyword_queries", "normalize_english_queries", "parse_keyword_json"]
