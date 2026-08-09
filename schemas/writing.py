"""开题报告、文献综述和任务书接口数据结构。"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

WritingDocumentType = Literal["proposal_report", "literature_review", "task_book"]
WritingTaskStatus = Literal["queued", "generating", "completed", "failed"]


class StudentProfile(BaseModel):
    """文档封面和任务书中的学生信息，缺失字段必须保持空白。"""

    school: str | None = Field(default=None, max_length=200)
    college: str | None = Field(default=None, max_length=200)
    name: str | None = Field(default=None, max_length=100)
    student_no: str | None = Field(default=None, max_length=100)
    class_name: str | None = Field(default=None, max_length=100)
    major: str | None = Field(default=None, max_length=200)
    internal_advisor: str | None = Field(default=None, max_length=100)
    enterprise_advisor: str | None = Field(default=None, max_length=100)
    year_month: str | None = Field(default=None, max_length=20)


class ResearchContext(BaseModel):
    """生成内容所需的研究和技术补充信息。"""

    direction: str | None = Field(default=None, max_length=1000)
    topic_category: str | None = Field(default=None, max_length=50)
    technology_stack: list[str] = Field(default_factory=list, max_length=20)
    core_features: list[str] = Field(default_factory=list, max_length=30)
    additional_requirements: str | None = Field(default=None, max_length=3000)


class ScheduleOptions(BaseModel):
    """实际日期或相对周次生成配置。"""

    start_date: date | None = None
    end_date: date | None = None
    total_weeks: int | None = Field(default=None, ge=5, le=52)

    @model_validator(mode="after")
    def validate_date_range(self) -> ScheduleOptions:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("开始日期不能晚于结束日期")
        return self


class ReferenceOptions(BaseModel):
    """真实参考文献检索配置。"""

    target_count: int
    # 三类学术材料要求中英文文献均达到配额，保留字段仅兼容旧客户端。
    include_foreign: Literal[True] = True


class BaseWritingRequest(BaseModel):
    """三类学术材料通用请求。"""

    title: str = Field(min_length=2, max_length=200)
    student_profile: StudentProfile = Field(default_factory=StudentProfile)
    research_context: ResearchContext = Field(default_factory=ResearchContext)
    schedule_options: ScheduleOptions = Field(default_factory=ScheduleOptions)
    callback_url: str = Field(default="", max_length=1024)
    callback_secret: str = Field(default="", max_length=255)


class ProposalReportRequest(BaseWritingRequest):
    """开题报告生成请求。"""

    target_word_count: int = Field(default=4000, ge=2500, le=12000)
    reference_options: ReferenceOptions = Field(
        default_factory=lambda: ReferenceOptions(target_count=15, include_foreign=True)
    )

    @model_validator(mode="after")
    def validate_reference_count(self) -> ProposalReportRequest:
        if not 8 <= self.reference_options.target_count <= 40:
            raise ValueError("开题报告参考文献数量需在8-40之间")
        return self


class LiteratureReviewRequest(BaseWritingRequest):
    """文献综述生成请求。"""

    target_word_count: int = Field(default=6000, ge=3500, le=20000)
    reference_options: ReferenceOptions = Field(
        default_factory=lambda: ReferenceOptions(target_count=20, include_foreign=True)
    )

    @model_validator(mode="after")
    def validate_reference_count(self) -> LiteratureReviewRequest:
        if not 12 <= self.reference_options.target_count <= 60:
            raise ValueError("文献综述参考文献数量需在12-60之间")
        return self


TopicType = Literal["产品设计类", "工艺设计类", "方案设计类", "作品设计类", "作品展示类", "其他"]


class TaskBookRequest(BaseWritingRequest):
    """毕业设计任务书生成请求。"""

    topic_type: TopicType = "其他"


class WritingSubmitResponse(BaseModel):
    task_id: str
    order_sn: str
    document_type: WritingDocumentType
    status: Literal["queued"] = "queued"
    charged_points: int


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


class WritingProductResponse(BaseModel):
    document_type: WritingDocumentType
    name: str
    points: int
    default_word_count: int | None = None
    default_reference_count: int | None = None
    minimum_reference_count: int | None = None


class WritingProductsResponse(BaseModel):
    user_points: int
    products: list[WritingProductResponse]


class WritingTaskResponse(BaseModel):
    task_id: str
    order_sn: str
    document_type: WritingDocumentType
    title: str
    status: WritingTaskStatus
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


class WritingOrderListItem(BaseModel):
    order_sn: str
    task_id: str | None = None
    document_type: WritingDocumentType
    title: str
    status: str
    cost_points: int
    refunded_points: int
    created_at: str
    completed_at: str | None = None


class WritingOrderDetail(WritingOrderListItem):
    request: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    stage: str | None = None
    progress: int = 0
    error_message: str | None = None
    download_url: str | None = None
