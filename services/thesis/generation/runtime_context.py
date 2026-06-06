"""论文生成运行上下文。

生成链路中的内容服务、图片服务和大模型客户端都通过这里读取当前用户、
订单、任务和阶段信息，避免在每个函数签名里层层传递审计字段。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class GenerationRuntimeContext:
    """当前论文生成调用链的审计上下文。"""

    user_id: int | None = None
    order_id: int | None = None
    generation_task_id: int | None = None
    task_id: str | None = None
    stage: str | None = None


_runtime_context: ContextVar[GenerationRuntimeContext | None] = ContextVar(
    "paper_generation_runtime_context",
    default=None,
)
_UNSET = object()


def get_runtime_context() -> GenerationRuntimeContext:
    """读取当前调用链上下文。"""

    return _runtime_context.get() or GenerationRuntimeContext()


def _resolve_context_value[T](value: T | object, default: T) -> T:
    """解析可选覆盖值，未传入时沿用当前上下文字段。"""

    if value is _UNSET:
        return default
    return cast(T, value)


@contextmanager
def use_runtime_context(
    *,
    user_id: int | None | object = _UNSET,
    order_id: int | None | object = _UNSET,
    generation_task_id: int | None | object = _UNSET,
    task_id: str | None | object = _UNSET,
    stage: str | None | object = _UNSET,
) -> Iterator[GenerationRuntimeContext]:
    """临时覆盖调用链上下文，退出后自动恢复。"""

    current = get_runtime_context()
    next_context = GenerationRuntimeContext(
        user_id=_resolve_context_value(user_id, current.user_id),
        order_id=_resolve_context_value(order_id, current.order_id),
        generation_task_id=_resolve_context_value(generation_task_id, current.generation_task_id),
        task_id=_resolve_context_value(task_id, current.task_id),
        stage=_resolve_context_value(stage, current.stage),
    )
    token = _runtime_context.set(next_context)
    try:
        yield next_context
    finally:
        _runtime_context.reset(token)


__all__ = ["GenerationRuntimeContext", "get_runtime_context", "use_runtime_context"]
