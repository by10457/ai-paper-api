"""论文材料订单、任务、扣费、重试与退款服务。"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from fastapi import HTTPException, status
from tortoise import timezone
from tortoise.transactions import in_transaction

from core.config import settings
from models.admin import PointLedger
from models.paper_material import ThesisMaterialGenerationTask, ThesisMaterialOrder
from models.user import User


class ThesisMaterialOrderService:
    """维护三类论文材料共用但与论文隔离的订单生命周期。"""

    @staticmethod
    async def create_paid_task(
        user: User,
        *,
        document_type: str,
        title: str,
        request_payload: dict[str, Any],
        idempotency_key: str | None,
        cost_points: int,
    ) -> tuple[ThesisMaterialGenerationTask, bool]:
        """原子创建订单和任务并扣积分。

        Args:
            user: 当前用户。
            document_type: 论文材料类型。
            title: 文档标题。
            request_payload: 已校验的请求快照。
            idempotency_key: 客户端幂等键。
            cost_points: 产品积分价格。

        Returns:
            生成任务，以及是否需要加入队列。
        """

        async with in_transaction() as conn:
            locked_user = await User.filter(id=user.id).using_db(conn).select_for_update().first()
            if locked_user is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

            if idempotency_key:
                existing_order = (
                    await ThesisMaterialOrder.filter(user_id=user.id, idempotency_key=idempotency_key)
                    .using_db(conn)
                    .select_for_update()
                    .first()
                )
                if existing_order is not None:
                    existing_task = (
                        await ThesisMaterialGenerationTask.filter(order_id=existing_order.id)
                        .using_db(conn)
                        .order_by("-id")
                        .first()
                    )
                    if existing_task is not None:
                        return existing_task, existing_task.status == "paid"

            if locked_user.points < cost_points:
                raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="积分余额不足")

            locked_user.points -= cost_points
            await locked_user.save(using_db=conn, update_fields=["points", "updated_at"])
            task_id = ThesisMaterialOrderService.generate_task_id()
            order = await ThesisMaterialOrder.create(
                using_db=conn,
                user=locked_user,
                order_sn=ThesisMaterialOrderService.generate_order_sn(),
                document_type=document_type,
                idempotency_key=idempotency_key,
                title=title,
                request_payload=request_payload,
                cost_points=cost_points,
                paid_points=cost_points,
                status="paid",
                task_id=task_id,
                callback_url=str(request_payload.get("callback_url") or settings.paper_callback_url or "") or None,
                callback_secret=str(request_payload.get("callback_secret") or settings.paper_callback_secret or "")
                or None,
                paid_at=timezone.now(),
            )
            generation_task = await ThesisMaterialGenerationTask.create(
                using_db=conn,
                user=locked_user,
                order=order,
                idempotency_key=idempotency_key,
                task_id=task_id,
                document_type=document_type,
                title=title,
                status="paid",
                current_stage="queued",
                progress=2,
            )
            await PointLedger.create(
                using_db=conn,
                user=locked_user,
                thesis_material_order=order,
                change_type="thesis_material_deduct",
                delta=-cost_points,
                balance_after=locked_user.points,
                reason=f"论文材料订单 {order.order_sn} 积分支付",
                metadata={"task_id": task_id, "document_type": document_type},
            )

        await user.refresh_from_db()
        return generation_task, True

    @staticmethod
    async def mark_task_generating_if_paid(task_db_id: int) -> ThesisMaterialGenerationTask | None:
        """把到期的已支付任务原子切换到生成中。

        Args:
            task_db_id: 生成任务数据库主键。

        Returns:
            成功抢占的任务；状态不允许执行时返回 None。
        """

        async with in_transaction() as conn:
            task = (
                await ThesisMaterialGenerationTask.filter(id=task_db_id)
                .using_db(conn)
                .select_for_update()
                .first()
            )
            if task is None or task.status != "paid":
                return None
            if task.next_retry_at and task.next_retry_at > timezone.now():
                return None
            order = await ThesisMaterialOrder.filter(id=task.order_id).using_db(conn).select_for_update().first()
            if order is None or order.status not in {"paid", "generating"}:
                return None

            now = timezone.now()
            task.status = "generating"
            task.started_at = now
            task.last_error = ""
            task.next_retry_at = None  # type: ignore[assignment]
            await task.save(
                using_db=conn,
                update_fields=["status", "started_at", "last_error", "next_retry_at", "updated_at"],
            )
            order.status = "generating"
            order.started_at = now
            order.last_error = ""
            order.next_retry_at = None  # type: ignore[assignment]
            await order.save(
                using_db=conn,
                update_fields=["status", "started_at", "last_error", "next_retry_at", "updated_at"],
            )
            return task

    @staticmethod
    async def mark_completed(task_db_id: int, status_data: dict[str, Any]) -> None:
        """把完成状态、文件和结构化结果同步到任务及订单。

        Args:
            task_db_id: 生成任务数据库主键。
            status_data: Redis 中的最终状态快照。
        """

        async with in_transaction() as conn:
            task = (
                await ThesisMaterialGenerationTask.filter(id=task_db_id)
                .using_db(conn)
                .select_for_update()
                .first()
            )
            if task is None:
                return
            order = await ThesisMaterialOrder.filter(id=task.order_id).using_db(conn).select_for_update().first()
            if order is None:
                return

            now = timezone.now()
            provider = str(status_data.get("storage_provider") or "")
            file_key = str(status_data.get("file_key") or "")
            local_file_key = str(status_data.get("local_file_key") or "")
            task.status = "completed"
            task.current_stage = "completed"
            task.progress = 100
            task.storage_provider = provider
            task.file_key = file_key
            task.local_file_key = local_file_key
            raw_result_data = status_data.get("result_data")
            task.result_data = raw_result_data if isinstance(raw_result_data, dict) else {}
            task.completed_at = now
            task.last_error = ""
            await task.save(
                using_db=conn,
                update_fields=[
                    "status",
                    "current_stage",
                    "progress",
                    "storage_provider",
                    "file_key",
                    "local_file_key",
                    "result_data",
                    "completed_at",
                    "last_error",
                    "updated_at",
                ],
            )
            order.status = "completed"
            order.storage_provider = provider
            order.file_key = file_key
            order.local_file_key = local_file_key
            order.download_url = str(status_data.get("download_url") or "")
            order.completed_at = now
            order.last_error = ""
            await order.save(
                using_db=conn,
                update_fields=[
                    "status",
                    "storage_provider",
                    "file_key",
                    "local_file_key",
                    "download_url",
                    "completed_at",
                    "last_error",
                    "updated_at",
                ],
            )

    @staticmethod
    async def handle_failed_task(
        task_db_id: int,
        message: str,
        error_type: str,
    ) -> bool:
        """安排普通错误重试，或在最终失败时幂等退款。

        Args:
            task_db_id: 生成任务数据库主键。
            message: 用户可见失败信息。
            error_type: 失败类型。

        Returns:
            最终失败并已退款时返回 True；已安排重试时返回 False。
        """

        should_retry = False
        retry_delay = settings.PAPER_GENERATION_RETRY_DELAY_SECONDS
        async with in_transaction() as conn:
            task = (
                await ThesisMaterialGenerationTask.filter(id=task_db_id)
                .using_db(conn)
                .select_for_update()
                .first()
            )
            if task is None:
                return True
            order = await ThesisMaterialOrder.filter(id=task.order_id).using_db(conn).select_for_update().first()
            if order is None:
                return True

            can_retry = error_type == "generation_error" and task.retry_count < settings.PAPER_GENERATION_MAX_RETRIES
            if can_retry:
                next_retry_at = timezone.now() + timedelta(seconds=retry_delay)
                task.retry_count += 1
                task.status = "paid"
                task.started_at = None  # type: ignore[assignment]
                task.next_retry_at = next_retry_at
                task.last_error = (
                    f"{message}，将自动重试 {task.retry_count}/{settings.PAPER_GENERATION_MAX_RETRIES}"
                )[:500]
                await task.save(
                    using_db=conn,
                    update_fields=[
                        "retry_count",
                        "status",
                        "started_at",
                        "next_retry_at",
                        "last_error",
                        "updated_at",
                    ],
                )
                order.retry_count = task.retry_count
                order.status = "paid"
                order.started_at = None  # type: ignore[assignment]
                order.next_retry_at = next_retry_at
                order.last_error = task.last_error
                await order.save(
                    using_db=conn,
                    update_fields=[
                        "retry_count",
                        "status",
                        "started_at",
                        "next_retry_at",
                        "last_error",
                        "updated_at",
                    ],
                )
                should_retry = True
            else:
                user = await User.filter(id=order.user_id).using_db(conn).select_for_update().first()
                if user is None:
                    raise RuntimeError("论文材料订单用户不存在")
                refundable = order.paid_points - order.refunded_points
                if refundable > 0:
                    user.points += refundable
                    await user.save(using_db=conn, update_fields=["points", "updated_at"])
                    order.refunded_points += refundable
                    order.refunded_at = timezone.now()
                    await PointLedger.create(
                        using_db=conn,
                        user=user,
                        thesis_material_order=order,
                        change_type="thesis_material_refund",
                        delta=refundable,
                        balance_after=user.points,
                        reason=message,
                        metadata={"reason": error_type, "task_id": task.task_id},
                    )
                task.status = "failed"
                task.current_stage = "failed"
                task.progress = 100
                task.completed_at = timezone.now()
                task.last_error = message[:500]
                await task.save(
                    using_db=conn,
                    update_fields=[
                        "status",
                        "current_stage",
                        "progress",
                        "completed_at",
                        "last_error",
                        "updated_at",
                    ],
                )
                order.status = "failed"
                order.last_error = message[:500]
                await order.save(
                    using_db=conn,
                    update_fields=["status", "refunded_points", "refunded_at", "last_error", "updated_at"],
                )

        if should_retry:
            from services.thesis.generation.paper_queue import enqueue_thesis_material_generation_task

            await enqueue_thesis_material_generation_task(task_db_id, delay_seconds=retry_delay)
            return False
        return True

    @staticmethod
    def generate_order_sn() -> str:
        """生成论文材料订单号。

        Returns:
            带 TM 前缀的唯一订单号。
        """

        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        return f"TM{timestamp}{secrets.token_hex(4).upper()}"

    @staticmethod
    def generate_task_id() -> str:
        """生成对外暴露的短任务 ID。

        Returns:
            十二位十六进制任务 ID。
        """

        return secrets.token_hex(6)


__all__ = ["ThesisMaterialOrderService"]
