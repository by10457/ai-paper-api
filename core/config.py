"""
配置中心 —— 所有环境变量都从这里读取，整个项目只 import 这一个对象。

使用方式：
    from core.config import settings
    print(settings.APP_NAME)
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # ── 应用基础 ──────────────────────────────────────────
    APP_NAME: str = "FastAPI Template"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 10457
    WEB_CONCURRENCY: int | None = Field(default=None, ge=1)
    SCHEDULER_ENABLED: bool = True
    SECRET_KEY: str = "change-me-in-production"

    # ── MySQL ─────────────────────────────────────────────
    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DB: str = "app"
    MYSQL_POOL_MIN: int = 3
    MYSQL_POOL_MAX: int = 10
    DB_GENERATE_SCHEMAS: bool = False

    @property
    def TORTOISE_DATABASE_URL(self) -> str:
        return f"mysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}"

    # ── Redis ─────────────────────────────────────────────
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0
    REDIS_MAX_CONNECTIONS: int = 20

    @property
    def REDIS_URL(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ── 日志 ──────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/app.log"

    # ── Tortoise-ORM 完整配置（供 aerich 迁移工具使用）────
    @property
    def TORTOISE_ORM(self) -> dict:
        return {
            "connections": {
                "default": {
                    "engine": "tortoise.backends.mysql",
                    "credentials": {
                        "host": self.MYSQL_HOST,
                        "port": self.MYSQL_PORT,
                        "user": self.MYSQL_USER,
                        "password": self.MYSQL_PASSWORD,
                        "database": self.MYSQL_DB,
                        "minsize": self.MYSQL_POOL_MIN,
                        "maxsize": self.MYSQL_POOL_MAX,
                    },
                }
            },
            "apps": {
                "models": {
                    # 把所有 models 模块路径注册在这里
                    "models": ["models.user", "aerich.models"],
                    "default_connection": "default",
                }
            },
        }


@lru_cache
def get_settings() -> Settings:
    """单例，整个应用生命周期只创建一次。"""
    return Settings()


settings = get_settings()
