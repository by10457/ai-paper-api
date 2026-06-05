"""论文图片生成与渲染能力。"""

from services.thesis.image.ai_generator import (
    GenerateContentImageGenerator,
    ImageGenerator,
    OpenAIImageGenerator,
    PlaceholderImageGenerator,
)
from services.thesis.image.chart_renderer import render_chart
from services.thesis.image.mermaid_renderer import render_mermaid
from services.thesis.image.renderer import render_all_figures

__all__ = [
    "GenerateContentImageGenerator",
    "ImageGenerator",
    "OpenAIImageGenerator",
    "PlaceholderImageGenerator",
    "render_all_figures",
    "render_chart",
    "render_mermaid",
]
