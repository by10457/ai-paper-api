import asyncio
import warnings
from collections.abc import Generator
from pathlib import Path

import pytest

import services.thesis.document.image_renderer as image_renderer
from services.thesis.document.image_renderer import (
    GenerateContentImageGenerator,
    PlaceholderImageGenerator,
    _normalize_mermaid_code,
    _resolve_chart_font,
    _summarize_render_error,
    render_all_figures,
    render_chart,
    render_mermaid,
)


def _chart_spec(chart_type: str) -> dict:
    base = {
        "caption": "图表",
        "render_method": "chart",
        "chart_type": chart_type,
        "title": "测试图表",
        "x_label": "X",
        "y_label": "Y",
        "categories": ["A", "B", "C"],
    }
    if chart_type == "pie":
        return base | {
            "series": [{"name": "占比", "data": [45, 35, 20]}],
        }
    return base | {
        "series": [{"name": "值", "data": [1, 3, 2]}],
    }


def test_render_chart_line_creates_png(tmp_path: Path) -> None:
    output = tmp_path / "line.png"
    path = asyncio.run(render_chart(_chart_spec("line"), str(output)))
    assert Path(path).exists()
    assert Path(path).stat().st_size > 0


def test_render_chart_bar_creates_png(tmp_path: Path) -> None:
    output = tmp_path / "bar.png"
    path = asyncio.run(render_chart(_chart_spec("bar"), str(output)))
    assert Path(path).exists()
    assert Path(path).stat().st_size > 0


def test_render_chart_pie_creates_png(tmp_path: Path) -> None:
    output = tmp_path / "pie.png"
    path = asyncio.run(render_chart(_chart_spec("pie"), str(output)))
    assert Path(path).exists()
    assert Path(path).stat().st_size > 0


def test_render_all_figures_dispatches_chart(tmp_path: Path) -> None:
    output_dir = tmp_path / "images"
    placeholders = [
        _chart_spec("line") | {"index": 0},
    ]

    result = asyncio.run(
        render_all_figures(
            placeholders=placeholders,
            image_generator=PlaceholderImageGenerator(),
            output_dir=str(output_dir),
        )
    )

    assert 0 in result
    assert result[0] is not None
    assert Path(result[0]).exists()


def test_render_mermaid_reports_missing_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(image_renderer.shutil, "which", lambda _: None)

    with pytest.raises(RuntimeError, match="Mermaid CLI 未安装"):
        asyncio.run(render_mermaid("graph TD; A-->B;", str(tmp_path / "flow.png")))


def test_normalize_mermaid_usecase_diagram_to_flowchart() -> None:
    code = """
usecaseDiagram
    actor 普通用户
    actor 安全管理员
    package "安全检测与防御系统" {
        usecase "流量深度解析" as UC1
        usecase "恶意请求阻断" as UC2
    }
    普通用户 --> UC1
    UC1 --> UC2 : 触发安全阈值
    安全管理员 --> UC2
"""

    normalized = _normalize_mermaid_code(code)

    assert normalized.startswith("flowchart TD")
    assert 'ACTOR_1["普通用户"]' in normalized
    assert 'subgraph PKG_1["安全检测与防御系统"]' in normalized
    assert 'UC1(["流量深度解析"])' in normalized
    assert 'ACTOR_1 --> UC1' in normalized
    assert 'UC1 -->|"触发安全阈值"| UC2' in normalized


def test_summarize_render_error_keeps_first_line_only() -> None:
    error = RuntimeError("Mermaid 渲染失败\nstack line 1\nstack line 2")

    assert _summarize_render_error(error) == "Mermaid 渲染失败"


def test_generate_content_image_error_url_masks_api_key() -> None:
    generator = GenerateContentImageGenerator(
        api_key="sk-secret",
        model="gemini-3-pro-image-preview",
        base_url="https://cdn.12ai.org",
    )

    safe_url = generator._build_safe_url()

    assert "sk-secret" not in safe_url
    assert "key=***" in safe_url


@pytest.fixture(autouse=True)
def clear_chart_font_cache() -> Generator[None]:
    _resolve_chart_font.cache_clear()
    yield
    _resolve_chart_font.cache_clear()


def test_resolve_chart_font_prefers_installed_chinese_font(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        image_renderer,
        "_available_chart_fonts",
        lambda: [
            ("DejaVu Sans", "/usr/share/fonts/dejavu/DejaVuSans.ttf"),
            ("Noto Sans CJK SC", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        ],
    )

    font_name, font_path = _resolve_chart_font()

    assert font_name == "Noto Sans CJK SC"
    assert font_path is not None
    assert "NotoSansCJK".lower() in font_path.lower()


def test_resolve_chart_font_falls_back_to_dejavu(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        image_renderer,
        "_available_chart_fonts",
        lambda: [("DejaVu Sans", "/usr/share/fonts/dejavu/DejaVuSans.ttf")],
    )

    font_name, font_path = _resolve_chart_font()

    assert font_name == "DejaVu Sans"
    assert font_path is not None
    assert "DejaVuSans".lower() in font_path.lower()


def test_render_chart_uses_resolved_font_without_missing_glyph_warning(
        tmp_path: Path,
) -> None:
    output = tmp_path / "line_cn.png"
    font_name, font_path = _resolve_chart_font()
    if font_name == "DejaVu Sans":
        pytest.skip("当前测试环境没有可用中文字体，跳过中文缺字校验")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        path = asyncio.run(
            render_chart(
                {
                    "caption": "图表",
                    "render_method": "chart",
                    "chart_type": "line",
                    "title": "测试图表",
                    "x_label": "时间（秒）",
                    "y_label": "响应时间（毫秒）",
                    "categories": ["一", "二", "三"],
                    "series": [{"name": "平均值", "data": [1, 2, 3]}],
                },
                str(output),
            )
        )

    assert Path(path).exists()
    assert all("Glyph" not in str(item.message) for item in caught)
