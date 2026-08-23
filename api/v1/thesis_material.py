"""开题报告、文献综述和任务书统一为论文材料接口。"""

from fastapi import APIRouter, Depends, Header, HTTPException, Path
from fastapi.responses import FileResponse, StreamingResponse

from api.dependencies.api_token import get_api_token_or_jwt_user
from models.user import User
from schemas.common import PageResponse, Response
from schemas.thesis_material import (
    LiteratureReviewRequest,
    ProposalReportRequest,
    TaskBookRequest,
    ThesisMaterialOrderDetail,
    ThesisMaterialOrderListItem,
    ThesisMaterialProductsResponse,
    ThesisMaterialSubmitResponse,
    ThesisMaterialTaskResponse,
)
from services.thesis.generation.sse import stream_order_status_events
from services.thesis_material import workflow

router = APIRouter(tags=["论文材料生成"])
MAX_IDEMPOTENCY_KEY_LENGTH = 128


@router.get("/products", response_model=Response[ThesisMaterialProductsResponse], summary="查询论文材料产品和价格")
async def products(current_user: User = Depends(get_api_token_or_jwt_user)) -> Response[ThesisMaterialProductsResponse]:
    return Response.ok(workflow.list_products(current_user))


@router.post("/proposal-reports", response_model=Response[ThesisMaterialSubmitResponse], summary="生成开题报告")
async def submit_proposal_report(
    request: ProposalReportRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_api_token_or_jwt_user),
) -> Response[ThesisMaterialSubmitResponse]:
    return Response.ok(
        await workflow.submit_request(current_user, "proposal_report", request, _idempotency_key(idempotency_key))
    )


@router.post("/literature-reviews", response_model=Response[ThesisMaterialSubmitResponse], summary="生成文献综述")
async def submit_literature_review(
    request: LiteratureReviewRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_api_token_or_jwt_user),
) -> Response[ThesisMaterialSubmitResponse]:
    return Response.ok(
        await workflow.submit_request(current_user, "literature_review", request, _idempotency_key(idempotency_key))
    )


@router.post("/task-books", response_model=Response[ThesisMaterialSubmitResponse], summary="生成任务书")
async def submit_task_book(
    request: TaskBookRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_api_token_or_jwt_user),
) -> Response[ThesisMaterialSubmitResponse]:
    return Response.ok(
        await workflow.submit_request(current_user, "task_book", request, _idempotency_key(idempotency_key))
    )


@router.get("/tasks/{task_id}", response_model=Response[ThesisMaterialTaskResponse], summary="查询论文材料任务")
async def get_task(
    task_id: str = Path(pattern=r"^[a-zA-Z0-9_-]+$"),
    current_user: User = Depends(get_api_token_or_jwt_user),
) -> Response[ThesisMaterialTaskResponse]:
    return Response.ok(await workflow.get_task(current_user, task_id))


@router.get("/tasks/{task_id}/events", summary="SSE 推送论文材料进度")
async def task_events(
    task_id: str = Path(pattern=r"^[a-zA-Z0-9_-]+$"),
    current_user: User = Depends(get_api_token_or_jwt_user),
) -> StreamingResponse:
    return StreamingResponse(
        stream_order_status_events(current_user, task_id, workflow.get_task),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/tasks/{task_id}/download", summary="下载论文材料 DOCX")
async def download_task(
    task_id: str = Path(pattern=r"^[a-zA-Z0-9_-]+$"),
    current_user: User = Depends(get_api_token_or_jwt_user),
) -> FileResponse:
    path = await workflow.get_download_path(current_user, task_id)
    return FileResponse(
        path=str(path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=path.name,
    )


@router.get("/orders", response_model=Response[PageResponse[ThesisMaterialOrderListItem]], summary="查询论文材料订单")
async def list_orders(
    page: int = 1,
    page_size: int = 10,
    current_user: User = Depends(get_api_token_or_jwt_user),
) -> Response[PageResponse[ThesisMaterialOrderListItem]]:
    return Response.ok(await workflow.list_orders(current_user, page, page_size))


@router.get("/orders/{order_sn}", response_model=Response[ThesisMaterialOrderDetail], summary="查询论文材料订单详情")
async def get_order(
    order_sn: str,
    current_user: User = Depends(get_api_token_or_jwt_user),
) -> Response[ThesisMaterialOrderDetail]:
    return Response.ok(await workflow.get_order(current_user, order_sn))


def _idempotency_key(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    key = value.strip()
    if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise HTTPException(status_code=400, detail="Idempotency-Key不能超过128个字符")
    return key
