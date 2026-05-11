# 代码风格细则

## 注释与 docstring

- 注释使用中文，变量名、函数名、类名保持英文。
- 注释解释“为什么这样做”、边界条件、业务约束和异常原因，不逐行复述代码。
- 复杂函数可以在函数上方加一行中文注释，便于折叠时快速识别；简单函数不强制添加。
- 公共函数、类、方法和复杂业务函数应包含 docstring；内部短小辅助函数可按可读性判断。

```python
def get_user_by_id(user_id: int) -> User | None:
    """根据用户 ID 查询用户，不存在时返回 None。"""
    return User.get_or_none(id=user_id)
```

```python
# 按业务幂等要求跳过已完成任务，避免重复扣减库存
if task.is_finished:
    return
```

## 函数拆分

- 不要为了“复用一两行代码”创建大量细碎函数，例如简单字典返回、字符串拼接、轻量字段映射。
- 适合拆分的情况：逻辑超过 5 行、包含复杂判断、具有独立业务语义、需要单独测试、被多处复用且直接内联会降低可读性。
- 函数建议保持在 60 行以内；超过时优先检查职责是否混杂。
- 控制嵌套深度不超过 3 层，优先使用提前返回让主流程变平。

```python
def process_order(order: Order) -> None:
    """处理订单支付完成后的业务动作。"""
    if order.is_cancelled:
        return
    if not order.is_paid:
        return

    create_delivery_task(order)
    notify_user(order)
```

## 模块组织

模块内部按以下顺序组织：

1. 模块文档字符串或文件说明
2. 标准库、第三方库、本项目模块 import
3. 常量定义
4. 底层工具函数
5. 核心业务函数
6. 入口函数或主流程函数
7. `if __name__ == "__main__"` 块

import 使用绝对导入，避免跨层级相对导入。

```python
from services.user_service import get_user_by_id
```

## 命名

| 类型 | 风格 | 示例 |
| --- | --- | --- |
| 函数、变量 | `snake_case` | `create_user`, `retry_count` |
| 类名 | `PascalCase` | `UserService` |
| 常量 | `UPPER_SNAKE_CASE` | `MAX_RETRY_LIMIT` |
| 私有成员 | `_` 前缀 | `_build_query` |
| 布尔变量 | `is_`、`has_`、`can_` | `is_active`, `has_error` |

命名应见名知意，除常见循环计数器外避免单字母变量。

## 错误处理

- 捕获具体异常类型，不写裸 `except:`。
- 捕获异常后必须记录日志、转换为业务异常或重新抛出。
- 不静默吞掉异常；如果确实允许忽略，需要中文注释说明原因。
- 重新抛出时使用 `raise ... from exc` 保留异常链。

```python
try:
    await redis_client.ping()
except TimeoutError as exc:
    logger.warning("Redis 心跳超时，交由上层健康检查返回异常状态")
    raise RuntimeError("Redis 连接超时") from exc
```

## 类型注解

- 所有函数参数和返回值都写类型注解。
- Python 3.13 项目优先使用内置泛型和 `| None`，例如 `list[str]`、`dict[str, Any]`、`User | None`。
- 返回复杂结构时优先定义 Pydantic Schema、dataclass 或明确的类型别名，不长期依赖裸 `dict`。
- 测试代码可适度宽松，但不要影响业务代码的 Mypy 质量。

## 禁止事项

| 禁止行为 | 原因 |
| --- | --- |
| 裸 `except:` | 会吞掉系统退出、键盘中断和未知异常，难以排查 |
| 可变对象作为默认参数 | Python 运行期会复用同一个对象 |
| 未使用变量、未使用 import | 增加阅读和维护负担 |
| 连续堆叠大量单行函数 | 文件结构碎片化 |
| 在路由层堆业务逻辑 | 破坏 FastAPI 分层，难以测试 |
| 把英文通用模板原样写入项目注释 | 与当前中文模板风格不一致 |
