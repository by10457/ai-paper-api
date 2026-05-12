import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from tortoise.expressions import F

from core.config import settings
from models.paper import PaperOrder, PaperOutlineRecord
from models.user import User
from schemas.thesis import (
    NormalizedPaperOrder,
    OutlineChapter,
    OutlineSection,
    PaperOrderCreateRequest,
    PaperOutlineCreateRequest,
)


class PaperOrderService:
    """论文订单与大纲记录的数据服务。"""

    @staticmethod
    async def create_outline_record(
        user: User,
        req: PaperOutlineCreateRequest,
        outline_data: dict[str, Any],
    ) -> PaperOutlineRecord:
        """保存用户生成的大纲，后续订单从该记录创建。"""

        return await PaperOutlineRecord.create(
            user=user,
            title=req.title,
            request_payload=req.model_dump(),
            outline_data=outline_data,
        )

    @staticmethod
    async def create_order(user: User, req: PaperOrderCreateRequest) -> PaperOrder:
        """创建论文订单，订单创建阶段不扣减积分。"""

        outline_record = await PaperOutlineRecord.filter(id=req.record_id, user=user).first()
        if outline_record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="大纲记录不存在")

        order = await PaperOrder.create(
            user=user,
            outline_record=outline_record,
            order_sn=PaperOrderService._generate_order_sn(),
            title=outline_record.title,
            outline_json=req.outline,
            config_form=outline_record.request_payload,
            template_id=req.template_id,
            selftemp=req.selftemp,
            service_ids=req.service_ids,
            cost_points=settings.PAPER_GENERATE_POINTS,
            status="created",
        )
        return order

    @staticmethod
    async def get_order(user: User, order_sn: str) -> PaperOrder:
        """查询当前用户的论文订单，不存在时返回 404。"""

        order = await PaperOrder.filter(order_sn=order_sn, user=user).first()
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="论文订单不存在")
        return order

    @staticmethod
    async def pay_order(user: User, order: PaperOrder) -> bool:
        """扣减积分并标记订单已支付，返回是否需要启动生成。"""

        if order.status not in {"created", "failed"}:
            return False

        updated = await User.filter(id=user.id, points__gte=order.cost_points).update(
            points=F("points") - order.cost_points,
        )
        if updated == 0:
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="积分余额不足")

        now = datetime.now(UTC)
        order.status = "paid"
        order.paid_points = order.cost_points
        order.paid_at = now
        order.last_error = ""
        await order.save(update_fields=["status", "paid_points", "paid_at", "last_error", "updated_at"])
        await user.refresh_from_db()
        return True

    @staticmethod
    async def mark_generating(order: PaperOrder, task_id: str) -> None:
        """记录订单对应的后台生成任务。"""

        now = datetime.now(UTC)
        order.status = "generating"
        order.task_id = task_id
        order.started_at = now
        order.last_error = ""
        await order.save(update_fields=["status", "task_id", "started_at", "last_error", "updated_at"])

    @staticmethod
    async def mark_from_task_status(order: PaperOrder, data: dict[str, Any] | None) -> PaperOrder:
        """根据后台任务状态回写订单状态。"""

        if not data:
            return order

        task_status = str(data.get("status", ""))
        if task_status == "completed":
            order.status = "completed"
            order.file_key = str(data.get("file_key") or "")
            order.download_url = str(data.get("download_url") or "")
            order.completed_at = datetime.now(UTC)
            order.last_error = ""
            await order.save(
                update_fields=[
                    "status",
                    "file_key",
                    "download_url",
                    "completed_at",
                    "last_error",
                    "updated_at",
                ]
            )
        elif task_status == "failed":
            order.status = "failed"
            order.last_error = str(data.get("message") or "生成失败")[:500]
            await order.save(update_fields=["status", "last_error", "updated_at"])
        return order

    @staticmethod
    def normalize_generate_input(order: PaperOrder) -> NormalizedPaperOrder:
        """把订单快照转换成论文生成服务参数。"""

        config = order.config_form if isinstance(order.config_form, dict) else {}
        return NormalizedPaperOrder(
            title=order.title,
            outline_json=PaperOrderService._normalize_outline(order.outline_json),
            target_word_count=PaperOrderService._to_int(config.get("lengthnum"), 8000),
            codetype=PaperOrderService._to_text(config.get("codetype"), "否"),
            wxquote=PaperOrderService._to_text(config.get("wxquote"), "标注"),
            language=PaperOrderService._to_text(config.get("language"), "否"),
            wxnum=PaperOrderService._to_int(config.get("wxnum"), 25),
        )

    @staticmethod
    def _normalize_outline(raw_outline: Any) -> list[OutlineChapter]:
        chapters: list[OutlineChapter] = []
        if not isinstance(raw_outline, list):
            return chapters
        for chapter_item in raw_outline:
            if not isinstance(chapter_item, dict):
                continue
            sections: list[OutlineSection] = []
            raw_sections = chapter_item.get("sections")
            if isinstance(raw_sections, list):
                for section_item in raw_sections:
                    if not isinstance(section_item, dict):
                        continue
                    name = section_item.get("name") or section_item.get("section") or ""
                    if not str(name).strip():
                        continue
                    sections.append(
                        OutlineSection(
                            name=str(name).strip(),
                            abstract=str(section_item.get("abstract") or ""),
                        )
                    )
            chapter = str(chapter_item.get("chapter") or "").strip()
            if chapter and sections:
                chapters.append(OutlineChapter(chapter=chapter, sections=sections))
        return chapters

    @staticmethod
    def _generate_order_sn() -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"AP{timestamp}{secrets.token_hex(4).upper()}"

    @staticmethod
    def _to_text(value: Any, default: str) -> str:
        text = str(value).strip() if value is not None else ""
        return text or default

    @staticmethod
    def _to_int(value: Any, default: int) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return default
