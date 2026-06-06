"""论文生成运行上下文。

生成链路中的内容服务、图片服务和大模型客户端都通过这里读取当前用户、
订单、任务和阶段信息，避免在每个函数签名里层层传递审计字段。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace


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


def get_runtime_context() -> GenerationRuntimeContext:
    """读取当前调用链上下文。"""

    return _runtime_context.get() or GenerationRuntimeContext()


@contextmanager
def use_runtime_context(**kwargs: object) -> Iterator[GenerationRuntimeContext]:
    """临时覆盖调用链上下文，退出后自动恢复。"""

    current = get_runtime_context()
    token = _runtime_context.set(replace(current, **kwargs))
    try:
        yield _runtime_context.get()
    finally:
        _runtime_context.reset(token)


__all__ = ["GenerationRuntimeContext", "get_runtime_context", "use_runtime_context"]
