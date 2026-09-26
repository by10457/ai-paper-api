import json

import pytest
from pydantic import ValidationError

from schemas.thesis import (
    GenerateRequest,
    OutlinePayload,
    OutlineRequest,
    PaperOrderCreateRequest,
    PaperOutlineCreateRequest,
    ReferenceConfig,
    extract_figure_placeholders,
    split_by_render_method,
    validate_figure_payload,
)


def test_generate_request_preserves_explicit_reference_counts() -> None:
    """直连接口分别保留中英文篇数。"""

    payload = GenerateRequest.model_validate(
        {
            "title": "基于 Spring Boot 与 Vue 的校园二手交易平台设计与实现",
            "outline_json": [
                {
                    "chapter": "绪论",
                    "sections": [{"name": "研究背景", "abstract": "说明研究背景。"}],
                }
            ],
            "chinese_reference_count": 8,
            "english_reference_count": 4,
        }
    )

    assert payload.chinese_reference_count == 8
    assert payload.english_reference_count == 4


def test_generate_request_defaults_to_chinese_references() -> None:
    """省略数量时默认25篇中文文献。"""

    payload = GenerateRequest.model_validate(
        {
            "title": "论文题目",
            "outline_json": [
                {
                    "chapter": "绪论",
                    "sections": [{"name": "研究背景", "abstract": "说明研究背景。"}],
                }
            ],
        }
    )

    assert payload.chinese_reference_count == 25
    assert payload.english_reference_count == 0


# 验证两种语言可独立关闭、但总数不能为零或超限
@pytest.mark.parametrize("chinese,english", [(0, 1), (25, 0), (3, 17), (50, 50)])
def test_reference_counts_accept_language_targets(chinese: int, english: int) -> None:
    """中英文目标应原样保留，不再隐式分配比例。"""
    config = ReferenceConfig(chinese_reference_count=chinese, english_reference_count=english)
    assert config.model_dump() == {"chinese_reference_count": chinese, "english_reference_count": english}


# 拒绝非法数量，防止检索阶段才发现参数错误
@pytest.mark.parametrize("chinese,english", [(0, 0), (-1, 5), (5, -1), (90, 11), (1.5, 2)])
def test_reference_counts_reject_invalid_targets(chinese: float, english: int) -> None:
    """负数、小数、零总数与超限总数均应在请求校验时拒绝。"""
    with pytest.raises(ValidationError):
        ReferenceConfig.model_validate({"chinese_reference_count": chinese, "english_reference_count": english})


# 新契约不再接受已移除的开关或历史文献字段
@pytest.mark.parametrize("field", ["codetype", "wxquote", "language", "wxnum", "reference_count", "include_foreign"])
def test_outline_rejects_removed_parameters(field: str) -> None:
    """明确报错，避免旧参数被静默忽略后使用错误数量。"""
    with pytest.raises(ValidationError):
        OutlineRequest.model_validate({"title": "测试论文", field: "旧参数"})


# 检查两个大纲入口共享文献字段并保留篇幅和层级开关
def test_outline_schemas_expose_shared_configuration() -> None:
    """直接接口与管理端接口的文献配置保持一致。"""
    for schema in (OutlineRequest, PaperOutlineCreateRequest):
        fields = schema.model_json_schema()["properties"]
        assert {"chinese_reference_count", "english_reference_count", "target_word_count"} <= fields.keys()
        assert not {"codetype", "wxquote", "language", "wxnum", "reference_count", "include_foreign"} & fields.keys()


def test_outline_payload_preserves_third_level_subsections() -> None:
    """三级大纲应保留并规范化二级章节下的三级小节。"""

    payload = OutlinePayload.model_validate(
        {
            "outline": [
                {
                    "chapter": "1 绪论",
                    "sections": [
                        {
                            "name": "1.1 研究背景",
                            "abstract": "介绍研究背景。",
                            "subsections": [
                                {
                                    "name": "1.1.1 行业背景",
                                    "abstract": "介绍行业发展情况。",
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )

    section = payload.outline[0].sections[0]
    assert section.name == "研究背景"
    assert len(section.subsections) == 1
    assert section.subsections[0].name == "行业背景"


def test_outline_payload_defaults_subsections_for_legacy_clients() -> None:
    """旧版两级大纲缺少 subsections 时应继续通过校验。"""

    payload = OutlinePayload.model_validate(
        {
            "outline": [
                {
                    "chapter": "绪论",
                    "sections": [{"name": "研究背景", "abstract": "介绍研究背景。"}],
                }
            ]
        }
    )

    assert payload.outline[0].sections[0].subsections == []


def test_paper_order_create_rejects_chapter_without_sections() -> None:
    """订单大纲应拒绝没有有效小节的章节。"""

    with pytest.raises(ValidationError):
        PaperOrderCreateRequest.model_validate({"record_id": 1, "outline": [{"chapter": "绪论", "sections": []}]})


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


def test_extract_figure_placeholders_repairs_unescaped_mermaid_quotes() -> None:
    text = (
        "前文\n"
        "<<FIGURE>>\n"
        "{\n"
        '  "caption": "图 3.1 业务流程图",\n'
        '  "render_method": "mermaid",\n'
        '  "mermaid_code": "flowchart TD\\n    A["用户提交信息"] --> B["系统校验"]"\n'
        "}\n"
        "<</FIGURE>>\n"
        "后文"
    )

    placeholders = extract_figure_placeholders(text)

    assert len(placeholders) == 1
    assert placeholders[0]["render_method"] == "mermaid"
    assert placeholders[0]["index"] == 0
    assert 'A["用户提交信息"]' in placeholders[0]["mermaid_code"]


def test_extract_figure_placeholders_repairs_trailing_commas() -> None:
    text = (
        "<<FIGURE>>\n"
        "{\n"
        '  "caption": "图 4.1 测试结果趋势图",\n'
        '  "render_method": "chart",\n'
        '  "chart_type": "line",\n'
        '  "title": "测试结果趋势",\n'
        '  "categories": ["0", "60", "120",],\n'
        '  "series": [{"name": "响应时间", "data": [0.5, 1.2, 0.9,],}],\n'
        "}\n"
        "<</FIGURE>>"
    )

    placeholders = extract_figure_placeholders(text)

    assert len(placeholders) == 1
    assert placeholders[0]["render_method"] == "chart"
    assert placeholders[0]["categories"] == ["0", "60", "120"]


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

# 所有生成入口拒绝个人信息，校验发生在服务与持久化之前
@pytest.mark.parametrize("field", [
    "author", "advisor", "degree_type", "major", "school", "year_month",
    "student_id", "student_class", "student_profile", "form_params", "three_level",
])
def test_generation_requests_reject_personal_fields(field: str) -> None:
    """验证旧个人信息与任意快照入口不再被接收。

    Args:
        field: 禁止作为请求参数提交的字段。
    """
    from schemas.thesis_material import LiteratureReviewRequest, ProposalReportRequest, TaskBookRequest

    for request_type in (OutlineRequest, PaperOutlineCreateRequest, GenerateRequest,
                         ProposalReportRequest, LiteratureReviewRequest, TaskBookRequest):
        payload: dict[str, object] = {"title": "隐私边界测试论文", field: "虚构敏感信息"}
        if request_type is GenerateRequest:
            payload["outline_json"] = [{"chapter": "绪论", "sections": [{"name": "背景", "abstract": "背景"}]}]
        with pytest.raises(ValidationError) as exc_info:
            request_type.model_validate(payload)
        assert any(error["loc"] == (field,) and error["type"] == "extra_forbidden"
                   for error in exc_info.value.errors())
        assert field not in request_type.model_json_schema()["properties"]

# 对实际 FastAPI 文档检查公开契约，避免仅修改未挂载的模型
def test_openapi_generation_requests_exclude_personal_information() -> None:
    """验证完整 OpenAPI 可生成，且各生成请求不再公开个人信息字段。"""
    from app import app

    schemas = app.openapi()["components"]["schemas"]
    forbidden = {"author", "advisor", "degree_type", "major", "school", "year_month",
                 "student_id", "student_class", "student_profile", "form_params"}
    for name in ("GenerateRequest", "OutlineRequest", "PaperOutlineCreateRequest",
                 "ProposalReportRequest", "LiteratureReviewRequest", "TaskBookRequest"):
        assert not forbidden & schemas[name]["properties"].keys()
        assert schemas[name]["additionalProperties"] is False
