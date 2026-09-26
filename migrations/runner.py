"""部署前执行版本化迁移；独占同一 MySQL 会话，不在 API worker 中运行。"""

import argparse
import asyncio
import hashlib
import importlib.util
import inspect
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Protocol, cast

import aiomysql

from core.config import settings

logger = logging.getLogger(__name__)
# 序号固定且只允许追加；迁移内容由 SHA-256 防篡改。
MIGRATION_DIRECTORY = Path(__file__).parent / "models"
MIGRATION_PATTERN = re.compile(r"^(?P<order>\d+)_.+\.py$")
# 独立于业务 ORM 管理的部署执行账本。
MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migration (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '迁移记录主键',
    migration_name VARCHAR(255) NOT NULL COMMENT '迁移文件名',
    checksum CHAR(64) NOT NULL COMMENT '迁移文件SHA-256校验值',
    execution_ms INT UNSIGNED NOT NULL COMMENT '执行耗时毫秒',
    applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '执行完成时间',
    PRIMARY KEY (id),
    UNIQUE KEY uq_schema_migration_name (migration_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='数据库版本迁移执行记录';
"""


class MigrationError(RuntimeError):
    """迁移预检或执行失败，需要停止部署。"""


class MigrationDB(Protocol):
    """仅暴露迁移需要的查询与脚本操作，避免访问业务 ORM 连接池。"""

    # 返回字典查询结果
    async def execute_query_dict(self, sql: str, values: list[object] | None = None) -> list[dict[str, Any]]:
        """执行 SQL 和绑定参数，返回数据库行。"""
        ...

    # 执行脚本并消费所有结果集
    async def execute_script(self, sql: str) -> None:
        """执行受版本管理的 SQL；不承诺 MySQL DDL 可以回滚。"""
        ...


class MySQLSession:
    """持有一个独立物理连接，使 GET_LOCK 与所有迁移 SQL 在同一会话执行。"""

    # 绑定专用连接
    def __init__(self, connection: aiomysql.Connection) -> None:
        """保存 connection，不创建连接池，不自动重连。"""
        self.connection = connection

    # 执行参数化查询
    async def execute_query_dict(self, sql: str, values: list[object] | None = None) -> list[dict[str, Any]]:
        """执行 sql/values，返回行字典；驱动返回值在此边界收窄。"""
        async with self.connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, values)
            return cast(list[dict[str, Any]], list(await cursor.fetchall()))

    # 多语句错误必须完整传播，不能只检查第一条语句
    async def execute_script(self, sql: str) -> None:
        """执行 sql 并读取全部结果集，以捕获脚本中后续语句的错误。"""
        async with self.connection.cursor() as cursor:
            await cursor.execute(sql)
            while await cursor.nextset():
                pass


@dataclass(frozen=True)
class MigrationFile:
    """不可变的版本文件描述。"""

    order: int
    name: str
    path: Path
    checksum: str


MigrationUpgrade = Callable[[MigrationDB], Awaitable[str]]


# 发现迁移并严格校验文件名及重复序号
def discover_migrations(directory: Path = MIGRATION_DIRECTORY) -> list[MigrationFile]:
    """读取 directory 中的迁移元数据，返回按序排列的文件；不连接数据库。"""
    if not directory.is_dir():
        raise MigrationError("迁移目录不存在")
    migrations: list[MigrationFile] = []
    seen: set[int] = set()
    for path in sorted(directory.glob("*.py")):
        if path.name == "__init__.py":
            continue
        match = MIGRATION_PATTERN.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"迁移文件名不合法：{path.name}")
        order = int(match["order"])
        if order in seen:
            raise MigrationError(f"迁移序号重复：{order}")
        seen.add(order)
        migrations.append(MigrationFile(order, path.name, path, hashlib.sha256(path.read_bytes()).hexdigest()))
    return sorted(migrations, key=lambda item: item.order)


# 预加载全部迁移，避免执行一半才发现后续文件语法错误
def load_upgrade(migration: MigrationFile) -> MigrationUpgrade:
    """加载 migration 的 async upgrade(db) 入口，不执行升级。"""
    spec = importlib.util.spec_from_file_location(f"paper_migration_{migration.order}", migration.path)
    if spec is None or spec.loader is None:
        raise MigrationError(f"无法加载迁移：{migration.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    upgrade = getattr(module, "upgrade", None)
    if not inspect.iscoroutinefunction(upgrade):
        raise MigrationError(f"缺少 async upgrade(db)：{migration.name}")
    inspect.signature(upgrade).bind(object())
    return cast(MigrationUpgrade, upgrade)


# 不接触数据库的部署前检查
def validate_migrations(directory: Path = MIGRATION_DIRECTORY) -> list[MigrationFile]:
    """校验 directory 下全部迁移的命名、序号、语法及入口，返回文件列表。"""
    migrations = discover_migrations(directory)
    for migration in migrations:
        load_upgrade(migration)
    return migrations


# 在同一专用会话内执行版本迁移
async def apply_migrations(db: MigrationDB, directory: Path = MIGRATION_DIRECTORY) -> int:
    """对 db 顺序应用 directory 中的未执行版本，返回成功数量。

    已完成版本必须保持内容不变；失败版本不登记，重试依靠迁移自身幂等。
    """
    migrations = validate_migrations(directory)
    # 按数据库名隔离锁，长度不超过 MySQL 的 64 字节限制。
    rows = await db.execute_query_dict("SELECT DATABASE() AS db_name")
    database = str(rows[0]["db_name"])
    lock_name = "ai_paper_migrate_" + hashlib.sha256(database.encode()).hexdigest()[:32]
    rows = await db.execute_query_dict("SELECT GET_LOCK(%s, %s) AS acquired", [lock_name, 60])
    if not rows or rows[0]["acquired"] != 1:
        raise MigrationError("等待数据库迁移锁超时")
    try:
        await db.execute_script(MIGRATION_TABLE_SQL)
        rows = await db.execute_query_dict("SELECT migration_name, checksum FROM schema_migration")
        applied = {str(row["migration_name"]): str(row["checksum"]) for row in rows}
        orders = [int(match["order"]) for name in applied if (match := MIGRATION_PATTERN.fullmatch(name))]
        highest_order = max(orders, default=-1)
        for migration in migrations:
            if migration.name in applied:
                if applied[migration.name] != migration.checksum:
                    raise MigrationError(f"已执行迁移内容发生变化：{migration.name}")
            elif migration.order <= highest_order:
                raise MigrationError(f"不能插入或改名历史迁移：{migration.name}")

        count = 0
        for migration in migrations:
            if migration.name in applied:
                logger.info("跳过已执行迁移：%s", migration.name)
                continue
            started = monotonic()
            try:
                sql = await load_upgrade(migration)(db)
                if sql.strip():
                    await db.execute_script(sql)
                await db.execute_query_dict(
                    "INSERT INTO schema_migration (migration_name, checksum, execution_ms) VALUES (%s, %s, %s)",
                    [migration.name, migration.checksum, max(0, round((monotonic() - started) * 1000))],
                )
            except Exception as exc:
                # 不在部署日志中打印数据库原始异常或潜在敏感数据。
                raise MigrationError(f"迁移失败：{migration.name}（{type(exc).__name__}）；请核查部分执行状态后重试") from None
            count += 1
            logger.info("迁移成功：%s", migration.name)
        return count
    finally:
        await db.execute_query_dict("SELECT RELEASE_LOCK(%s)", [lock_name])


# 创建独立连接，禁止 API 连接池或启动建表逻辑参与迁移
async def run_migrations(*, preflight: bool = False) -> int:
    """读取项目配置；preflight 仅检查连接，其余模式执行待应用版本。"""
    validate_migrations()
    # 项目锁定的 aiomysql 默认启用 MULTI_STATEMENTS；使用单连接读取所有结果集。
    connection = await aiomysql.connect(
        host=settings.MYSQL_HOST, port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER, password=settings.MYSQL_PASSWORD,
        db=settings.MYSQL_DB, charset="utf8mb4", autocommit=True,
        connect_timeout=15,
    )
    try:
        db = MySQLSession(connection)
        if preflight:
            await db.execute_query_dict("SELECT 1")
            return 0
        return await apply_migrations(db)
    finally:
        connection.close()


# 提供部署 CLI，失败时以非零退出码阻断上线
def main() -> None:
    """解析 --check/--preflight 模式；默认执行迁移，错误日志不输出凭据。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="AI Paper 数据库版本迁移")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="仅预检文件，不连接数据库")
    mode.add_argument("--preflight", action="store_true", help="只读检查数据库连接")
    args = parser.parse_args()
    try:
        if args.check:
            logger.info("迁移预检通过：%d 个文件", len(validate_migrations()))
        else:
            logger.info("迁移检查完成，本次应用 %d 个版本", asyncio.run(run_migrations(preflight=args.preflight)))
    except Exception as exc:
        logger.error("%s", str(exc) if isinstance(exc, MigrationError) else f"迁移检查失败：{type(exc).__name__}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
