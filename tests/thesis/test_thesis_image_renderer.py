import asyncio
import base64
import warnings
from collections.abc import Generator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

import services.thesis.image.chart_renderer as chart_renderer
import services.thesis.image.mermaid_renderer as mermaid_renderer
from services.thesis.image.ai_generator import (
    GenerateContentImageGenerator,
    OpenAIImageGenerator,
    PlaceholderImageGenerator,
)
from services.thesis.image.chart_renderer import (
    _resolve_chart_font,
    render_chart,
)
from services.thesis.image.mermaid_renderer import (
    _normalize_mermaid_code,
    render_mermaid,
)
from services.thesis.image.renderer import render_all_figures
from services.thesis.image.utils import summarize_render_error


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


def test_render_all_figures_uses_method_concurrency_slots(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
) -> None:
    events: list[str] = []

    def slot(name: str):
        @asynccontextmanager
        async def _slot():
            events.append(name)
            yield

        return _slot

    async def fake_render_mermaid(_code: str, output_path: str) -> str:
        Path(output_path).write_bytes(b"mermaid")
        return output_path

    async def fake_render_chart(_spec: dict, output_path: str) -> str:
        Path(output_path).write_bytes(b"chart")
        return output_path

    class FakeImageGenerator(PlaceholderImageGenerator):
        async def generate(
            self,
            description: str,
            style: str,
            aspect_ratio: str,
            output_path: str,
        ) -> str:
            Path(output_path).write_bytes(b"ai")
            return output_path

    monkeypatch.setattr("services.thesis.image.renderer.mermaid_render_slot", slot("mermaid"))
    monkeypatch.setattr("services.thesis.image.renderer.chart_render_slot", slot("chart"))
    monkeypatch.setattr("services.thesis.image.renderer.ai_image_render_slot", slot("ai_image"))
    monkeypatch.setattr("services.thesis.image.renderer.render_mermaid", fake_render_mermaid)
    monkeypatch.setattr("services.thesis.image.renderer.render_chart", fake_render_chart)

    result = asyncio.run(
        render_all_figures(
            placeholders=[
                {"index": 0, "render_method": "mermaid", "mermaid_code": "graph TD;A-->B;"},
                _chart_spec("line") | {"index": 1},
                {"index": 2, "render_method": "ai_image", "description": "插图"},
            ],
            image_generator=FakeImageGenerator(),
            output_dir=str(tmp_path / "images"),
        )
    )

    assert events == ["mermaid", "chart", "ai_image"]
    assert sorted(result) == [0, 1, 2]


def test_render_mermaid_reports_missing_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(mermaid_renderer.shutil, "which", lambda _: None)

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


def test_normalize_flowchart_quotes_labels_and_edge_text() -> None:
    code = """
graph TD
    subgraph 前端业务服务
        A[用户输入(题目/字数)] --> B{是否通过:校验}
    end
    B --> C[生成论文文件] : 通过
"""

    normalized = _normalize_mermaid_code(code)

    assert normalized.startswith("flowchart TD")
    assert 'subgraph SUBGRAPH_1["前端业务服务"]' in normalized
    assert 'A["用户输入(题目/字数)"] --> B{"是否通过:校验"}' in normalized
    assert 'B -->|"通过"| C["生成论文文件"]' in normalized


def test_normalize_flowchart_splits_semicolon_statements() -> None:
    code = 'graph TD;A[模块A] --> B[模块B];B --> C[模块C]'

    normalized = _normalize_mermaid_code(code)

    assert normalized.splitlines() == [
        "flowchart TD",
        'A["模块A"] --> B["模块B"]',
        'B --> C["模块C"]',
    ]


def test_summarize_render_error_keeps_first_line_only() -> None:
    error = RuntimeError("Mermaid 渲染失败\nstack line 1\nstack line 2")

    assert summarize_render_error(error) == "Mermaid 渲染失败"


def test_generate_content_image_error_url_masks_api_key() -> None:
    generator = GenerateContentImageGenerator(
        api_key="sk-secret",
        model="gemini-3-pro-image-preview",
        base_url="https://cdn.12ai.org",
    )

    safe_url = generator._build_safe_url()

    assert "sk-secret" not in safe_url
    assert "key=***" in safe_url


def test_openai_image_error_url_masks_api_key() -> None:
    generator = OpenAIImageGenerator(
        api_key="sk-secret",
        model="gpt-image-1",
        base_url="https://api.openai.com",
    )

    safe_url = generator._build_safe_url()

    assert "sk-secret" not in safe_url
    assert safe_url == "https://api.openai.com/v1/images/generations"


def test_openai_image_size_mapping() -> None:
    generator = OpenAIImageGenerator(
        api_key="sk-secret",
        model="gpt-image-1",
        base_url="https://api.openai.com/v1",
    )

    assert generator._resolve_size("1:1") == "1024x1024"
    assert generator._resolve_size("16:9") == "1536x1024"
    assert generator._resolve_size("4:3") == "1536x1024"
    assert generator._resolve_size("9:16") == "1024x1536"
    assert generator._resolve_size("3:4") == "1024x1536"


def test_openai_image_extracts_base64_bytes() -> None:
    async def run() -> bytes:
        generator = OpenAIImageGenerator(
            api_key="sk-secret",
            model="gpt-image-1",
            base_url="https://api.openai.com",
        )
        image_bytes = b"fake-image-bytes"
        data = {"data": [{"b64_json": base64.b64encode(image_bytes).decode()}]}
        async with httpx.AsyncClient() as client:
            return await generator._extract_image_bytes(data, client)

    assert asyncio.run(run()) == b"fake-image-bytes"


@pytest.fixture(autouse=True)
def clear_chart_font_cache() -> Generator[None]:
    _resolve_chart_font.cache_clear()
    yield
    _resolve_chart_font.cache_clear()


def test_resolve_chart_font_prefers_installed_chinese_font(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chart_renderer,
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
        chart_renderer,
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
