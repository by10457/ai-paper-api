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
    APP_RELOAD: bool = False
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 10462
    BACKEND_CORS_ORIGINS: str = "*"
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
    DB_TIMEZONE: str = "Asia/Shanghai"
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

    @property
    def cors_origins(self) -> list[str]:
        """解析允许跨域访问的前端来源，多个域名用英文逗号分隔。"""

        value = self.BACKEND_CORS_ORIGINS.strip()
        if not value or value == "*":
            return ["*"]
        return [origin.strip() for origin in value.split(",") if origin.strip()]

    # ── 日志 ──────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/app.log"

    # ── 论文生成运行配置 ─────────────────────────────────
    THESIS_OUTPUT_ROOT: str = "public/output/thesis"
    PUBLIC_BASE_URL: str = ""
    PUPPETEER_EXECUTABLE_PATH: str = ""
    TEXT_LONG_CONCURRENCY: int = Field(default=16, ge=1)
    TEXT_SHORT_CONCURRENCY: int = Field(default=32, ge=1)
    MERMAID_RENDER_CONCURRENCY: int = Field(default=2, ge=1)
    CHART_RENDER_CONCURRENCY: int = Field(default=6, ge=1)
    AI_IMAGE_RENDER_CONCURRENCY: int = Field(default=6, ge=1)
    IMAGE_MODEL_CONCURRENCY: int = Field(default=6, ge=1)
    SERPAPI_CONCURRENCY: int = Field(default=12, ge=1)
    WFDATA_CONCURRENCY: int = Field(default=12, ge=1)
    CROSSREF_CONCURRENCY: int = Field(default=10, ge=1)
    PAPER_GENERATION_CONCURRENCY: int = Field(default=20, ge=1)
    PAPER_WORKER_POLL_SECONDS: int = Field(default=2, ge=1)
    PAPER_GENERATION_MAX_RETRIES: int = Field(default=2, ge=0)
    PAPER_GENERATION_RETRY_DELAY_SECONDS: int = Field(default=120, ge=1)

    # 参考文献检索配置：默认使用万方；SerpAPI/CrossRef 用于英文检索或补全。
    REFERENCE_PROVIDER_MODE: str = "wfapi"
    WFDATA_API_KEY: str = ""
    WFDATA_API_URL: str = "https://api.wfdata.com/openwanfang/getQuery"
    SERPAPI_KEY: str = ""
    CROSSREF_MAILTO: str = ""

    # 文件存储配置：本地文件始终保留，远端存储按 STORAGE_PROVIDER 选择。
    STORAGE_PROVIDER: str = "local"
    STORAGE_OBJECT_PREFIX: str = "paper"
    STORAGE_DOWNLOAD_EXPIRES: int = Field(default=3600, ge=60)

    # 七牛云上传配置：论文生成完成后，可将 docx 上传到对象存储。
    QINIU_ACCESS_KEY: str = ""
    QINIU_SECRET_KEY: str = ""
    QINIU_BUCKET: str = ""
    QINIU_DOMAIN: str = ""
    QINIU_DOWNLOAD_EXPIRES: int = Field(default=3600, ge=60)

    # MinIO 存储配置。
    MINIO_ENDPOINT: str = ""
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET: str = ""
    MINIO_SECURE: bool = False
    MINIO_DOMAIN: str = ""

    # 腾讯云 COS 存储配置。
    COS_SECRET_ID: str = ""
    COS_SECRET_KEY: str = ""
    COS_BUCKET: str = ""
    COS_REGION: str = ""
    COS_DOMAIN: str = ""
    COS_ACCESS_POLICY: str = "PRIVATE"
    COS_UPLOAD_ALLOW_PREFIX: str = "*"

    # 业务系统回调配置：生成完成后通知上游业务系统。
    PAPER_CALLBACK_URL: str = ""
    PAPER_CALLBACK_SECRET: str = ""

    @property
    def thesis_output_root(self) -> str:
        return self.THESIS_OUTPUT_ROOT

    @property
    def public_base_url(self) -> str:
        return self.PUBLIC_BASE_URL

    @property
    def serpapi_key(self) -> str:
        return self.SERPAPI_KEY

    @property
    def reference_provider_mode(self) -> str:
        return self.REFERENCE_PROVIDER_MODE

    @property
    def wfdata_api_key(self) -> str:
        return self.WFDATA_API_KEY

    @property
    def wfdata_api_url(self) -> str:
        return self.WFDATA_API_URL

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
    def qiniu_domain(self) -> str:
        return self.QINIU_DOMAIN

    @property
    def qiniu_download_expires(self) -> int:
        return self.QINIU_DOWNLOAD_EXPIRES

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
            "use_tz": False,
            "timezone": self.DB_TIMEZONE,
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
                    "models": ["models.user", "models.paper", "models.admin", "aerich.models"],
                    "default_connection": "default",
                }
            },
        }


@lru_cache
def get_settings() -> Settings:
    """单例，整个应用生命周期只创建一次。"""
    return Settings()


settings = get_settings()
