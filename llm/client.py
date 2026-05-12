from functools import lru_cache

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from core.config import get_settings


def _create_openai_llm(
    *,
    model: str,
    api_key: str,
    base_url: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    secret_api_key = SecretStr(api_key)
    if max_tokens is None:
        if temperature is None:
            return ChatOpenAI(model=model, api_key=secret_api_key, base_url=base_url)
        return ChatOpenAI(
            model=model,
            api_key=secret_api_key,
            base_url=base_url,
            temperature=temperature,
        )

    if temperature is None:
        return ChatOpenAI(
            model=model,
            api_key=secret_api_key,
            base_url=base_url,
            max_completion_tokens=max_tokens,
        )

    return ChatOpenAI(
        model=model,
        api_key=secret_api_key,
        base_url=base_url,
        temperature=temperature,
        max_completion_tokens=max_tokens,
    )


@lru_cache
def get_llm() -> ChatOpenAI:
    """初始化并返回可复用的 LLM 客户端单例。"""

    # 读取全局配置（已通过缓存保证只初始化一次）。
    settings = get_settings()
    # 未配置密钥时尽早失败，避免在链路深处报错难以定位。
    if not settings.deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY is not configured")

    # DeepSeek 兼容 OpenAI 协议，因此直接使用 ChatOpenAI 客户端。
    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=SecretStr(settings.deepseek_api_key),
        base_url=settings.deepseek_base_url,
        # 提取任务倾向稳定输出，温度设为 0。
        temperature=0.0,
    )


def create_llm(
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> BaseChatModel:
    """创建通用 LLM 客户端，支持按场景覆盖模型参数。"""

    settings = get_settings()
    if not settings.deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY is not configured")

    resolved_model = model or settings.deepseek_model

    if "claude" in resolved_model.lower():
        from langchain_anthropic import ChatAnthropic

        resolved_max_tokens = max_tokens if max_tokens is not None else 4096
        if temperature is None:
            return ChatAnthropic(
                model_name=resolved_model,
                api_key=SecretStr(settings.twelveai_api_key),
                base_url="https://cdn.12ai.org",
                max_tokens_to_sample=resolved_max_tokens,
                timeout=3600.0,
                stop=None,
            )
        return ChatAnthropic(
            model_name=resolved_model,
            api_key=SecretStr(settings.twelveai_api_key),
            base_url="https://cdn.12ai.org",
            max_tokens_to_sample=resolved_max_tokens,
            temperature=temperature,
            timeout=3600.0,
            stop=None,
        )

    # 动态路由：如果是 gemini 等通过 12AI 提供的模型，切换 provider
    if "gemini" in resolved_model.lower():
        api_key = settings.twelveai_api_key
        base_url = "https://api.12ai.org/v1"
    else:
        api_key = settings.deepseek_api_key
        base_url = settings.deepseek_base_url

    # deepseek-reasoner 不支持 temperature / top_p 等采样参数。
    resolved_temperature = temperature if temperature is not None and "reasoner" not in resolved_model else None
    return _create_openai_llm(
        model=resolved_model,
        api_key=api_key,
        base_url=base_url,
        temperature=resolved_temperature,
        max_tokens=max_tokens,
    )
