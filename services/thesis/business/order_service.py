import secrets
from typing import Any

from fastapi import HTTPException, status
from tortoise import timezone
from tortoise.transactions import in_transaction

from core.config import settings
from models.admin import PointLedger
from models.paper import PaperDirectTask, PaperOrder, PaperOutlineRecord
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
    async def create_order(
        user: User,
        req: PaperOrderCreateRequest,
        idempotency_key: str | None = None,
    ) -> PaperOrder:
        """创建论文订单，订单创建阶段不扣减积分。"""

        if idempotency_key:
            async with in_transaction() as conn:
                await User.filter(id=user.id).using_db(conn).select_for_update().first()
                existing_order = await PaperOrder.filter(
                    user_id=user.id,
                    idempotency_key=idempotency_key,
                ).using_db(conn).first()
                if existing_order is not None:
                    return existing_order

                outline_record = await PaperOutlineRecord.filter(id=req.record_id, user=user).using_db(conn).first()
                if outline_record is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="大纲记录不存在")
                return await PaperOrderService._create_order_record(user, req, outline_record, idempotency_key, conn)

        outline_record = await PaperOutlineRecord.filter(id=req.record_id, user=user).first()
        if outline_record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="大纲记录不存在")

        return await PaperOrderService._create_order_record(user, req, outline_record, None, None)

    @staticmethod
    async def _create_order_record(
        user: User,
        req: PaperOrderCreateRequest,
        outline_record: PaperOutlineRecord,
        idempotency_key: str | None,
        conn: Any | None,
    ) -> PaperOrder:
        """写入论文订单记录。"""

        data: dict[str, Any] = {
            "user": user,
            "outline_record": outline_record,
            "order_sn": PaperOrderService._generate_order_sn(),
            "idempotency_key": idempotency_key,
            "title": outline_record.title,
            "outline_json": req.outline,
            "config_form": outline_record.request_payload,
            "template_id": req.template_id,
            "selftemp": req.selftemp,
            "service_ids": req.service_ids,
            "cost_points": settings.PAPER_GENERATE_POINTS,
            "status": "created",
        }
        if conn is None:
            return await PaperOrder.create(**data)
        return await PaperOrder.create(using_db=conn, **data)

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

        async with in_transaction() as conn:
            locked_order = (
                await PaperOrder.filter(id=order.id, user_id=user.id)
                .using_db(conn)
                .select_for_update()
                .first()
            )
            if locked_order is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="论文订单不存在")

            if locked_order.status == "paid":
                return True
            if locked_order.status not in {"created", "failed"}:
                return False

            if locked_order.status == "failed" and locked_order.paid_points > locked_order.refunded_points:
                now = timezone.now()
                locked_order.status = "paid"
                locked_order.last_error = ""
                locked_order.paid_at = locked_order.paid_at or now
                await locked_order.save(
                    using_db=conn,
                    update_fields=["status", "paid_at", "last_error", "updated_at"],
                )
                return True

            locked_user = await User.filter(id=user.id).using_db(conn).select_for_update().first()
            if locked_user is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
            if locked_user.points < locked_order.cost_points:
                raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="积分余额不足")

            now = timezone.now()
            locked_user.points -= locked_order.cost_points
            await locked_user.save(using_db=conn, update_fields=["points", "updated_at"])

            locked_order.status = "paid"
            locked_order.paid_points = locked_order.cost_points
            locked_order.paid_at = now
            locked_order.last_error = ""
            await locked_order.save(
                using_db=conn,
                update_fields=["status", "paid_points", "paid_at", "last_error", "updated_at"],
            )
            await PointLedger.create(
                using_db=conn,
                user=locked_user,
                order=locked_order,
                change_type="paper_deduct",
                delta=-locked_order.cost_points,
                balance_after=locked_user.points,
                reason=f"论文订单 {locked_order.order_sn} 积分支付",
            )

        await user.refresh_from_db()
        return True

    @staticmethod
    async def create_direct_generate_task(
        user: User,
        *,
        task_id: str,
        title: str,
        request_payload: dict[str, Any],
        idempotency_key: str | None,
    ) -> tuple[PaperDirectTask, bool]:
        """创建兼容式生成任务并扣积分，返回任务和是否需要启动生成。"""

        async with in_transaction() as conn:
            locked_user = await User.filter(id=user.id).using_db(conn).select_for_update().first()
            if locked_user is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

            if idempotency_key:
                existing_task = await PaperDirectTask.filter(
                    user_id=user.id,
                    idempotency_key=idempotency_key,
                ).using_db(conn).select_for_update().first()
                if existing_task is not None:
                    return existing_task, existing_task.status == "paid"

            if locked_user.points < settings.PAPER_GENERATE_POINTS:
                raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="积分余额不足")

            locked_user.points -= settings.PAPER_GENERATE_POINTS
            await locked_user.save(using_db=conn, update_fields=["points", "updated_at"])
            direct_task = await PaperDirectTask.create(
                using_db=conn,
                user=locked_user,
                idempotency_key=idempotency_key,
                task_id=task_id,
                title=title,
                request_payload=request_payload,
                cost_points=settings.PAPER_GENERATE_POINTS,
                refunded_points=0,
                status="paid",
            )
            await PointLedger.create(
                using_db=conn,
                user=locked_user,
                change_type="paper_api_deduct",
                delta=-settings.PAPER_GENERATE_POINTS,
                balance_after=locked_user.points,
                reason=f"直接生成论文 {task_id} 积分支付",
                metadata={"task_id": task_id, "title": title, "idempotency_key": idempotency_key},
            )

        await user.refresh_from_db()
        return direct_task, True

    @staticmethod
    async def mark_generating_if_paid(order_id: int, task_id: str) -> PaperOrder | None:
        """把已支付订单切换到生成中；已被其它任务启动时返回 None。"""

        async with in_transaction() as conn:
            order = await PaperOrder.filter(id=order_id).using_db(conn).select_for_update().first()
            if order is None or order.status != "paid":
                return None

            now = timezone.now()
            order.status = "generating"
            order.task_id = task_id
            order.started_at = now
            order.last_error = ""
            await order.save(
                using_db=conn,
                update_fields=["status", "task_id", "started_at", "last_error", "updated_at"],
            )
            return order

    @staticmethod
    async def mark_direct_task_generating_if_paid(direct_task_id: int) -> PaperDirectTask | None:
        """把兼容式已扣费任务切换到生成中；已被其它任务启动时返回 None。"""

        async with in_transaction() as conn:
            direct_task = await PaperDirectTask.filter(id=direct_task_id).using_db(conn).select_for_update().first()
            if direct_task is None or direct_task.status != "paid":
                return None

            direct_task.status = "generating"
            direct_task.started_at = timezone.now()
            direct_task.last_error = ""
            await direct_task.save(
                using_db=conn,
                update_fields=["status", "started_at", "last_error", "updated_at"],
            )
            return direct_task

    @staticmethod
    async def mark_direct_task_from_status(direct_task_id: int, data: dict[str, Any] | None) -> None:
        """根据生成任务状态回写兼容式任务记录。"""

        direct_task = await PaperDirectTask.filter(id=direct_task_id).first()
        if direct_task is None or not data:
            return

        task_status = str(data.get("status", ""))
        if task_status == "completed":
            direct_task.status = "completed"
            direct_task.file_key = str(data.get("file_key") or "")
            direct_task.completed_at = timezone.now()
            direct_task.last_error = ""
            await direct_task.save(update_fields=["status", "file_key", "completed_at", "last_error", "updated_at"])
        elif task_status == "failed":
            if str(data.get("error_type") or "") in {"provider_quota", "provider_config"}:
                await PaperOrderService.refund_failed_direct_task_points(
                    direct_task.id,
                    str(data.get("message") or "生成服务暂时不可用，本次扣除积分已退回，请稍后重试或联系管理员"),
                )
                return
            direct_task.status = "failed"
            direct_task.last_error = str(data.get("message") or "生成失败")[:500]
            await direct_task.save(update_fields=["status", "last_error", "updated_at"])

    @staticmethod
    async def refund_failed_direct_task_points(direct_task_id: int, reason: str) -> None:
        """供应商额度不足等平台侧失败时，退回兼容式任务扣费。"""

        async with in_transaction() as conn:
            direct_task = (
                await PaperDirectTask.filter(id=direct_task_id)
                .using_db(conn)
                .select_for_update()
                .first()
            )
            if direct_task is None:
                return

            refundable = direct_task.cost_points - direct_task.refunded_points
            user = await User.filter(id=direct_task.user_id).using_db(conn).select_for_update().first()
            if user is None:
                return

            if refundable > 0:
                user.points += refundable
                await user.save(using_db=conn, update_fields=["points", "updated_at"])
                direct_task.refunded_points += refundable
                await PointLedger.create(
                    using_db=conn,
                    user=user,
                    change_type="paper_api_refund",
                    delta=refundable,
                    balance_after=user.points,
                    reason=reason,
                    metadata={"task_id": direct_task.task_id, "reason": "provider_quota"},
                )

            direct_task.status = "failed"
            direct_task.last_error = reason[:500]
            await direct_task.save(
                using_db=conn,
                update_fields=["status", "refunded_points", "last_error", "updated_at"],
            )

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
            order.completed_at = timezone.now()
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
            if str(data.get("error_type") or "") in {"provider_quota", "provider_config"}:
                return await PaperOrderService.refund_failed_order_points(
                    order.id,
                    str(data.get("message") or "生成服务暂时不可用，本次扣除积分已退回，请稍后重试或联系管理员"),
                )
            order.status = "failed"
            order.last_error = str(data.get("message") or "生成失败")[:500]
            await order.save(update_fields=["status", "last_error", "updated_at"])
        return order

    @staticmethod
    async def refund_failed_order_points(order_id: int, reason: str) -> PaperOrder:
        """供应商额度不足等平台侧失败时，退回订单扣费。"""

        async with in_transaction() as conn:
            order = await PaperOrder.filter(id=order_id).using_db(conn).select_for_update().first()
            if order is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="论文订单不存在")

            refundable = order.paid_points - order.refunded_points
            user = await User.filter(id=order.user_id).using_db(conn).select_for_update().first()
            if user is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

            if refundable > 0:
                user.points += refundable
                await user.save(using_db=conn, update_fields=["points", "updated_at"])
                order.refunded_points += refundable
                order.refunded_at = timezone.now()
                await PointLedger.create(
                    using_db=conn,
                    user=user,
                    order=order,
                    change_type="paper_refund",
                    delta=refundable,
                    balance_after=user.points,
                    reason=reason,
                    metadata={"reason": "provider_quota"},
                )

            order.status = "failed"
            order.last_error = reason[:500]
            await order.save(
                using_db=conn,
                update_fields=["status", "refunded_points", "refunded_at", "last_error", "updated_at"],
            )
            return order

    @staticmethod
    def normalize_generate_input(order: PaperOrder) -> NormalizedPaperOrder:
        """把订单快照转换成论文生成服务参数。"""

        config = order.config_form if isinstance(order.config_form, dict) else {}
        form_params = config.get("form_params")
        if isinstance(form_params, dict):
            config = form_params
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
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
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
