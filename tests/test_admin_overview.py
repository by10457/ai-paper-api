"""管理后台概览健康状态测试。"""

import pytest

from services.admin import overview as overview_module


@pytest.mark.parametrize(
    ("connected", "expected"),
    ((True, "ok"), (False, "degraded")),
)
def test_mysql_health_reads_live_database_state(
    monkeypatch: pytest.MonkeyPatch,
    connected: bool,
    expected: str,
) -> None:
    """概览页必须读取实时连接状态，不能缓存应用启动前的 False。"""

    monkeypatch.setattr(overview_module.database_module, "db_connected", connected)

    assert overview_module.AdminOverviewService._mysql_health() == expected
