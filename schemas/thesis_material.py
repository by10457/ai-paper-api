"""开题报告、文献综述和任务书接口数据结构。"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.thesis import OutlineChapter, ReferenceConfig

ThesisMaterialDocumentType = Literal["proposal_report", "literature_review", "task_book"]
ThesisMaterialTaskStatus = Literal["queued", "generating", "completed", "failed"]


class ResearchContext(BaseModel):
    """生成内容所需的研究和技术补充信息。"""

    model_config = ConfigDict(extra="forbid")

    direction: str | None = Field(default=None, max_length=1000)
    topic_category: str | None = Field(default=None, max_length=50)
    topic_source: str | None = Field(default=None, max_length=100)
    technology_stack: list[str] = Field(default_factory=list, max_length=20)
    core_features: list[str] = Field(default_factory=list, max_length=30)
    additional_requirements: str | None = Field(default=None, max_length=3000)


class ScheduleOptions(BaseModel):
    """实际日期或相对周次生成配置。"""

    model_config = ConfigDict(extra="forbid")

    start_date: date | None = None
    end_date: date | None = None
    total_weeks: int | None = Field(default=None, ge=5, le=52)

    @model_validator(mode="after")
    def validate_date_range(self) -> ScheduleOptions:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("开始日期不能晚于结束日期")
        return self


class ReferenceOptions(ReferenceConfig):
    """真实参考文献检索配置。"""


class ThesisSourceConfig(BaseModel):
    """下游公共论文表单的快照；材料正文篇幅仍以顶层目标为准。"""

    model_config = ConfigDict(extra="forbid")

    target_word_count: int | None = Field(default=None, ge=1)
    three_level: bool = False
    aboutmsg: str = Field(default="", max_length=1000)


class BaseThesisMaterialRequest(BaseModel):
    """三类论文材料通用请求。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=200)
    source_outline: list[OutlineChapter] | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description="用户确认的论文大纲；旧版调用方可省略",
    )
    thesis_config: ThesisSourceConfig | None = Field(
        default=None,
        description="公共论文配置快照；不覆盖材料专用的目标字数和文献配置",
    )
    research_context: ResearchContext = Field(default_factory=ResearchContext)
    schedule_options: ScheduleOptions = Field(default_factory=ScheduleOptions)
    callback_url: str = Field(default="", max_length=1024)
    callback_secret: str = Field(default="", max_length=255)


class ProposalReportRequest(BaseThesisMaterialRequest):
    """开题报告生成请求。"""

    target_word_count: int = Field(default=4000, ge=2500, le=12000)
    reference_options: ReferenceOptions = Field(
        default_factory=lambda: ReferenceOptions(chinese_reference_count=10, english_reference_count=5)
    )

    @model_validator(mode="after")
    def validate_reference_count(self) -> ProposalReportRequest:
        if not 8 <= self.reference_options.chinese_reference_count + self.reference_options.english_reference_count <= 40:
            raise ValueError("开题报告参考文献数量需在8-40之间")
        return self


class LiteratureReviewRequest(BaseThesisMaterialRequest):
    """文献综述生成请求。"""

    target_word_count: int = Field(default=6000, ge=3500, le=20000)
    reference_options: ReferenceOptions = Field(
        default_factory=lambda: ReferenceOptions(chinese_reference_count=15, english_reference_count=5)
    )

    @model_validator(mode="after")
    def validate_reference_count(self) -> LiteratureReviewRequest:
        if not 12 <= self.reference_options.chinese_reference_count + self.reference_options.english_reference_count <= 60:
            raise ValueError("文献综述参考文献数量需在12-60之间")
        return self


TopicType = Literal["产品设计类", "工艺设计类", "方案设计类", "作品设计类", "作品展示类", "其他"]


class TaskBookRequest(BaseThesisMaterialRequest):
    """毕业设计任务书生成请求。"""

    topic_type: TopicType = "其他"
    reference_options: ReferenceOptions = Field(
        default_factory=lambda: ReferenceOptions(chinese_reference_count=10, english_reference_count=0)
    )

    @model_validator(mode="after")
    def validate_reference_count(self) -> TaskBookRequest:
        if not 5 <= self.reference_options.chinese_reference_count + self.reference_options.english_reference_count <= 30:
            raise ValueError("任务书参考资料数量需在5-30之间")
        return self


class ThesisMaterialSubmitResponse(BaseModel):
    task_id: str
    order_sn: str
    document_type: ThesisMaterialDocumentType
    status: Literal["queued"] = "queued"
    charged_points: int
    missing_profile_fields: list[str] = Field(
        default_factory=list,
        description="文档中将显示待补充提示的个人信息字段",
    )


class ReferenceRecord(BaseModel):
    index: int
    title: str
    authors: list[str] = Field(default_factory=list)
    year: str = ""
    document_type: str = "J"
    source: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    language: Literal["zh", "en"] = "zh"
    provider: str = ""
    source_url: str = ""
    formatted: str = ""


class ThesisMaterialProductResponse(BaseModel):
    document_type: ThesisMaterialDocumentType
    name: str
    points: int
    default_word_count: int | None = None
    default_reference_count: int | None = None
    minimum_reference_count: int | None = None


class ThesisMaterialProductsResponse(BaseModel):
    user_points: int
    products: list[ThesisMaterialProductResponse]


class ThesisMaterialTaskResponse(BaseModel):
    task_id: str
    order_sn: str
    document_type: ThesisMaterialDocumentType
    title: str
    status: ThesisMaterialTaskStatus
    stage: str = ""
    progress: int = Field(default=0, ge=0, le=100)
    message: str = ""
    charged_points: int = 0
    refunded_points: int = 0
    request: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    download_url: str | None = None
    created_at: str
    completed_at: str | None = None


class ThesisMaterialOrderListItem(BaseModel):
    order_sn: str
    task_id: str | None = None
    document_type: ThesisMaterialDocumentType
    title: str
    status: str
    cost_points: int
    refunded_points: int
    created_at: str
    completed_at: str | None = None


class ThesisMaterialOrderDetail(ThesisMaterialOrderListItem):
    request: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    stage: str | None = None
    progress: int = 0
    error_message: str | None = None
    download_url: str | None = None
