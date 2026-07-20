---
name: test-guidelines
description: ai-paper-api 项目的 pytest 测试开发与维护规范。新增、修改、迁移、归类、审查或删除 tests 下的测试与 fixture，测试 FastAPI、论文生成、LLM、Redis 队列、文档/图片渲染、对象存储或外部回调，或修复测试隔离与临时文件问题时必须使用。
---

# ai-paper-api 测试开发规范

## 开始前

1. 先读被测实现和相邻测试，确认真实契约、现有替身和断言风格。
2. 修改 Python 测试时，同时读取 `../python-code-style/SKILL.md` 及其强制引用。
3. 修 bug 时先写或定位能复现问题的最小测试，再修改实现。
4. 先运行 `rtk git status --short`，保留用户已有改动。

## 当前测试布局

以仓库现状为准，不套用其他项目的目录模板：

```text
tests/
├── test_config.py                 # 配置解析
├── test_health.py                 # 健康检查
├── test_security.py               # 密码与安全工具
├── test_llm_client.py             # LLM 协议与错误脱敏
├── test_admin_*.py                # 管理端服务与 schema
├── test_paper_queue.py            # Redis 队列
├── test_paper_worker.py           # worker 调度
├── test_status_store.py           # Redis/本地状态兜底
└── thesis/                        # 论文领域的 API、业务、内容、文档、图片、存储和 schema
```

- 新测试优先放到已有相邻文件；一个文件围绕一个模块或紧密相关的契约展开。
- `services/thesis/`、论文 API、论文 schema、DOCX/图片/参考文献/存储测试放 `tests/thesis/`。
- `core/`、`llm/`、`tasks/`、管理服务等横切或顶层模块继续使用 `tests/test_<subject>.py`。
- 只有测试数量和共享 fixture 已形成清晰领域边界时才新增子目录；不要为“镜像生产目录”批量移动现有测试。
- 当前没有全局 `conftest.py` 和固定响应 fixture 目录。局部 fixture 保留在测试文件内；确有跨文件复用后再提取。
- 保留测试包的 `__init__.py`。

## 测试设计

- 文件命名为 `test_<subject>.py`；函数命名为 `test_<condition>_<expected_result>`。
- 按 Arrange、Act、Assert 的顺序组织，但不添加逐行复述代码的模板注释。
- 一个测试验证一个可描述的行为；输入变体使用 `pytest.mark.parametrize`。
- 优先断言 API 契约、返回值、持久化状态、生成产物和错误脱敏，不锁定无关的私有调用细节。
- 除非调用顺序本身是论文生成或退款流程的契约，否则不要断言实现步骤顺序。
- 新异步测试直接使用 `async def`；项目已配置 `asyncio_mode = "auto"`，不要新建或关闭事件循环。不要仅为统一风格改写现有 `asyncio.run(...)` 测试。
- 测试类只在共享场景或一组文档结构断言能显著改善阅读时使用。

## 项目关键契约

改动相应模块时，按影响选择覆盖：

- API：状态码、响应 schema、认证依赖、`Idempotency-Key` 和路由注册。
- 订单：扣积分、失败重试、最终失败退款、重复请求不重复扣费或入队。
- 队列与 worker：ready/delayed 队列、去重、并发槽、终态任务跳过和重启补偿。
- 状态：Redis 优先、本地 `status.json` 兜底以及终态修正。
- LLM/参考文献：协议分发、解析降级、额度/认证错误映射，且错误信息不得泄露 API Key 或供应商原始敏感响应。
- 文档与图片：DOCX 的 OOXML/版式语义、图表或占位图产物、Mermaid 规范化及渲染失败降级；避免依赖不稳定的像素级快照。
- 存储与回调：local/qiniu/minio/cos 分发、远端失败回落本地、私有下载链接按需生成，以及回调字段完整性。

## 隔离外部边界

- 自动化测试不得访问真实 MySQL、Redis、LLM、万方、SerpAPI、CrossRef、对象存储、业务回调地址或其他公网服务。
- 使用 `monkeypatch`、轻量 fake 或 `AsyncMock` 替换最窄的外部边界；在被测模块实际查找名称的位置打补丁。
- Redis 测试替换 `core.redis.redis_client`，只实现当前场景需要的命令，不启动真实 Redis。
- ORM 测试替换模型查询/写入边界；需要验证 SQL 或事务语义时，另行明确集成测试环境，不让普通单元测试隐式依赖本机 MySQL。
- HTTP、LLM、存储 SDK、Mermaid CLI、图片下载和回调测试使用可观察 fake，断言请求参数与结果映射。
- 测试 FastAPI 路由时使用 `app.dependency_overrides` 替换认证依赖，并在 fixture 的清理阶段恢复；不要让覆盖泄漏到其他测试。
- 仅检查路由注册时直接读取 `app.routes`。需要 HTTP 行为但不需要生命周期时优先使用 ASGI transport；使用 `TestClient` 生命周期时，必须避免启动阶段真的连接 MySQL/Redis 或启动 scheduler/worker。
- 不使用 `sleep` 等待队列或并发状态；替换等待边界，或暴露可断言的同步点。

## 文件、环境与测试数据

- 文件生成测试使用 pytest 的 `tmp_path`；不要使用 `tempfile.mktemp()` 新增不受控临时文件。
- 将 `OUTPUT_ROOT`、当前工作目录或存储路径替换到临时目录，测试结束后不得污染 `public/output/`、仓库根目录或用户环境。
- 使用 `monkeypatch.setenv/delenv/chdir` 修改环境与工作目录，使 pytest 自动恢复。
- 测试数据使用明显虚构的用户、学号、Token、API Key、论文和回调地址。
- 不提交真实姓名、账号、手机号、邮箱、密码、Cookie、JWT、API Key、对象存储密钥、验证码、抓包或模型原始敏感响应。
- 如需固定响应样本，只保留触发分支的最小字段，先脱敏，再从 `Path(__file__)` 解析路径；不得依赖执行命令时的当前目录。

## 保留、迁移与删除

- 不因测试失败、维护成本高、近期未修改或“看起来旧”而删除测试。
- 删除前必须用 `rg` 查引用并对照生产实现，证明满足以下至少一项：契约已删除；存在条件、动作和断言等价的替代覆盖；或文件是未被收集和引用的一次性调试产物。
- 移动或合并测试前后运行 `pytest --collect-only -q`，比较收集数量与 node id；数量变化必须有明确理由。
- fixture 含敏感数据时优先用最小合成数据替代，不把“无法公开”当作取消回归覆盖的理由。
- 最终说明删除或移动对象、证据、替代覆盖和恢复方式。

## 验证顺序

按改动范围逐步扩大，不机械运行无关命令：

```bash
# 先验证本次直接影响
rtk uv run pytest <changed-or-related-test-paths> -q
rtk uv run ruff check <changed-test-paths> <changed-production-paths>

# 移动、重命名或调整收集规则时
rtk uv run pytest --collect-only -q

# 类型或生产代码契约变化时
rtk uv run mypy <changed-test-paths> <changed-production-paths>

# 影响跨模块流程或准备交付时
rtk uv run pytest -q
```

当前仓库全量 `mypy tests` 存在既有错误，不把它冒充绿色基线。新改测试应有完整类型；运行 Mypy 后区分本次新增错误与既存错误，并在最终结果中如实记录。

## 完成检查

- 测试放在现有项目结构中的正确位置。
- 覆盖可观察契约和失败/降级路径，不依赖实现偶然细节。
- 不访问真实外部服务，不泄漏全局覆盖、环境或临时文件。
- 不包含真实凭据、个人数据或未脱敏响应。
- 已运行相关 pytest 与 Ruff；按影响补充收集、Mypy 和全量 pytest。
- 最终回复列出实际命令、结果、既存失败和残余风险。
