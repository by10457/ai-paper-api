"""论文生成主流水线，串联参考文献、正文、摘要、图片渲染和 Word 构建。"""

import asyncio
import logging
import re
from collections.abc import Awaitable
from dataclasses import dataclass, field
from pathlib import Path

from llm.client import create_configured_llm, get_enabled_model_config
from llm.prompts.thesis_fulltext_repair_prompt import SECTION_EXPANSION_PROMPT
from schemas.thesis_material import ReferenceRecord
from services.thesis.content.abstract_service import (
    generate_abstracts,
)
from services.thesis.content.fulltext_service import count_visible_words, generate_fulltext, validate_fulltext_chapters
from services.thesis.content.quality_service import (
    constrain_fulltext_length,
    extract_confirmed_technologies,
    has_user_empirical_evidence,
    normalize_chapter_count_statement,
    normalize_citation_integrity,
    remove_ai_image_figures,
    sanitize_abstract_truth,
    sanitize_generated_claims,
)
from services.thesis.content.reference_service import generate_references
from services.thesis.document.docx_builder import build_word_document
from services.thesis.document.placeholder import (
    extract_figure_placeholders,
    split_by_render_method,
)
from services.thesis.document.utils import sanitize_filename
from services.thesis.generation.concurrency import text_long_slot
from services.thesis.generation.progress import publish_progress, stage_context
from services.thesis.image import (
    GenerateContentImageGenerator,
    ImageGenerator,
    LazyImageGenerator,
    OpenAIImageGenerator,
    PlaceholderImageGenerator,
    render_all_figures,
)
from services.thesis.profile_policy import acknowledgment_placeholder, thesis_profile_placeholders
from services.thesis_material.reference_service import (
    NO_REFERENCE_NOTICE,
    reference_quality_summary,
    retrieve_reference_records,
)

logger = logging.getLogger(__name__)


# 正文安全清理后短缺时只补写现有小节，不重做文献检索和已完成章节。
async def _repair_short_fulltext(
    full_text: str,
    *,
    title: str,
    target_word_count: int,
    writing_requirements: str,
    confirmed_technologies: set[str],
    evidence_instruction: str,
) -> str:
    """最多三轮向短小节追加经过事实清理的内容。

    Args:
        full_text: 已完成真实性清理的正文。
        title: 论文题目。
        target_word_count: 目标正文篇幅。
        writing_requirements: 用户写作要求。
        confirmed_technologies: 用户已确认技术集合。
        evidence_instruction: 测试数据事实边界。

    Returns:
        保留所有原有章节的正文；仍不足时由最终校验决定失败或告警。
    """
    for _ in range(3):
        current = count_visible_words(full_text)
        if current >= round(target_word_count * 0.9):
            break
        headings = list(re.finditer(r"^#{1,3}\s+.+$", full_text, re.MULTILINE))
        blocks = [
            (heading.start(), headings[index + 1].start() if index + 1 < len(headings) else len(full_text))
            for index, heading in enumerate(headings)
            if index + 1 == len(headings)
            or len(heading.group().split()[0]) >= len(headings[index + 1].group().split()[0])
        ]
        if not blocks:
            break
        start, end = min(blocks, key=lambda block: count_visible_words(full_text[block[0] : block[1]]))
        target = min(1200, max(200, target_word_count - current))
        llm = await create_configured_llm("fulltext", temperature=0.3, max_tokens=target * 3)
        async with text_long_slot():
            response = await llm.ainvoke(
                SECTION_EXPANSION_PROMPT.format_messages(
                    title=title,
                    requirements=writing_requirements,
                    technologies="、".join(sorted(confirmed_technologies)),
                    evidence=evidence_instruction,
                    section=full_text[start:end],
                    target=target,
                )
            )
        if not isinstance(response.content, str):
            continue
        addition = response.content.strip()
        # 新段落不得改变结构或插入图表；不信任模型对输出格式的自觉遵守。
        if re.search(r"(?m)^\s*(?:#|\||```)|<<FIGURE>>", addition):
            continue
        addition = re.sub(r"\[\d+\]", "", addition)
        addition, _ = sanitize_generated_claims(
            addition,
            writing_requirements=writing_requirements,
            confirmed_technologies=confirmed_technologies,
        )
        if addition and addition not in full_text:
            full_text = full_text[:end].rstrip() + "\n\n" + addition + "\n\n" + full_text[end:]
    return full_text


async def _best_effort[T](coro: Awaitable[T], default: T, label: str) -> T:
    """锦上添花环节的降级包装：失败不影响主文档输出。"""
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001
        logger.warning("[best_effort] %s 失败，使用默认值。原因: %s", label, exc)
        return default


@dataclass
class ThesisResult:
    """论文生成结果摘要。"""

    task_id: str
    docx_path: str
    figure_count: int = 0
    mermaid_count: int = 0
    chart_count: int = 0
    ai_image_count: int = 0
    fallback_count: int = 0
    fulltext_char_count: int = 0
    fulltext_word_count: int = 0
    truncation_warning: bool = False
    result_data: dict[str, object] = field(default_factory=dict)


async def _retrieve_verified_references(
    title: str,
    outline: str,
    *,
    chinese_reference_count: int,
    english_reference_count: int,
) -> list[ReferenceRecord]:
    """按论文配置尽力检索真实文献，数量和语言偏好不作为失败门槛。"""

    return await retrieve_reference_records(
        title,
        outline,
        chinese_reference_count=chinese_reference_count,
        english_reference_count=english_reference_count,
    )


async def generate_thesis_document(
    task_id: str,
    title: str,
    outline: str,
    target_word_count: int = 8000,
    chinese_reference_count: int = 25,
    english_reference_count: int = 0,
    writing_requirements: str = "",
    allow_ai_images: bool = True,
) -> ThesisResult:
    """
    论文生成主流程（阶段② + ②.5 + ②.7 + ③）。

    task_id 由 API 层传入，确保状态文件和产物目录一致。
    """

    from core.config import get_settings

    settings = get_settings()
    output_dir = Path(getattr(settings, "thesis_output_root", "public/output/thesis")) / task_id
    safe_title = sanitize_filename(title)
    docx_filename = f"{safe_title}-{task_id}.docx"

    await publish_progress(task_id, "started", "论文生成任务已启动")

    await publish_progress(task_id, "references", "正在检索和整理参考文献")
    with stage_context("references"):
        reference_records = await _retrieve_verified_references(
            title,
            outline,
            chinese_reference_count=chinese_reference_count,
            english_reference_count=english_reference_count,
        )
        references = "\n".join(item.formatted for item in reference_records)

    reference_quality = reference_quality_summary(
        reference_records,
        chinese_reference_count=chinese_reference_count,
        english_reference_count=english_reference_count,
    )
    reference_instruction = ""
    if reference_quality["status"] == "unavailable":
        reference_instruction = (
            f"{NO_REFERENCE_NOTICE} 不得编造作者、题名、DOI、来源、引用编号或声称已有文献支持；"
            "研究现状仅写待核实的研究方向与检索计划，不写成已完成的文献综述。"
        )
    if reference_quality["warnings"]:
        await publish_progress(
            task_id,
            "references",
            "文献检索未完全达到目标，使用实际可用文献继续生成",
            reference_quality=reference_quality,
            quality_warnings=reference_quality["warnings"],
        )

    confirmed_technologies = extract_confirmed_technologies(f"{title}\n{writing_requirements}")
    allow_empirical_data = has_user_empirical_evidence(writing_requirements)
    evidence_instruction = (
        "用户已提供包含测试语义和具体数值的材料；只可复述材料中的数值，不得补造其他指标。"
        if allow_empirical_data
        else "未提供真实测试数据，禁止输出实测结论、具体性能指标或数据图。"
    )

    await publish_progress(task_id, "fulltext", "正在生成论文正文")
    with stage_context("fulltext"):
        full_text = await generate_fulltext(
            outline,
            target_word_count=target_word_count,
            references=references,
            writing_requirements="\n".join(filter(None, [writing_requirements, reference_instruction])),
            confirmed_technologies="、".join(sorted(confirmed_technologies)),
            evidence_instruction=evidence_instruction,
        )
        full_text, suggestion_fields = sanitize_generated_claims(
            full_text,
            writing_requirements=writing_requirements,
            confirmed_technologies=confirmed_technologies,
        )
        if not allow_ai_images:
            full_text, removed_ai_images = remove_ai_image_figures(full_text)
            if removed_ai_images:
                suggestion_fields.append("ai_images_disabled")
        full_text = normalize_chapter_count_statement(full_text)
        # 零文献也必须清理模型擅自生成的引用，不能因为列表为空跳过校验。
        full_text, reference_records = normalize_citation_integrity(full_text, reference_records)
        full_text = await _repair_short_fulltext(
            full_text,
            title=title,
            target_word_count=target_word_count,
            writing_requirements=writing_requirements,
            confirmed_technologies=confirmed_technologies,
            evidence_instruction=evidence_instruction,
        )
        full_text = constrain_fulltext_length(full_text, target_word_count=target_word_count)
        full_text, reference_records = normalize_citation_integrity(full_text, reference_records)
        validate_fulltext_chapters(outline, full_text)
        references = "\n".join(item.formatted for item in reference_records)

    char_count = len(full_text)
    # 正文裁剪和引用清理可能移除未使用条目，最终质量统计以交付文献为准。
    reference_quality = reference_quality_summary(
        reference_records,
        chinese_reference_count=chinese_reference_count,
        english_reference_count=english_reference_count,
    )
    word_count = count_visible_words(full_text)
    truncation_warning = not round(target_word_count * 0.9) <= word_count <= round(target_word_count * 1.1)

    default_abstract = {
        "abstract_zh": "",
        "keywords_zh": "",
        "abstract_en": "",
        "keywords_en": "",
    }
    await publish_progress(task_id, "abstracts", "正在生成摘要和关键词")
    with stage_context("abstracts"):
        abstract_data = await _best_effort(
            generate_abstracts(full_text, evidence_instruction=evidence_instruction),
            default_abstract,
            "摘要生成",
        )
        abstract_data, abstract_changed = sanitize_abstract_truth(
            abstract_data,
            writing_requirements=writing_requirements,
            confirmed_technologies=confirmed_technologies,
        )
        if abstract_changed:
            suggestion_fields.append("abstract_generated_suggestion")
        # 摘要独立生成但不参与正文编号，不保留模型自行添加的来源标记。
        for key in ("abstract_zh", "abstract_en"):
            abstract_data[key], _ = normalize_citation_integrity(abstract_data.get(key, ""), [])

    _, missing_profile_fields = thesis_profile_placeholders()
    acknowledgment = acknowledgment_placeholder()
    suggestion_fields.append("acknowledgment_personal_experience")

    placeholders = extract_figure_placeholders(full_text)
    mermaid_list, chart_list, ai_image_list, fallback_list = split_by_render_method(placeholders)

    image_generator: ImageGenerator = LazyImageGenerator(_create_image_generator)

    await publish_progress(task_id, "figures", "正在渲染论文图表和插图", figure_count=len(placeholders))
    with stage_context("figures"):
        image_paths = await render_all_figures(
            placeholders=placeholders,
            image_generator=image_generator,
            output_dir=str(output_dir / "images"),
            allow_ai_fallback=allow_ai_images,
        )

    await publish_progress(task_id, "document", "正在组装 Word 论文文档")
    with stage_context("document"):
        docx_path = await asyncio.to_thread(
            build_word_document,
            full_text=full_text,
            placeholders=placeholders,
            image_paths=image_paths,
            output_path=str(output_dir / docx_filename),
            title=title,
            abstract_zh=abstract_data.get("abstract_zh", ""),
            abstract_en=abstract_data.get("abstract_en", ""),
            keywords_zh=abstract_data.get("keywords_zh", ""),
            keywords_en=abstract_data.get("keywords_en", ""),
            acknowledgment=acknowledgment,
            references="\n".join(
                filter(
                    None,
                    [
                        references,
                        *[
                            item["message"]
                            if item["message"].startswith("【")
                            else f"【文献检索提示：{item['message']}】"
                            for item in reference_quality["warnings"]
                        ],
                    ],
                )
            ),
        )

    language_counts = {
        "zh": sum(item.language == "zh" for item in reference_records),
        "en": sum(item.language == "en" for item in reference_records),
    }
    result_data: dict[str, object] = {
        "word_count": {
            "metric": "Word/WPS可见正文口径（中文字符逐字、连续英文数字按词；不含图表占位JSON）",
            "target": target_word_count,
            "minimum": round(target_word_count * 0.9),
            "maximum": round(target_word_count * 1.1),
            "actual": word_count,
        },
        "reference_count": len(reference_records),
        "reference_language_counts": language_counts,
        "reference_quality": reference_quality,
        "quality_warnings": reference_quality["warnings"],
        "reference_sources": [
            {
                "index": item.index,
                "title": item.title,
                "provider": item.provider,
                "doi": item.doi,
                "source_url": item.source_url,
            }
            for item in reference_records
        ],
        "citation_integrity": ("closed" if reference_records else "no_references"),
        "missing_profile_fields": missing_profile_fields,
        "generated_suggestion_fields": sorted(set(suggestion_fields)),
        "effective_config": {
            "target_word_count": target_word_count,
            "chinese_reference_count": chinese_reference_count,
            "english_reference_count": english_reference_count,
            "citation_enabled": True,
        },
    }
    return ThesisResult(
        task_id=task_id,
        docx_path=docx_path,
        figure_count=len(placeholders),
        mermaid_count=len(mermaid_list),
        chart_count=len(chart_list),
        ai_image_count=len(ai_image_list),
        fallback_count=len(fallback_list),
        fulltext_char_count=char_count,
        fulltext_word_count=word_count,
        truncation_warning=truncation_warning,
        result_data=result_data,
    )


async def _create_image_generator() -> ImageGenerator:
    """按后台模型配置创建图片生成器。"""

    try:
        image_config = await get_enabled_model_config("figure", allow_default=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取图片模型配置失败，使用占位图生成器。原因: %s", exc)
        return PlaceholderImageGenerator()

    if image_config is None:
        logger.warning("未配置可用的图片模型，使用占位图生成器")
        return PlaceholderImageGenerator()

    image_model_protocol = image_config.provider.lower()
    if image_model_protocol in {"google-generate-content", "gemini-generate-content"}:
        return GenerateContentImageGenerator(
            api_key=image_config.api_key,
            model=image_config.model_name,
            base_url=image_config.api_base_url,
            model_config_id=image_config.id,
        )
    if image_model_protocol == "openai-image-generations":
        return OpenAIImageGenerator(
            api_key=image_config.api_key,
            model=image_config.model_name,
            base_url=image_config.api_base_url,
            model_config_id=image_config.id,
        )

    logger.warning("不支持的图片模型协议 %s，使用占位图生成器", image_model_protocol)
    return PlaceholderImageGenerator()


__all__ = [
    "ThesisResult",
    "build_word_document",
    "extract_figure_placeholders",
    "generate_abstracts",
    "generate_fulltext",
    "generate_references",
    "generate_thesis_document",
    "render_all_figures",
    "split_by_render_method",
]
