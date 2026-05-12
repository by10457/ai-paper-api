import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

logger = logging.getLogger(__name__)

# 匹配 <<FIGURE>> ... <</FIGURE>> 占位块，支持跨行内容。
FIGURE_BLOCK_PATTERN = re.compile(r"<<FIGURE>>\s*(.*?)\s*<</FIGURE>>", re.DOTALL)


class OutlineRequest(BaseModel):
    """生成论文大纲请求。"""

    title: str = Field(..., min_length=2, max_length=200, description="论文标题")
    target_word_count: int = Field(
        default=8000,
        description="目标正文字数",
    )
    codetype: str = Field(default="否", description="代码语言类型，否=不生成代码")
    language: str = Field(default="否", description="是否引用外文文献：是/否")
    three_level: bool = Field(default=False, description="是否使用三级目录结构")
    aboutmsg: str = Field(default="", max_length=1000, description="写作方向补充说明")


class OutlineSection(BaseModel):
    """论文大纲小节。"""

    name: str
    abstract: str

    @model_validator(mode="after")
    def normalize_name(self) -> "OutlineSection":
        self.name = re.sub(r"^\s*\d+(?:\.\d+)*[\.\s、-]*", "", self.name).strip()
        return self


class OutlineChapter(BaseModel):
    """论文大纲章节。"""

    chapter: str
    sections: list[OutlineSection]

    @model_validator(mode="after")
    def normalize_chapter(self) -> "OutlineChapter":
        self.chapter = re.sub(r"^\s*第[一二三四五六七八九十百零\d]+章[\s、:：.-]*", "", self.chapter).strip()
        self.chapter = re.sub(r"^\s*\d+[\.\s、-]*", "", self.chapter).strip()
        return self


class OutlinePayload(BaseModel):
    """结构化大纲载荷。"""

    outline: list[OutlineChapter]
    abstract: str = ""
    keywords: str = ""


class OutlineResponse(OutlinePayload):
    """生成论文大纲响应。"""

    title: str


class GenerateRequest(BaseModel):
    """提交论文生成任务请求。"""

    title: str = Field(..., min_length=2, max_length=200, description="论文标题")
    outline_json: list[OutlineChapter] = Field(
        ...,
        description="JSON 格式大纲, 结构同 OutlineResponse.outline",
    )
    target_word_count: int = Field(
        default=8000,
        description="目标正文字数",
    )
    codetype: str = Field(default="否")
    wxquote: str = Field(default="标注", description="标注/不标注")
    language: str = Field(default="否")
    wxnum: int = Field(default=25, description="参考文献条数")
    author: str = Field(default="作者姓名", description="作者姓名")
    advisor: str = Field(default="指导教师（姓名、职称、单位）", description="指导教师")
    degree_type: str = Field(default="学士", description="学位类别")
    major: str = Field(default="专业名称", description="专业")
    school: str = Field(default="XX大学XX学院", description="学院（系）")
    year_month: str = Field(default="", description="留空则自动填当前年月")
    student_id: str = Field(default="", description="学号")
    student_class: str = Field(default="", description="班级")


class GenerateSubmitResponse(BaseModel):
    """提交任务后立即返回。"""

    task_id: str
    message: str = "任务已提交，正在生成中"


class TaskStatusResponse(BaseModel):
    """任务状态查询响应。"""

    task_id: str
    status: Literal["pending", "completed", "failed"]
    message: str = ""
    file_key: str = Field(default="", description="七牛云文件 key，生成完成后填充")
    figure_count: int = Field(default=0, ge=0)
    mermaid_count: int = Field(default=0, ge=0)
    chart_count: int = Field(default=0, ge=0)
    ai_image_count: int = Field(default=0, ge=0)
    fallback_count: int = Field(default=0, ge=0)
    fulltext_char_count: int = Field(default=0, ge=0)
    truncation_warning: bool = False
    docx_path: str = Field(default="")


class PaperOutlineCreateRequest(BaseModel):
    """创建可下单的大纲记录。"""

    title: str = Field(..., min_length=2, max_length=200)
    form_params: dict[str, Any] = Field(default_factory=dict)
    about_msg: str = ""
    three_level: bool = False
    literatures: list[str] = Field(default_factory=list)
    gallery_resources: list[str] = Field(default_factory=list)


class PaperOrderCreateRequest(BaseModel):
    """基于大纲记录创建论文订单。"""

    record_id: int
    outline: list[dict[str, Any]]
    template_id: int | None = None
    selftemp: int | None = None
    service_ids: list[int] = Field(default_factory=list)
    agent_id: int | None = None


class PaperOrderPayRequest(BaseModel):
    """论文订单积分支付请求。"""

    order_sn: str


class PaperPriceResponse(BaseModel):
    """论文生成价格与用户积分。"""

    points: int
    amount: float
    user_points: int


class PaperOutlineRecordResponse(BaseModel):
    """生成大纲并保存记录后的响应。"""

    record_id: int
    outline: list[OutlineChapter]
    abstract: str = ""
    keywords: str = ""


class PaperOrderCreateResponse(BaseModel):
    """创建论文订单后的支付信息。"""

    order_sn: str
    amount: float
    points: int
    is_paid: int = 0


class PaperOrderPayResponse(BaseModel):
    """论文订单积分支付结果。"""

    order_sn: str
    is_paid: int = 1
    points: int
    cost_points: int


class PaperOrderStatusResponse(BaseModel):
    """论文订单状态查询结果。"""

    order_sn: str
    status: str
    is_paid: int
    has_file: int
    task_id: str | None = None
    file_key: str | None = None
    download_url: str | None = None
    error_msg: str | None = None


class PaperOrderDownloadUrlResponse(BaseModel):
    """论文订单下载链接。"""

    order_sn: str
    download_url: str
    file_key: str | None = None


class NormalizedPaperOrder(BaseModel):
    """论文订单归一化后的生成参数。"""

    title: str
    outline_json: list[OutlineChapter]
    target_word_count: int
    codetype: str
    wxquote: str
    language: str
    wxnum: int


class MermaidFigure(BaseModel):
    """Mermaid 技术图占位符。"""

    caption: str = Field(..., min_length=1)
    render_method: Literal["mermaid"]
    mermaid_code: str = Field(..., min_length=1)


class AiImageFigure(BaseModel):
    """AI 生图占位符。"""

    caption: str = Field(..., min_length=1)
    render_method: Literal["ai_image"]
    description: str = Field(..., min_length=1)
    style: str = "concept_illustration"
    aspect_ratio: str = "16:9"


class ChartSeries(BaseModel):
    """标准图表数据序列。"""

    name: str = Field(..., min_length=1)
    data: list[float] = Field(..., min_length=1)


class ChartFigure(BaseModel):
    """标准图表占位符。"""

    caption: str = Field(..., min_length=1)
    render_method: Literal["chart"]
    chart_type: Literal["line", "bar", "pie"]
    title: str = Field(..., min_length=1)
    x_label: str = ""
    y_label: str = ""
    categories: list[str] = Field(..., min_length=1)
    series: list[ChartSeries] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_chart_shape(self) -> "ChartFigure":
        category_count = len(self.categories)
        if self.chart_type in {"line", "bar"}:
            for item in self.series:
                if len(item.data) != category_count:
                    raise ValueError("line/bar 图的 series.data 长度必须与 categories 一致")
        elif self.chart_type == "pie":
            if len(self.series[0].data) != category_count:
                raise ValueError("pie 图的第一组 series.data 长度必须与 categories 一致")
        return self


class FallbackFigure(BaseModel):
    """解析或校验失败时的降级占位符。"""

    caption: str = "（占位图）"
    render_method: Literal["fallback"] = "fallback"
    error: str = ""


def validate_figure_payload(raw: dict[str, Any], index: int) -> dict[str, Any]:
    """校验单个占位符；失败时返回 fallback，确保索引不丢失。"""

    method = raw.get("render_method", "")
    try:
        if method == "mermaid":
            result = MermaidFigure(**raw).model_dump()
        elif method == "chart":
            result = ChartFigure(**raw).model_dump()
        elif method == "ai_image":
            result = AiImageFigure(**raw).model_dump()
        else:
            raise ValueError(f"未知的 render_method: {method!r}")
    except (ValidationError, ValueError, TypeError) as exc:
        logger.warning("占位符 #%d 校验失败，使用 fallback: %s", index, exc)
        result = FallbackFigure(error=str(exc)).model_dump()

    result["index"] = index
    return result


def extract_figure_placeholders(text: str) -> list[dict[str, Any]]:
    """提取并校验全文中的全部图片占位符。"""

    placeholders: list[dict[str, Any]] = []
    matches = FIGURE_BLOCK_PATTERN.findall(text)

    for index, match in enumerate(matches):
        try:
            # 防御性剥离：LLM 偶尔会在 JSON 外包裹 Markdown 代码围栏
            clean_text = match.strip()
            clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text, flags=re.IGNORECASE)
            clean_text = re.sub(r"\s*```$", "", clean_text).strip()
            raw = json.loads(clean_text)
        except json.JSONDecodeError as exc:
            logger.warning("占位符 #%d JSON 解析失败: %s", index, exc)
            placeholders.append(FallbackFigure(error=f"JSON 解析失败: {exc}").model_dump() | {"index": index})
            continue

        placeholders.append(validate_figure_payload(raw, index=index))

    return placeholders


def split_by_render_method(
    placeholders: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """按渲染方式分组，返回 (mermaid, chart, ai_image, fallback)。"""

    mermaid = [item for item in placeholders if item.get("render_method") == "mermaid"]
    chart = [item for item in placeholders if item.get("render_method") == "chart"]
    ai_image = [item for item in placeholders if item.get("render_method") == "ai_image"]
    fallback = [item for item in placeholders if item.get("render_method") == "fallback"]
    return mermaid, chart, ai_image, fallback


__all__ = [
    "AiImageFigure",
    "ChartFigure",
    "ChartSeries",
    "FallbackFigure",
    "FIGURE_BLOCK_PATTERN",
    "GenerateRequest",
    "GenerateSubmitResponse",
    "MermaidFigure",
    "OutlineChapter",
    "OutlinePayload",
    "OutlineRequest",
    "OutlineResponse",
    "OutlineSection",
    "NormalizedPaperOrder",
    "PaperOrderCreateResponse",
    "PaperOrderCreateRequest",
    "PaperOrderDownloadUrlResponse",
    "PaperOrderPayRequest",
    "PaperOrderPayResponse",
    "PaperOrderStatusResponse",
    "PaperOutlineCreateRequest",
    "PaperOutlineRecordResponse",
    "PaperPriceResponse",
    "TaskStatusResponse",
    "extract_figure_placeholders",
    "split_by_render_method",
    "validate_figure_payload",
]
