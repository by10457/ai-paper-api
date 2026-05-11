---
name: python-code-style
description: T-FastApi 项目的 Python 代码风格、中文注释、类型标注、Ruff/Mypy 校验、FastAPI 分层与文档规范。用于编写或审查本项目代码、调整 lint/type-check 配置、补充 docstring、制定项目代码约定时。
---

# T-FastApi Python 代码规范

这个 skill 面向当前仓库的 FastAPI 后端模板，而不是通用 Python 项目模板。执行代码编写、重构、审查或规范配置时，优先遵循本仓库已有约定。

## 当前项目约束

- Python 版本：`>=3.13`，Ruff `target-version = "py313"`，Mypy `python_version = "3.13"`。
- 依赖管理：使用 `uv`，不要新增 `pip install ...` 作为项目标准流程。
- 主要栈：FastAPI、Tortoise-ORM、Pydantic Settings、Redis asyncio、APScheduler、Loguru、Aerich。
- 代码校验：使用 `uv run ruff check .`、`uv run ruff format .`、`uv run mypy .`、`uv run pytest`。
- 行宽：`120`，由 Ruff 配置统一处理。
- 注释和新增文档：项目内优先使用中文；代码标识符仍使用英文。

## 使用流程

1. 先查看当前文件所在层级，按 `api`、`schemas`、`services`、`models`、`core`、`tasks`、`utils` 的职责边界落代码。
2. 写代码前检查 `pyproject.toml` 中已有 Ruff/Mypy 配置，不要用通用模板覆盖项目配置。
3. 新增或修改公开函数、类、方法时，补齐类型标注和必要 docstring。
4. 对关键业务逻辑添加中文注释，解释原因和边界条件；避免逐行解释显而易见的代码。
5. 修改完成后按影响范围运行校验，至少运行对应文件或模块的 Ruff；触及类型、接口或业务流程时加跑 Mypy/pytest。

## 何时读取引用文件

- 需要具体命名、注释、函数拆分、异常处理、类型注解规则时，读取 [references/code-style.md](references/code-style.md)。
- 需要按本项目 FastAPI 分层落代码、判断文件放置位置或新增业务模块时，读取 [references/project-structure.md](references/project-structure.md)。
- 需要调整 Ruff、Mypy、pytest、uv 命令或解释配置取舍时，读取 [references/tooling.md](references/tooling.md)。

## 核心规则

- 函数和变量使用 `snake_case`，类使用 `PascalCase`，常量使用 `UPPER_SNAKE_CASE`，私有成员使用 `_` 前缀。
- 所有函数参数和返回值都应写类型注解；公共 API、复杂业务函数和类应写 docstring。
- 函数职责保持单一，但不要把一两行简单逻辑过度拆成大量小函数。
- 模块组织顺序：模块说明、import、常量、底层工具函数、中层业务函数、高层入口函数、`if __name__ == "__main__"`。
- 捕获具体异常类型，不使用裸 `except:`；捕获后记录日志或重新抛出，不静默吞错。
- FastAPI 路由层只处理参数、依赖、权限和响应组装；核心业务放到 `services/`。
- ORM 模型放 `models/`，Pydantic 请求/响应结构放 `schemas/`，跨模块基础设施放 `core/`。

## 不适用于本项目的内容

- 不使用 Python 3.10/3.12 作为新代码示例基线。
- 不把 `pip install ruff mypy` 作为项目内安装指令；本项目使用 `uv sync` 和依赖组。
- 不引入 Black、isort、flake8 作为独立标准工具；本项目用 Ruff 统一 lint、format、import 排序。
- 不要求所有函数都必须额外写“函数上方单行注释”；只有复杂逻辑、折叠后难以识别的函数才需要。
- 不在 skill 中维护 README、CHANGELOG 等通用文档模板；只保留对代码规范有直接帮助的内容。
