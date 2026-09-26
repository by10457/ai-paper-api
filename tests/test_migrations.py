"""数据库迁移测试全部使用隔离文件与 fake，会话不访问真实 MySQL。"""

from pathlib import Path
from typing import Any

import pytest

from migrations.runner import (
    MIGRATION_DIRECTORY,
    MIGRATION_TABLE_SQL,
    MigrationError,
    MySQLSession,
    apply_migrations,
    discover_migrations,
    validate_migrations,
)


class FakeDB:
    """记录迁移和锁操作，模拟部署账本。"""

    # 初始化隔离状态
    def __init__(self) -> None:
        """创建空账本和调用记录。"""
        self.applied: dict[str, str] = {}
        self.scripts: list[str] = []
        self.queries: list[str] = []
        self.lock = 1
        self.fail_script = False

    # 模拟版本账本查询及登记
    async def execute_query_dict(self, sql: str, values: list[object] | None = None) -> list[dict[str, Any]]:
        """根据 sql/values 返回 fake 查询结果并保存登记。"""
        self.queries.append(sql)
        if "DATABASE() AS" in sql:
            return [{"db_name": "isolated_test"}]
        if "GET_LOCK" in sql:
            return [{"acquired": self.lock}]
        if sql.startswith("SELECT migration_name"):
            return [{"migration_name": key, "checksum": value} for key, value in self.applied.items()]
        if sql.startswith("INSERT INTO schema_migration"):
            assert values is not None
            self.applied[str(values[0])] = str(values[1])
        return []

    # 模拟后续 DDL 失败
    async def execute_script(self, sql: str) -> None:
        """记录 sql；开启故障时在业务 SQL 阶段抛错。"""
        self.scripts.append(sql)
        if self.fail_script and sql != MIGRATION_TABLE_SQL:
            raise RuntimeError("sensitive database detail")


# 生成最小迁移版本
def write_migration(directory: Path, name: str = "001_test.py", sql: str = "SELECT 1;") -> Path:
    """在 directory 写入 name，返回执行 sql 的隔离版本路径。"""
    path = directory / name
    path.write_text(f"async def upgrade(db):\n    return {sql!r}\n", encoding="utf-8")
    return path


# 验证成功登记和二次部署去重
async def test_apply_is_ordered_and_idempotent(tmp_path: Path) -> None:
    """tmp_path 中的版本按序执行，重跑不执行已登记 SQL。"""
    write_migration(tmp_path, "002_second.py", "SELECT 2;")
    write_migration(tmp_path)
    db = FakeDB()
    assert await apply_migrations(db, tmp_path) == 2
    assert db.scripts[1:] == ["SELECT 1;", "SELECT 2;"]
    assert await apply_migrations(db, tmp_path) == 0
    assert list(db.applied) == ["001_test.py", "002_second.py"]
    assert db.queries[-1] == "SELECT RELEASE_LOCK(%s)"


# 历史内容变更必须在执行新版本前失败
async def test_checksum_change_blocks_new_versions(tmp_path: Path) -> None:
    """验证 tmp_path 历史文件变更被拒绝且释放锁。"""
    write_migration(tmp_path)
    db = FakeDB()
    await apply_migrations(db, tmp_path)
    write_migration(tmp_path, sql="SELECT 99;")
    write_migration(tmp_path, "002_new.py", "SELECT 2;")
    with pytest.raises(MigrationError, match="内容发生变化"):
        await apply_migrations(db, tmp_path)
    assert "SELECT 2;" not in db.scripts
    assert len(db.applied) == 1
    assert "RELEASE_LOCK" in db.queries[-1]


# 部分失败不登记，允许幂等版本在修复外部故障后重试
async def test_failure_is_not_recorded_and_can_retry(tmp_path: Path) -> None:
    """验证 tmp_path 迁移失败不泄漏原始数据库异常。"""
    write_migration(tmp_path)
    db = FakeDB()
    db.fail_script = True
    with pytest.raises(MigrationError) as error:
        await apply_migrations(db, tmp_path)
    assert "sensitive" not in str(error.value)
    assert not db.applied
    assert "RELEASE_LOCK" in db.queries[-1]
    db.fail_script = False
    assert await apply_migrations(db, tmp_path) == 1


# 锁超时不允许执行任何 DDL
async def test_lock_timeout_performs_no_write(tmp_path: Path) -> None:
    """验证 tmp_path 迁移未取得锁时不会创建账本或执行 SQL。"""
    write_migration(tmp_path)
    db = FakeDB()
    db.lock = 0
    with pytest.raises(MigrationError, match="超时"):
        await apply_migrations(db, tmp_path)
    assert not db.scripts
    assert not any("RELEASE_LOCK" in query for query in db.queries)


# 所有版本语法必须先验证
async def test_invalid_later_migration_blocks_all_writes(tmp_path: Path) -> None:
    """验证 tmp_path 后续版本损坏时连第一版也不会执行。"""
    write_migration(tmp_path)
    (tmp_path / "002_bad.py").write_text("not valid python!", encoding="utf-8")
    db = FakeDB()
    with pytest.raises(SyntaxError):
        await apply_migrations(db, tmp_path)
    assert not db.queries
    assert not db.scripts


# 序号不能重复，也不能插入已执行历史之前
async def test_duplicate_and_out_of_order_versions_rejected(tmp_path: Path) -> None:
    """验证 tmp_path 中重复和倒序新增版本的保护。"""
    write_migration(tmp_path, "002_second.py")
    db = FakeDB()
    await apply_migrations(db, tmp_path)
    write_migration(tmp_path)
    with pytest.raises(MigrationError, match="历史迁移"):
        await apply_migrations(db, tmp_path)
    write_migration(tmp_path, "001_duplicate.py")
    with pytest.raises(MigrationError, match="重复"):
        discover_migrations(tmp_path)


# 检查仓库真实版本的预检与基线
async def test_repository_migrations_require_existing_baseline() -> None:
    """真实迁移只读 fake 表列表，不会误初始化空库或导入演示用户。"""
    from migrations.runner import load_upgrade

    versions = validate_migrations()
    assert len(versions) == 2
    for version in versions:
        with pytest.raises(MigrationError, match="基础业务表"):
            await load_upgrade(version)(FakeDB())


# 版本账本的初始化定义需与执行器一致
def test_init_sql_contains_same_migration_ledger() -> None:
    """核对全新安装 SQL、镜像打包及部署入口。"""
    root = MIGRATION_DIRECTORY.parents[1]
    assert MIGRATION_TABLE_SQL.strip() in (root / "sql/init.sql").read_text()
    dockerfile = (root / "Dockerfile").read_text()
    assert dockerfile.count("COPY --chown=app:app migrations ./migrations") == 2
    script = (root / "start.sh").read_text()
    assert script.index("\nrun_database_migrations\n") < script.index("\ndeploy_frontend_assets\n")
    assert script.index("\nrun_database_migrations\n") < script.index('docker rm -f "$CONTAINER_NAME"')


# 脚本后续语句的错误必须在同一物理连接上传播
async def test_session_consumes_later_results() -> None:
    """用 fake 游标验证 execute_script 不漏掉第二条 SQL 错误。"""
    from unittest.mock import AsyncMock, MagicMock

    connection = MagicMock()
    cursor = AsyncMock()
    connection.cursor.return_value.__aenter__ = AsyncMock(return_value=cursor)
    connection.cursor.return_value.__aexit__ = AsyncMock(return_value=False)
    cursor.nextset.side_effect = [True, RuntimeError("second statement failed")]
    session = MySQLSession(connection)
    with pytest.raises(RuntimeError, match="second statement"):
        await session.execute_script("SELECT 1; SELECT 2;")
    assert connection.cursor.call_count == 1
    assert cursor.nextset.await_count == 2

# 模拟 Docker 命令，实际执行部署脚本中的迁移函数以验证失败中止
@pytest.mark.parametrize("failure", ["", "--check", "--preflight", "apply"])
def test_deploy_migration_failure_blocks_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    """运行提取出的部署函数，不运行 Docker、不读取真实环境文件。

    Args:
        tmp_path: 隔离命令与日志目录。
        monkeypatch: 隔离环境变量。
        failure: 模拟失败的迁移阶段，空串表示成功。
    """
    import os
    import subprocess

    root = MIGRATION_DIRECTORY.parents[1]
    script = (root / "start.sh").read_text()
    function = script.split("run_database_migrations() {", 1)[1].split("\ndeploy_frontend_assets() {", 1)[0]
    docker = tmp_path / "docker"
    docker.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_CALLS"\n'
        'last=""\nfor arg in "$@"; do last="$arg"; done\n'
        '[ "$last" != "migrations.runner" ] || last=apply\n'
        '[ "$last" != "$TEST_FAILURE" ]\n',
        encoding="utf-8",
    )
    docker.chmod(0o700)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setenv("TEST_CALLS", str(tmp_path / "calls"))
    monkeypatch.setenv("TEST_FAILURE", failure)
    command = (
        'set -eu\nlog() { :; }\nfail() { exit 1; }\nis_truthy() { [ "$1" = true ]; }\n'
        'SANITIZED_ENV_FILE=/fake/env\nNETWORK_NAME=test-network\nADD_HOST_GATEWAY=true\nIMAGE_NAME=test-image\n'
        "run_database_migrations() {" + function +
        '\nrun_database_migrations\nprintf replacement-reached\n'
    )
    result = subprocess.run(["sh", "-c", command], capture_output=True, text=True, check=False)
    calls = (tmp_path / "calls").read_text().splitlines()
    expected = {"": 3, "--check": 1, "--preflight": 2, "apply": 3}[failure]
    assert len(calls) == expected
    assert all("--network test-network" in call for call in calls)
    assert all("--env-file /fake/env" in call for call in calls)
    assert all("host.docker.internal:host-gateway" in call for call in calls)
    assert (result.returncode == 0) == (not failure)
    assert ("replacement-reached" in result.stdout) == (not failure)
