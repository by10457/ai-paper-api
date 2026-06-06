"""图片占位符协议转发模块，统一暴露 schemas 中的解析与校验能力。"""

from schemas.thesis import (
    FIGURE_BLOCK_PATTERN,
    AiImageFigure,
    ChartFigure,
    ChartSeries,
    FallbackFigure,
    MermaidFigure,
    extract_figure_placeholders,
    split_by_render_method,
    validate_figure_payload,
)

__all__ = [
    "AiImageFigure",
    "ChartFigure",
    "ChartSeries",
    "FallbackFigure",
    "FIGURE_BLOCK_PATTERN",
    "MermaidFigure",
    "extract_figure_placeholders",
    "split_by_render_method",
    "validate_figure_payload",
]
