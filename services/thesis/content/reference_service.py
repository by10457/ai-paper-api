"""参考文献生成统一入口。"""

import logging
import re

from core.config import get_settings
from services.thesis.content import reference_service_serpapi, reference_service_wfapi

logger = logging.getLogger(__name__)

REFERENCE_MODE_SERPAPI = "serpapi"
REFERENCE_MODE_WFAPI = "wfapi"
REFERENCE_MODE_MIXED = "mixed"

_REFERENCE_INDEX_RE = re.compile(r"^\[\d+\]")


def _split_reference_lines(references: str) -> list[str]:
    return [line.strip() for line in references.splitlines() if line.strip()]


def _renumber_reference_lines(lines: list[str]) -> str:
    renumbered: list[str] = []
    for index, line in enumerate(lines, start=1):
        body = _REFERENCE_INDEX_RE.sub("", line).strip()
        renumbered.append(f"[{index}]{body}")
    return "\n".join(renumbered)


async def _generate_mixed_references(title: str, outline: str, wxnum: int, include_english: bool) -> str:
    if not include_english:
        return await reference_service_wfapi.generate_references(title, outline, wxnum=wxnum, include_english=False)

    target_total = max(1, wxnum)
    target_en = max(3, round(target_total / 3))
    target_zh = max(1, target_total - target_en)

    zh_references = await reference_service_wfapi.generate_references(
        title,
        outline,
        wxnum=target_zh,
        include_english=False,
    )
    en_references = await reference_service_serpapi.generate_references(
        title,
        outline,
        wxnum=target_en,
        include_english=True,
        include_chinese=False,
    )

    lines = _split_reference_lines(zh_references) + _split_reference_lines(en_references)
    return _renumber_reference_lines(lines[:target_total])


async def generate_references(
    title: str,
    outline: str,
    wxnum: int = 25,
    include_english: bool = True,
) -> str:
    """按配置选择参考文献来源并生成编号列表。"""

    mode = get_settings().reference_provider_mode.strip().lower()
    if mode == REFERENCE_MODE_WFAPI:
        return await reference_service_wfapi.generate_references(
            title,
            outline,
            wxnum=wxnum,
            include_english=include_english,
        )
    if mode == REFERENCE_MODE_SERPAPI:
        return await reference_service_serpapi.generate_references(
            title,
            outline,
            wxnum=wxnum,
            include_english=include_english,
        )
    if mode == REFERENCE_MODE_MIXED:
        return await _generate_mixed_references(title, outline, wxnum, include_english)

    logger.warning("未知参考文献生成模式 %r，已使用默认万方模式", mode)
    return await reference_service_wfapi.generate_references(
        title,
        outline,
        wxnum=wxnum,
        include_english=include_english,
    )
