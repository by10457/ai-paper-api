import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path

from llm.client import get_enabled_model_config
from services.thesis.content.abstract_service import (
    generate_abstracts,
    generate_acknowledgment,
)
from services.thesis.content.fulltext_service import generate_fulltext
from services.thesis.content.reference_service import generate_references
from services.thesis.document.docx_builder import build_word_document
from services.thesis.document.image_renderer import (
    GenerateContentImageGenerator,
    ImageGenerator,
    PlaceholderImageGenerator,
    render_all_figures,
)
from services.thesis.document.placeholder import (
    extract_figure_placeholders,
    split_by_render_method,
)
from services.thesis.document.utils import sanitize_filename

logger = logging.getLogger(__name__)


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
    truncation_warning: bool = False


async def generate_thesis_document(
    task_id: str,
    title: str,
    outline: str,
    target_word_count: int = 8000,
    codetype: str = "否",
    wxquote: str = "标注",
    language: str = "否",
    wxnum: int = 25,
    author: str = "作者姓名",
    advisor: str = "指导教师",
    degree_type: str = "学士",
    major: str = "专业名称",
    school: str = "XX大学XX学院",
    year_month: str = "",
    student_id: str = "",
    student_class: str = "",
) -> ThesisResult:
    """
    论文生成主流程（阶段② + ②.5 + ②.7 + ③）。

    task_id 由 API 层传入，确保状态文件和产物目录一致。
    """

    from core.config import get_settings

    settings = get_settings()
    output_dir = Path(getattr(settings, "thesis_output_root", "public/output/thesis")) / task_id
    safe_title = sanitize_filename(title)

    references = ""
    if wxquote != "不标注":
        references = await _best_effort(
            generate_references(
                title,
                outline,
                wxnum=wxnum,
                include_english=language == "是",
            ),
            "",
            "参考文献生成",
        )

    full_text = await generate_fulltext(
        outline,
        target_word_count=target_word_count,
        references=references,
        codetype=codetype,
    )

    char_count = len(full_text)
    truncation_warning = False
    truncation_threshold = int(target_word_count * 0.75)
    if char_count < truncation_threshold:
        logger.warning("全文仅 %d 字（低于目标 %d 字的 75%%），可能存在截断", char_count, target_word_count)
        truncation_warning = True

    default_abstract = {
        "abstract_zh": "",
        "keywords_zh": "",
        "abstract_en": "",
        "keywords_en": "",
    }
    abstract_data, acknowledgment = await asyncio.gather(
        _best_effort(generate_abstracts(full_text), default_abstract, "摘要生成"),
        _best_effort(generate_acknowledgment(title, advisor), "", "致谢生成"),
    )

    placeholders = extract_figure_placeholders(full_text)
    mermaid_list, chart_list, ai_image_list, fallback_list = split_by_render_method(placeholders)

    needs_image_model = bool(ai_image_list or mermaid_list)
    image_config = None
    if needs_image_model:
        try:
            image_config = await get_enabled_model_config("figure", allow_default=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取图片模型配置失败，使用占位图生成器。原因: %s", exc)
    image_model_protocol = image_config.provider.lower() if image_config else ""

    if image_config and image_model_protocol in {"google-generate-content", "gemini-generate-content"}:
        image_generator: ImageGenerator = GenerateContentImageGenerator(
            api_key=image_config.api_key,
            model=image_config.model_name,
            base_url=image_config.api_base_url,
        )
    else:
        if image_config:
            logger.warning("不支持的图片模型协议 %s，使用占位图生成器", image_model_protocol)
        image_generator = PlaceholderImageGenerator()

    image_paths = await render_all_figures(
        placeholders=placeholders,
        image_generator=image_generator,
        output_dir=str(output_dir / "images"),
    )

    docx_path = build_word_document(
        full_text=full_text,
        placeholders=placeholders,
        image_paths=image_paths,
        output_path=str(output_dir / f"论文_{safe_title}.docx"),
        title=title,
        author=author,
        advisor=advisor,
        degree_type=degree_type,
        major=major,
        school=school,
        year_month=year_month,
        student_id=student_id,
        student_class=student_class,
        abstract_zh=abstract_data.get("abstract_zh", ""),
        abstract_en=abstract_data.get("abstract_en", ""),
        keywords_zh=abstract_data.get("keywords_zh", ""),
        keywords_en=abstract_data.get("keywords_en", ""),
        acknowledgment=acknowledgment,
        references=references,
    )

    return ThesisResult(
        task_id=task_id,
        docx_path=docx_path,
        figure_count=len(placeholders),
        mermaid_count=len(mermaid_list),
        chart_count=len(chart_list),
        ai_image_count=len(ai_image_list),
        fallback_count=len(fallback_list),
        fulltext_char_count=char_count,
        truncation_warning=truncation_warning,
    )


__all__ = [
    "ThesisResult",
    "build_word_document",
    "extract_figure_placeholders",
    "generate_abstracts",
    "generate_acknowledgment",
    "generate_fulltext",
    "generate_references",
    "generate_thesis_document",
    "render_all_figures",
    "split_by_render_method",
]
