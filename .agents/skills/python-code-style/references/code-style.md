# 代码风格细则

## 执行要求

本文件是 `python-code-style` skill 的强制细则。写 Python 代码前必须先阅读本文件，并在实现、重构、review、修 bug 时主动核对下面规则。

特别注意：

- 不要只读 `python-code-style/SKILL.md` 的摘要。
- 不要把旧项目代码原样复制进来，必须按本文件规则收窄类型、分层和异常处理。
- 如果代码实现和本文件冲突，优先修改代码，而不是忽略规则。
- 最终回复中说明实际运行过的 Ruff、Mypy、pytest 或 OpenAPI 检查。

## 注释与 docstring

- 注释使用中文，变量名、函数名、类名保持英文。
- 注释解释“为什么这样做”、边界条件、业务约束和异常原因，不逐行复述代码。
- 每个函数上方都写一行中文注释，说明函数用途，便于编辑器折叠代码后仍能识别。
- 每个函数内部都写中文 docstring；函数有参数时必须写 `Args`，有返回值时写 `Returns`。
- 模块级关键常量、映射表、正则表达式、第三方接口路径等变量上方必须写一行中文注释，说明业务来源或用途。
- 关键代码块上方写简短中文注释，说明业务边界或特殊处理原因。
- 注释不要逐行复述代码，也不要使用英文通用模板。

```python
# 根据用户 ID 查询用户，不存在时返回 None
def get_user_by_id(user_id: int) -> User | None:
    """根据用户 ID 查询用户。

    Args:
        user_id: 用户 ID。

    Returns:
        查询到的用户；不存在时返回 None。
    """
    return User.get_or_none(id=user_id)
```

```python
# 按业务幂等要求跳过已完成任务，避免重复扣减库存
if task.is_finished:
    return
```

```python
# 强智课表查询接口路径。
COURSE_PATH = "/jsxsd/xskb/xskb_list.do"
# 老版课表行头可能使用 `0102节` 这类紧凑写法，这里映射到真实节次。
SECTION_MARKER_MAP = {"0102": (1, 2)}
# 同一个课表格子内，多门课程通常用一串横线分隔。
COURSE_SEPARATOR_PATTERN = re.compile(r"-{5,}")
```

## 函数拆分

- 本项目偏好“一个文件围绕一个核心功能展开”，不要把一个核心流程拆成大量小函数。
- 不要为了局部细节创建细碎函数，例如简单字典返回、字符串清理、轻量字段映射、只被调用一次的几行逻辑。
- 适合拆分的情况：有明确独立业务语义、需要单独测试、被多处复用，或直接内联会让主流程难以阅读。
- 对于工具函数，优先保留一个清晰的核心入口函数；关键步骤用中文注释分段表达。
- 函数建议保持在 300 行以内；超过时优先检查职责是否混杂。
- 控制嵌套深度不超过 3 层，优先使用提前返回让主流程变平。

```python
# 处理订单支付完成后的业务动作
def process_order(order: Order) -> None:
    """处理订单支付完成后的业务动作。

    Args:
        order: 订单对象。
    """
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
4. 类型别名、TypedDict、dataclass 等结构定义
5. 被调用的底层工具函数
6. 中层业务函数
7. 入口函数或主流程函数
8. `if __name__ == "__main__"` 块

函数顺序遵循“先定义再调用”：入口函数调用的辅助函数，应写在入口函数上方。这样从上往下阅读时，不会先看到未定义的调用目标。

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
- 外部边界允许短暂使用 `Any`，但必须在边界处收窄：`httpx.Response.json()`、LangChain `ainvoke()`、第三方 SDK 返回值、`model_dump()` 等应通过 `cast`、schema 校验或类型别名转换成明确类型后再进入业务逻辑。
- 不要把 `dict[str, object]` 作为第三方构造函数的动态 `**kwargs` 传入；优先显式传参，或者定义 `TypedDict`，避免 Mypy 把所有重载都判为不匹配。
- 第三方库里“工厂函数”和“真实类型”分开时要分别导入，例如 `python-docx` 中 `docx.Document` 是创建函数，类型应使用 `docx.document.Document`。
- 测试代码可适度宽松，但不要影响业务代码的 Mypy 质量。

## 禁止事项

| 禁止行为 | 原因 |
| --- | --- |
| 裸 `except:` | 会吞掉系统退出、键盘中断和未知异常，难以排查 |
| 可变对象作为默认参数 | Python 运行期会复用同一个对象 |
| 未使用变量、未使用 import | 增加阅读和维护负担 |
| 连续堆叠大量小函数 | 一个功能被拆散，文件读起来复杂 |
| 函数上方没有中文说明 | 编辑器折叠代码后无法快速识别函数用途 |
| docstring 不写参数说明 | 后续维护者无法快速确认调用契约 |
| 在路由层堆业务逻辑 | 破坏 FastAPI 分层，难以测试 |
| 把英文通用模板原样写入项目注释 | 与当前中文模板风格不一致 |
