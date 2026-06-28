"""配置解析测试。"""

from core.config import Settings


def test_cors_origins_defaults_to_wildcard() -> None:
    settings = Settings(BACKEND_CORS_ORIGINS="*")

    assert settings.cors_origins == ["*"]


def test_cors_origins_splits_comma_separated_values() -> None:
    settings = Settings(BACKEND_CORS_ORIGINS="https://a.example.com, https://b.example.com")

    assert settings.cors_origins == ["https://a.example.com", "https://b.example.com"]
