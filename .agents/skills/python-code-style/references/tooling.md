# 工具链约定

## 项目基线

- Python：`>=3.13`
- 依赖管理：`uv`
- Lint、格式化、import 排序：Ruff
- 类型检查：Mypy
- 测试：pytest、pytest-asyncio
- 数据库迁移：Aerich

## 常用命令

```bash
uv sync
uv run ruff check .
uv run ruff format .
uv run mypy .
uv run pytest
```

按需缩小范围：

```bash
uv run ruff check services/user_service.py
uv run mypy services/user_service.py
uv run pytest tests/test_user_service.py -v
```

## Ruff 配置取舍

项目已在 `pyproject.toml` 中配置：

- `target-version = "py313"`
- `line-length = 120`
- `select = ["E", "F", "I", "UP", "B", "N"]`
- `ignore = ["E501", "B008", "N802", "UP046"]`

不要用通用配置替换这些项目约定。几个忽略项的含义：

- `E501`：行宽由 Ruff formatter 和 `line-length` 统一处理。
- `B008`：FastAPI `Depends()` 写在参数默认值中是框架约定。
- `N802`：配置类中部分大写 property 是有意设计。
- `UP046`：Pydantic 对 PEP 695 新泛型语法支持仍需谨慎。

## Mypy 约定

项目已启用：

- `python_version = "3.13"`
- `ignore_missing_imports = true`
- `disallow_untyped_defs = true`
- `warn_return_any = true`
- `warn_unused_ignores = true`

新增业务代码时，不要用 `Any` 或 `# type: ignore` 逃避类型问题。确实需要忽略时，在同一行说明原因，并优先缩小忽略范围。

## 校验策略

- 只改注释或 skill 文档：检查 Markdown/frontmatter 结构即可。
- 改 Python 文件：至少运行 `uv run ruff check <path>`。
- 改 import、格式或批量风格：运行 `uv run ruff check .` 和 `uv run ruff format .`。
- 改公开函数签名、schema、service、model：加跑 `uv run mypy .`。
- 改业务流程、路由、数据库行为：加跑相关 pytest；必要时补测试。

## 不采用的通用工具建议

- 不把 Black、isort、flake8 作为独立工具引入；Ruff 已覆盖当前需求。
- 不在 README 或 skill 中推荐 `pip install` 作为本项目开发流程。
- 不把 Python 3.12 示例配置迁入项目；当前项目是 Python 3.13。
