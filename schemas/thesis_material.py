"""开题报告、文献综述和任务书接口数据结构。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class ThesisSourceConfig(ReferenceConfig):
    """下游公共论文表单的快照；材料正文篇幅仍以顶层目标为准。"""

    model_config = ConfigDict(extra="forbid")

    target_word_count: int | None = Field(default=None, ge=1)
    aboutmsg: str = Field(default="", max_length=1000)


class BaseThesisMaterialRequest(BaseModel):
    """三类论文材料通用请求。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=200)
    source_outline: list[OutlineChapter] = Field(min_length=1, max_length=20, description="用户确认的论文大纲")
    thesis_config: ThesisSourceConfig = Field(description="大纲阶段的公共配置，文献数量统一继承")
    research_context: ResearchContext = Field(default_factory=ResearchContext)
    callback_url: str = Field(default="", max_length=1024)
    callback_secret: str = Field(default="", max_length=255)


class ProposalReportRequest(BaseThesisMaterialRequest):
    """开题报告生成请求。"""

    target_word_count: int = Field(default=4000, ge=2500, le=12000)


class LiteratureReviewRequest(BaseThesisMaterialRequest):
    """文献综述生成请求。"""

    target_word_count: int = Field(default=6000, ge=3500, le=20000)


TopicType = Literal["产品设计类", "工艺设计类", "方案设计类", "作品设计类", "作品展示类", "其他"]


class TaskBookRequest(BaseThesisMaterialRequest):
    """毕业设计任务书生成请求。"""

    target_word_count: int = Field(default=2000, ge=1000, le=6000)
    topic_type: TopicType = "其他"


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
