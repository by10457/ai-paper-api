import asyncio
import warnings
from pathlib import Path

import pytest

import services.thesis.image_renderer as image_renderer
from services.thesis.image_renderer import (
    PlaceholderImageGenerator,
    _resolve_chart_font,
    render_all_figures,
    render_chart,
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


@pytest.fixture(autouse=True)
def clear_chart_font_cache() -> None:
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
