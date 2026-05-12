import json

from schemas.thesis import (
    extract_figure_placeholders,
    split_by_render_method,
    validate_figure_payload,
)


def _figure_block(payload: dict) -> str:
    return f"<<FIGURE>>{json.dumps(payload, ensure_ascii=False)}<</FIGURE>>"


def test_validate_figure_payload_mermaid() -> None:
    result = validate_figure_payload(
        {
            "caption": "系统架构图",
            "render_method": "mermaid",
            "mermaid_code": "graph TD; A-->B;",
        },
        index=0,
    )

    assert result["render_method"] == "mermaid"
    assert result["caption"] == "系统架构图"
    assert result["index"] == 0


def test_validate_figure_payload_ai_image() -> None:
    result = validate_figure_payload(
        {
            "caption": "概念图",
            "render_method": "ai_image",
            "description": "A modern AI lab",
        },
        index=1,
    )

    assert result["render_method"] == "ai_image"
    assert result["style"] == "concept_illustration"
    assert result["aspect_ratio"] == "16:9"
    assert result["index"] == 1


def test_validate_figure_payload_chart_line() -> None:
    result = validate_figure_payload(
        {
            "caption": "响应时间趋势图",
            "render_method": "chart",
            "chart_type": "line",
            "title": "接口响应时间趋势",
            "x_label": "时间（秒）",
            "y_label": "响应时间（秒）",
            "categories": ["0", "60", "120"],
            "series": [{"name": "响应时间", "data": [0.5, 2.1, 1.8]}],
        },
        index=2,
    )

    assert result["render_method"] == "chart"
    assert result["chart_type"] == "line"
    assert result["index"] == 2


def test_validate_figure_payload_chart_bar() -> None:
    result = validate_figure_payload(
        {
            "caption": "模块耗时对比图",
            "render_method": "chart",
            "chart_type": "bar",
            "title": "模块耗时对比",
            "categories": ["选题", "大纲", "正文"],
            "series": [{"name": "耗时", "data": [1.2, 2.4, 4.6]}],
        },
        index=3,
    )

    assert result["render_method"] == "chart"
    assert result["chart_type"] == "bar"


def test_validate_figure_payload_chart_pie() -> None:
    result = validate_figure_payload(
        {
            "caption": "资源占比图",
            "render_method": "chart",
            "chart_type": "pie",
            "title": "资源占比",
            "categories": ["CPU", "内存", "IO"],
            "series": [{"name": "占比", "data": [40, 35, 25]}],
        },
        index=4,
    )

    assert result["render_method"] == "chart"
    assert result["chart_type"] == "pie"


def test_validate_figure_payload_chart_mismatch_fallback() -> None:
    result = validate_figure_payload(
        {
            "caption": "错误图表",
            "render_method": "chart",
            "chart_type": "line",
            "title": "错误图表",
            "categories": ["0", "60", "120"],
            "series": [{"name": "响应时间", "data": [0.5, 2.1]}],
        },
        index=5,
    )

    assert result["render_method"] == "fallback"
    assert result["index"] == 5


def test_validate_figure_payload_chart_invalid_type_fallback() -> None:
    result = validate_figure_payload(
        {
            "caption": "非法图表",
            "render_method": "chart",
            "chart_type": "scatter",
            "title": "非法图表",
            "categories": ["A", "B"],
            "series": [{"name": "值", "data": [1, 2]}],
        },
        index=6,
    )

    assert result["render_method"] == "fallback"
    assert result["index"] == 6


def test_extract_figure_placeholders_json_parse_error_fallback() -> None:
    text = "前文\n<<FIGURE>>{bad json}<</FIGURE>>\n后文"

    placeholders = extract_figure_placeholders(text)

    assert len(placeholders) == 1
    assert placeholders[0]["render_method"] == "fallback"
    assert placeholders[0]["index"] == 0
    assert "JSON 解析失败" in placeholders[0]["error"]


def test_extract_figure_placeholders_missing_required_field_fallback() -> None:
    text = _figure_block(
        {
            "caption": "缺少代码",
            "render_method": "mermaid",
        }
    )

    placeholders = extract_figure_placeholders(text)

    assert len(placeholders) == 1
    assert placeholders[0]["render_method"] == "fallback"
    assert placeholders[0]["index"] == 0


def test_extract_figure_placeholders_unknown_method_fallback() -> None:
    text = _figure_block(
        {
            "caption": "未知渲染类型",
            "render_method": "xyz",
            "description": "anything",
        }
    )

    placeholders = extract_figure_placeholders(text)

    assert len(placeholders) == 1
    assert placeholders[0]["render_method"] == "fallback"
    assert placeholders[0]["index"] == 0


def test_extract_figure_placeholders_empty_text() -> None:
    placeholders = extract_figure_placeholders("这是一段没有占位符的正文。")
    assert placeholders == []


def test_split_by_render_method() -> None:
    text = "\n".join(
        [
            _figure_block(
                {
                    "caption": "流程图",
                    "render_method": "mermaid",
                    "mermaid_code": "graph TD; A-->B;",
                }
            ),
            _figure_block(
                {
                    "caption": "插画",
                    "render_method": "ai_image",
                    "description": "A city skyline",
                }
            ),
            _figure_block(
                {
                    "caption": "趋势图",
                    "render_method": "chart",
                    "chart_type": "line",
                    "title": "接口响应时间趋势",
                    "categories": ["0", "60", "120"],
                    "series": [{"name": "响应时间", "data": [0.5, 2.1, 1.8]}],
                }
            ),
            "<<FIGURE>>{broken}<</FIGURE>>",
        ]
    )

    placeholders = extract_figure_placeholders(text)
    mermaid, chart, ai_image, fallback = split_by_render_method(placeholders)

    assert len(placeholders) == 4
    assert len(mermaid) == 1
    assert len(chart) == 1
    assert len(ai_image) == 1
    assert len(fallback) == 1
