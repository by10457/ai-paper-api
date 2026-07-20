# 工具链约定

本文件只记录 `edu-sys-spider` 当前实际使用的工具链和校验方式。

## 项目基线

- Python：`>=3.13`
- 依赖管理：`uv`
- Lint、import 排序：Ruff
- 类型检查：Mypy
- 测试：pytest、pytest-asyncio
- 数据库迁移：Aerich
- 命令前缀：在本仓库执行命令时使用 `rtk`

## 常用命令

```bash
rtk uv sync
rtk uv run ruff check api core models schemas services tests utils app.py main.py
rtk uv run mypy api core models schemas services utils app.py main.py tests
rtk uv run pytest
```

按需缩小范围：

```bash
rtk uv run ruff check services/spider/repositories.py
rtk uv run mypy services/spider/repositories.py
rtk uv run pytest tests/schools/v1_0052/test_business_parsers.py
```

OpenAPI 生成检查：

```bash
rtk uv run python -c "from app import app; app.openapi(); print('openapi ok')"
```

## Ruff 配置

以 `pyproject.toml` 为准，不要用通用模板覆盖：

- `target-version = "py313"`
- `line-length = 120`
- `select = ["E", "F", "I", "UP", "B", "N"]`
- `ignore = ["E501", "B008", "N802", "UP046"]`

说明：

- `E501`：行宽由项目统一配置处理，不为它做局部绕行。
- `B008`：FastAPI `Depends()` 写在参数默认值中是框架约定。
- `N802`：配置类中大写 property 是项目约定。
- `UP046`：Pydantic 与新泛型语法兼容性需要谨慎。

## Mypy 约定

以 `pyproject.toml` 为准：

- `python_version = "3.13"`
- `ignore_missing_imports = true`
- `disallow_untyped_defs = true`
- `warn_return_any = true`
- `warn_unused_ignores = true`

新增业务代码不要用 `Any` 或 `# type: ignore` 逃避类型问题。确实无法避免时，限制在边界处，并说明原因。

## 校验策略

- 只改 skill/Markdown：检查 frontmatter、标题、链接和内容是否与项目一致。
- 改 Python 文件：运行 touched files 的 Ruff。
- 改 import、格式或批量风格：运行相关范围 Ruff；需要时再运行全量 Ruff。
- 改 schema、service、model、公开函数签名：加跑 Mypy。
- 改业务流程、路由、数据库、Redis、爬虫解析：加跑相关 pytest。
- 改 FastAPI 路由或 schema：加跑 OpenAPI 生成检查。
- 迁移旧项目代码：必须运行 Ruff、Mypy、相关 pytest，不能只看 IDE。

## 不采用

- 不引入 Black、isort、flake8；当前项目用 Ruff。
- 不推荐 `pip install` 作为开发流程；当前项目用 `uv`。
- 不迁入 Python 3.12 或通用 FastAPI 模板配置。
