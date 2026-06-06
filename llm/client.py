"""大模型文本客户端工厂。

模型 API 配置统一来自管理后台，当前支持 OpenAI 兼容、Anthropic Messages 和
Gemini generateContent 三类文本调用协议。
"""

import json
import time
from typing import Any, cast

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from pydantic import ConfigDict, SecretStr
from tortoise import timezone
from tortoise.exceptions import ConfigurationError

from llm.call_logger import record_model_call
from models.admin import ModelConfig

ANTHROPIC_PROTOCOLS = {"anthropic", "claude", "claude-messages"}
GEMINI_GENERATE_CONTENT_PROTOCOLS = {"gemini", "gemini-generate-content", "google-generate-content"}
DEFAULT_ANTHROPIC_MAX_TOKENS = 4096
GEMINI_HTTP_TIMEOUT_SECONDS = 300.0


class LLMProviderQuotaError(RuntimeError):
    """模型供应商账号额度不足。"""


class LLMProviderConfigError(RuntimeError):
    """模型供应商认证或协议配置错误。"""


def is_provider_quota_error(exc: BaseException) -> bool:
    """判断异常是否来自模型供应商额度不足。"""

    if isinstance(exc, LLMProviderQuotaError):
        return True
    text = str(exc).lower()
    return "insufficient_user_quota" in text or "额度不足" in text


def is_provider_config_error(exc: BaseException) -> bool:
    """判断异常是否来自模型供应商认证或协议配置。"""

    if isinstance(exc, LLMProviderConfigError):
        return True
    text = str(exc).lower()
    return "authentication fails" in text or "unauthorized" in text or "invalid api key" in text


def is_provider_platform_error(exc: BaseException) -> bool:
    """判断异常是否属于平台侧模型服务问题。"""

    return is_provider_quota_error(exc) or is_provider_config_error(exc)


def _normalize_protocol(protocol: str) -> str:
    """标准化管理后台填写的调用协议。"""
    return protocol.strip().lower()


def _is_anthropic_protocol(protocol: str) -> bool:
    """判断是否使用 Anthropic Messages 协议。"""
    return _normalize_protocol(protocol) in ANTHROPIC_PROTOCOLS


def _is_gemini_generate_content_protocol(protocol: str) -> bool:
    """判断是否使用 Gemini generateContent 协议。"""
    return _normalize_protocol(protocol) in GEMINI_GENERATE_CONTENT_PROTOCOLS


def _supports_temperature(model: str) -> bool:
    """部分推理模型不支持 temperature/top_p 等采样参数。"""
    return "reasoner" not in model.lower()


def _resolve_temperature(model: str, temperature: float | None) -> float | None:
    """按模型能力决定是否透传 temperature。"""
    if temperature is None:
        return None
    if not _supports_temperature(model):
        return None
    return temperature


async def get_enabled_model_config(config_type: str, *, allow_default: bool = True) -> ModelConfig | None:
    """读取管理后台启用的模型配置；文本场景可回退到 default。"""

    try:
        config = await _get_enabled_config_by_type(config_type)
        if config is not None:
            return config
        if not allow_default:
            return None
        return await _get_enabled_config_by_type("default")
    except ConfigurationError:
        return None


async def _get_enabled_config_by_type(config_type: str) -> ModelConfig | None:
    """按用途读取一条启用的模型配置，默认配置优先。"""
    return (
        await ModelConfig.filter(config_type=config_type, is_enabled=True)
        .order_by("-is_default", "-id")
        .first()
    )


def _create_openai_compatible_llm(
    *,
    model: str,
    api_key: str,
    base_url: str = "",
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    """创建 OpenAI Chat Completions 兼容协议客户端。"""

    secret_api_key = SecretStr(api_key)
    if max_tokens is None and temperature is None:
        return ChatOpenAI(model=model, api_key=secret_api_key, base_url=base_url or None)
    if max_tokens is None:
        return ChatOpenAI(model=model, api_key=secret_api_key, base_url=base_url or None, temperature=temperature)
    if temperature is None:
        return ChatOpenAI(
            model=model,
            api_key=secret_api_key,
            base_url=base_url or None,
            max_completion_tokens=max_tokens,
        )
    return ChatOpenAI(
        model=model,
        api_key=secret_api_key,
        base_url=base_url or None,
        temperature=temperature,
        max_completion_tokens=max_tokens,
    )


def _create_anthropic_llm(
    *,
    model: str,
    api_key: str,
    base_url: str = "",
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> BaseChatModel:
    """创建 Anthropic Messages 协议客户端。"""

    from langchain_anthropic import ChatAnthropic

    resolved_max_tokens = max_tokens if max_tokens is not None else DEFAULT_ANTHROPIC_MAX_TOKENS
    secret_api_key = SecretStr(api_key)
    if temperature is None:
        return ChatAnthropic(
            model_name=model,
            api_key=secret_api_key,
            base_url=base_url or None,
            max_tokens_to_sample=resolved_max_tokens,
            timeout=3600.0,
            stop=None,
        )
    return ChatAnthropic(
        model_name=model,
        api_key=secret_api_key,
        base_url=base_url or None,
        max_tokens_to_sample=resolved_max_tokens,
        temperature=temperature,
        timeout=3600.0,
        stop=None,
    )


class GeminiGenerateContentChatModel(BaseChatModel):
    """Gemini generateContent 兼容协议的 LangChain 聊天模型适配器。"""

    model_name: str
    api_key: str
    base_url: str
    temperature: float | None = None
    max_tokens: int | None = None

    @property
    def _llm_type(self) -> str:
        """返回 LangChain 内部识别用的模型类型。"""
        return "gemini-generate-content"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """同步调用 Gemini generateContent，并转换为 LangChain ChatResult。"""

        del run_manager, kwargs
        payload = self._build_payload(messages, stop)
        data = self._request_generate_content(payload)
        return self._build_chat_result(data)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """异步调用 Gemini generateContent，并转换为 LangChain ChatResult。"""

        del run_manager, kwargs
        payload = self._build_payload(messages, stop)
        data = await self._arequest_generate_content(payload)
        return self._build_chat_result(data)

    def _build_chat_result(self, data: dict[str, Any]) -> ChatResult:
        """把 Gemini 响应字典转换为 LangChain ChatResult。"""

        text = self._extract_text(data)
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(content=text),
                    generation_info={"model": self.model_name},
                )
            ],
            llm_output={"raw": data},
        )

    def _build_payload(self, messages: list[BaseMessage], stop: list[str] | None) -> dict[str, Any]:
        """构造 generateContent 请求体。"""

        payload: dict[str, Any] = {"contents": self._build_contents(messages)}
        system_text = self._build_system_instruction(messages)
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        generation_config = self._build_generation_config(stop)
        if generation_config:
            payload["generationConfig"] = generation_config
        return payload

    def _build_contents(self, messages: list[BaseMessage]) -> list[dict[str, Any]]:
        """把 LangChain 消息转换为 Gemini contents。"""

        contents: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, SystemMessage):
                continue
            text = self._message_text(message)
            if not text:
                continue
            role = "model" if message.type == "ai" else "user"
            contents.append({"role": role, "parts": [{"text": text}]})
        if not contents:
            contents.append({"role": "user", "parts": [{"text": ""}]})
        return contents

    def _build_system_instruction(self, messages: list[BaseMessage]) -> str:
        """合并 system 消息，适配 Gemini 独立 systemInstruction 字段。"""

        return "\n\n".join(self._message_text(message) for message in messages if isinstance(message, SystemMessage))

    def _build_generation_config(self, stop: list[str] | None) -> dict[str, Any]:
        """构造 Gemini generationConfig。"""

        generation_config: dict[str, Any] = {}
        if self.temperature is not None:
            generation_config["temperature"] = self.temperature
        if self.max_tokens is not None:
            generation_config["maxOutputTokens"] = self.max_tokens
        if stop:
            generation_config["stopSequences"] = stop
        return generation_config

    def _request_generate_content(self, payload: dict[str, Any]) -> dict[str, Any]:
        """调用 Gemini generateContent 接口并返回 JSON 字典。"""

        with httpx.Client(timeout=GEMINI_HTTP_TIMEOUT_SECONDS) as client:
            response = client.post(self._build_url(), json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self._raise_http_error(exc.response)
            data = response.json()
        return cast(dict[str, Any], data)

    async def _arequest_generate_content(self, payload: dict[str, Any]) -> dict[str, Any]:
        """异步调用 Gemini generateContent 接口并返回 JSON 字典。"""

        async with httpx.AsyncClient(timeout=GEMINI_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(self._build_url(), json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self._raise_http_error(exc.response)
            data = response.json()
        return cast(dict[str, Any], data)

    def _build_url(self) -> str:
        """生成 Gemini generateContent 请求地址。"""

        api_root = self.base_url.rstrip("/")
        if not api_root.endswith("/v1beta"):
            api_root = f"{api_root}/v1beta"
        return f"{api_root}/models/{self.model_name}:generateContent?key={self.api_key}"

    def _build_safe_url(self) -> str:
        """生成脱敏后的 Gemini generateContent 请求地址，用于错误信息。"""

        api_root = self.base_url.rstrip("/")
        if not api_root.endswith("/v1beta"):
            api_root = f"{api_root}/v1beta"
        return f"{api_root}/models/{self.model_name}:generateContent?key=***"

    def _build_http_error_message(self, response: httpx.Response) -> str:
        """生成不包含 API Key 的 HTTP 错误信息。"""

        response_text = response.text[:500]
        return (
            f"Gemini generateContent 调用失败: status={response.status_code}, "
            f"url={self._build_safe_url()}, response={response_text}"
        )

    def _raise_http_error(self, response: httpx.Response) -> None:
        """把 HTTP 错误转换为业务可识别的模型异常。"""

        error_code = ""
        error_message = ""
        try:
            data = response.json()
            if isinstance(data, dict):
                error = data.get("error")
                if isinstance(error, dict):
                    error_code = str(error.get("code") or "")
                    error_message = str(error.get("message") or "")
        except json.JSONDecodeError:
            pass

        if error_code == "insufficient_user_quota" or "额度不足" in error_message:
            raise LLMProviderQuotaError("模型供应商账号额度不足，请管理员充值或切换可用模型配置") from None
        if response.status_code == 401 or "authentication fails" in response.text.lower():
            raise LLMProviderConfigError("模型供应商认证失败，请管理员检查模型协议、Base URL 与 API Key 配置") from None
        raise RuntimeError(self._build_http_error_message(response)) from None

    def _message_text(self, message: BaseMessage) -> str:
        """提取 LangChain 消息中的文本内容。"""

        content = message.content
        if isinstance(content, str):
            return content
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)

    def _extract_text(self, data: dict[str, Any]) -> str:
        """从 Gemini 响应中提取首个候选文本。"""

        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Gemini generateContent returned no candidates: {data}")
        first_candidate = cast(dict[str, Any], candidates[0])
        content = cast(dict[str, Any], first_candidate.get("content") or {})
        parts = content.get("parts") or []
        texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
        return "".join(texts).strip()


class LoggingChatModel(BaseChatModel):
    """给 LangChain ChatModel 增加调用日志记录。"""

    wrapped: BaseChatModel
    model_config_id: int | None = None
    config_type: str
    provider: str
    configured_model_name: str

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        """返回被包装模型类型。"""

        return f"logged-{self.wrapped._llm_type}"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """同步调用被包装模型并记录日志。"""

        del run_manager
        started_at = timezone.now()
        started = time.perf_counter()
        prompt_chars = _messages_chars(messages)
        try:
            message = self.wrapped.invoke(messages, stop=stop, **kwargs)
            output_text = _message_text(message)
            _schedule_model_call_log(
                config_type=self.config_type,
                provider=self.provider,
                model_name=self.configured_model_name,
                status="success",
                model_config_id=self.model_config_id,
                prompt_chars=prompt_chars,
                response_chars=len(output_text),
                latency_ms=_elapsed_ms(started),
                started_at=started_at,
                completed_at=timezone.now(),
            )
            return _message_to_chat_result(message, self.configured_model_name)
        except Exception as exc:
            _schedule_model_call_log(
                config_type=self.config_type,
                provider=self.provider,
                model_name=self.configured_model_name,
                status="failed",
                model_config_id=self.model_config_id,
                prompt_chars=prompt_chars,
                latency_ms=_elapsed_ms(started),
                error_message=str(exc),
                started_at=started_at,
                completed_at=timezone.now(),
            )
            raise

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """异步调用被包装模型并记录日志。"""

        del run_manager
        started_at = timezone.now()
        started = time.perf_counter()
        prompt_chars = _messages_chars(messages)
        try:
            message = await self.wrapped.ainvoke(messages, stop=stop, **kwargs)
            output_text = _message_text(message)
            await record_model_call(
                config_type=self.config_type,
                provider=self.provider,
                model_name=self.configured_model_name,
                status="success",
                model_config_id=self.model_config_id,
                prompt_chars=prompt_chars,
                response_chars=len(output_text),
                latency_ms=_elapsed_ms(started),
                started_at=started_at,
                completed_at=timezone.now(),
            )
            return _message_to_chat_result(message, self.configured_model_name)
        except Exception as exc:
            await record_model_call(
                config_type=self.config_type,
                provider=self.provider,
                model_name=self.configured_model_name,
                status="failed",
                model_config_id=self.model_config_id,
                prompt_chars=prompt_chars,
                latency_ms=_elapsed_ms(started),
                error_message=str(exc),
                started_at=started_at,
                completed_at=timezone.now(),
            )
            raise


def _message_to_chat_result(message: BaseMessage, model_name: str) -> ChatResult:
    """把单条 AIMessage 转换为 ChatResult。"""

    return ChatResult(
        generations=[
            ChatGeneration(
                message=AIMessage(content=_message_text(message)),
                generation_info={"model": model_name},
            )
        ],
        llm_output={},
    )


def _message_text(message: BaseMessage) -> str:
    """提取 LangChain 消息中的文本内容。"""

    content = message.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(parts)


def _messages_chars(messages: list[BaseMessage]) -> int:
    """统计输入消息字符数。"""

    return sum(len(_message_text(message)) for message in messages)


def _elapsed_ms(started: float) -> int:
    """计算耗时毫秒。"""

    return int((time.perf_counter() - started) * 1000)


def _schedule_model_call_log(**kwargs: Any) -> None:
    """同步路径中尽力调度日志写入。"""

    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(record_model_call(**kwargs))
        return
    loop.create_task(record_model_call(**kwargs))


def _create_gemini_generate_content_llm(
    *,
    model: str,
    api_key: str,
    base_url: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> BaseChatModel:
    """创建 Gemini generateContent 兼容协议客户端。"""

    return GeminiGenerateContentChatModel(
        model_name=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _create_chat_model(
    *,
    protocol: str,
    model: str,
    api_key: str,
    base_url: str = "",
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> BaseChatModel:
    """按后台选择的协议创建文本模型客户端。"""

    resolved_temperature = _resolve_temperature(model, temperature)
    if _is_anthropic_protocol(protocol):
        return _create_anthropic_llm(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=resolved_temperature,
            max_tokens=max_tokens,
        )
    if _is_gemini_generate_content_protocol(protocol):
        return _create_gemini_generate_content_llm(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=resolved_temperature,
            max_tokens=max_tokens,
        )
    return _create_openai_compatible_llm(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=resolved_temperature,
        max_tokens=max_tokens,
    )


async def create_configured_llm(
    config_type: str,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> BaseChatModel:
    """创建文本生成模型客户端，优先使用管理后台模型配置。"""

    config = await get_enabled_model_config(config_type)
    if config is None:
        raise ValueError(f"请先在管理后台配置启用的模型：{config_type} 或 default")

    llm = _create_chat_model(
        protocol=config.provider,
        model=model or config.model_name,
        api_key=config.api_key,
        base_url=config.api_base_url,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return LoggingChatModel(
        wrapped=llm,
        model_config_id=config.id,
        config_type=config_type,
        provider=config.provider,
        configured_model_name=model or config.model_name,
    )
