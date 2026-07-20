---
name: python-code-style
description: edu-sys-spider 项目的 Python/FastAPI/Tortoise/Pydantic 代码规范。编写、修改、重构、调试或审查任何 Python 文件，调整 schema/model/service/api 分层，修复 Ruff/Mypy，迁移旧爬虫代码或补充测试时必须使用；加载后必须继续读取 references/code-style.md。
---

# edu-sys-spider Python 代码规范

这个 skill 面向当前 `edu-sys-spider` 仓库，不是通用 FastAPI 模板。只要要编写、修改、审查 Python 代码，都必须遵循本 skill 和引用文件。

## 必读流程

1. **先读本文件。**
2. **再读 `references/code-style.md`。这是强制步骤，不是可选参考。**
3. 按任务需要读取：
   - `references/project-structure.md`：新增模块、调整分层、判断代码放在哪里。
   - `references/tooling.md`：运行 Ruff、Mypy、pytest、Aerich 或解释工具链约定。

如果没有读取 `references/code-style.md`，不要开始写 Python 代码。

## 当前项目基线

- Python：`>=3.13`
- 依赖管理：`uv`
- Web 框架：FastAPI
- ORM：Tortoise-ORM
- Schema：Pydantic
- Redis：`redis.asyncio`
- 日志：Loguru
- 校验：Ruff、Mypy、pytest
- 命令执行：本仓库命令使用 `rtk` 前缀，例如 `rtk uv run pytest`

## 核心要求

- 路由层保持薄层，业务逻辑放在 `services/`。
- API 输入输出放在 `schemas/`，不要直接暴露 ORM model。
- ORM model 放在 `models/`，新增模型后同步检查 `core/config.py` 注册。
- 通用基础设施放在 `core/`，业务无关工具放在 `utils/`。
- 所有函数参数和返回值都写类型注解。
- 每个函数上方写一行中文注释，便于编辑器折叠后仍能识别函数用途。
- 每个函数内部写中文 docstring；有参数时必须说明参数，必要时说明返回值和业务边界。
- 模块内函数遵循先定义再调用：被入口函数调用的辅助函数写在入口函数上方。
- 优先让一个文件围绕一个核心功能展开，避免把主流程拆成大量小函数。
- 捕获具体异常，必要时 `raise ... from exc` 保留异常链。
- 不用 `Any` 或 `# type: ignore` 掩盖类型问题，除非边界处无法避免且有明确原因。

## AI 常见漏项

这些问题在本项目中必须主动避免：

- 没读 `references/code-style.md` 就开始写代码。
- 迁移旧项目代码时把 `dict` 响应、旧工具函数、旧依赖原样搬进来。
- 在 FastAPI 路由里堆业务逻辑。
- 为局部细节拆过多函数，导致一个文件读起来像小框架。
- 入口函数写在辅助函数前面，导致阅读时先看到未定义调用。
- 只写函数内 docstring，没有在函数上方写编辑器折叠时可见的中文说明。
- docstring 只写一句话，没有说明参数、返回值或业务边界。
- 捕获 `Exception` 后静默吞掉异常。
- 改 schema/service 后只跑 Ruff，不跑 Mypy 或相关测试。

## 验证要求

- 改 Python 文件：至少运行对应文件 Ruff。
- 改 schema、service、model、类型签名：加跑 Mypy。
- 改业务流程、路由、数据库或爬虫解析：加跑相关 pytest。
- 迁移旧项目代码：先跑 touched files 的 Ruff/Mypy，再跑相关测试。
- 最终回复说明实际运行过的命令和结果。
