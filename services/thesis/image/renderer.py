"""论文图片占位符批量渲染调度。"""

import asyncio
import logging
from pathlib import Path

from services.thesis.generation.concurrency import ai_image_render_slot, chart_render_slot, mermaid_render_slot
from services.thesis.image.ai_generator import ImageGenerator
from services.thesis.image.chart_renderer import render_chart
from services.thesis.image.mermaid_renderer import render_mermaid
from services.thesis.image.utils import summarize_render_error

logger = logging.getLogger(__name__)


async def render_all_figures(
    placeholders: list[dict],
    image_generator: ImageGenerator,
    output_dir: str = "public/output/thesis/images",
) -> dict[int, str | None]:
    """并发渲染所有占位符，返回 {index: path_or_none}。"""

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    async def _render_one(placeholder: dict) -> tuple[int, str | None]:
        index = placeholder["index"]
        output_path = f"{output_dir}/fig_{index}.png"
        method = placeholder.get("render_method")

        max_retries = 1 if method in {"ai_image", "mermaid"} else 2
        attempt = 0
        while attempt < max_retries:
            try:
                if method == "mermaid":
                    async with mermaid_render_slot():
                        rendered_path = await render_mermaid(placeholder["mermaid_code"], output_path)
                    return index, rendered_path
                if method == "chart":
                    async with chart_render_slot():
                        rendered_path = await render_chart(placeholder, output_path)
                    return index, rendered_path
                if method == "ai_image":
                    async with ai_image_render_slot():
                        rendered_path = await image_generator.generate(
                            description=placeholder.get("description", placeholder.get("caption", "学术插图")),
                            style=placeholder.get("style", "concept_illustration"),
                            aspect_ratio=placeholder.get("aspect_ratio", "16:9"),
                            output_path=output_path,
                        )
                    return index, rendered_path
                if method == "fallback":
                    logger.warning("占位符 #%d 为 fallback，跳过渲染", index)
                    return index, None

                logger.warning("占位符 #%d 的 render_method 非法: %s", index, method)
                return index, None

            except Exception as exc:
                if method == "mermaid":
                    logger.warning("占位符 #%d Mermaid 失败，转 ai_image 兜底: %s", index, summarize_render_error(exc))
                    method = "ai_image"
                    max_retries = 1
                    attempt = 0
                    continue

                attempt += 1
                if attempt < max_retries:
                    logger.warning(
                        "占位符 #%d 渲染出错，重试 %d/%d: %s",
                        index,
                        attempt,
                        max_retries,
                        summarize_render_error(exc),
                    )
                    await asyncio.sleep(2)
                else:
                    logger.warning(
                        "占位符 #%d 渲染失败，跳过该图 (已尝试 %d 次): %s",
                        index,
                        max_retries,
                        summarize_render_error(exc),
                    )
                    return index, None

        return index, None

    pairs = await asyncio.gather(*[_render_one(item) for item in placeholders])
    return dict(pairs)
