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
    APP_NAME: str = "AI Paper API"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 10462
    WEB_CONCURRENCY: int | None = Field(default=None, ge=1)
    SCHEDULER_ENABLED: bool = True
    SECRET_KEY: str = "change-me-in-production"
    DEFAULT_USER_POINTS: int = 0
    PAPER_GENERATE_POINTS: int = 200

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

    # ── LLM / 论文生成 ───────────────────────────────────
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    THESIS_OUTLINE_MODEL: str = "deepseek-chat"
    THESIS_FULLTEXT_MODEL: str = "deepseek-reasoner"
    THESIS_OUTPUT_ROOT: str = "public/output/thesis"
    TWELVEAI_API_KEY: str = ""
    TWELVEAI_IMAGE_MODEL: str = "gemini-3-pro-image-preview"
    SERPAPI_KEY: str = ""
    CROSSREF_MAILTO: str = ""
    QINIU_ACCESS_KEY: str = ""
    QINIU_SECRET_KEY: str = ""
    QINIU_BUCKET: str = ""
    PAPER_CALLBACK_URL: str = ""
    PAPER_CALLBACK_SECRET: str = ""

    @property
    def deepseek_api_key(self) -> str:
        return self.DEEPSEEK_API_KEY

    @property
    def deepseek_base_url(self) -> str:
        return self.DEEPSEEK_BASE_URL

    @property
    def deepseek_model(self) -> str:
        return self.DEEPSEEK_MODEL

    @property
    def thesis_outline_model(self) -> str:
        return self.THESIS_OUTLINE_MODEL

    @property
    def thesis_fulltext_model(self) -> str:
        return self.THESIS_FULLTEXT_MODEL

    @property
    def thesis_output_root(self) -> str:
        return self.THESIS_OUTPUT_ROOT

    @property
    def twelveai_api_key(self) -> str:
        return self.TWELVEAI_API_KEY

    @property
    def twelveai_image_model(self) -> str:
        return self.TWELVEAI_IMAGE_MODEL

    @property
    def serpapi_key(self) -> str:
        return self.SERPAPI_KEY

    @property
    def crossref_mailto(self) -> str:
        return self.CROSSREF_MAILTO

    @property
    def qiniu_access_key(self) -> str:
        return self.QINIU_ACCESS_KEY

    @property
    def qiniu_secret_key(self) -> str:
        return self.QINIU_SECRET_KEY

    @property
    def qiniu_bucket(self) -> str:
        return self.QINIU_BUCKET

    @property
    def paper_callback_url(self) -> str:
        return self.PAPER_CALLBACK_URL

    @property
    def paper_callback_secret(self) -> str:
        return self.PAPER_CALLBACK_SECRET

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
                    "models": ["models.user", "models.paper", "aerich.models"],
                    "default_connection": "default",
                }
            },
        }


@lru_cache
def get_settings() -> Settings:
    """单例，整个应用生命周期只创建一次。"""
    return Settings()


settings = get_settings()
