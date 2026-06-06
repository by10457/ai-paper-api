"""AI 图片生成器实现。"""

import asyncio
import base64
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

import httpx
from PIL import Image
from tortoise import timezone

from llm.call_logger import record_model_call
from services.thesis.generation.concurrency import image_model_slot

IMAGE_MODEL_TIMEOUT_SECONDS = 45.0

_STYLE_MAP = {
    "concept_illustration": "clean flat design, minimalist concept illustration, soft muted colors, white background",
    "data_visualization": "clean infographic style, flat design data chart, professional color palette, white background",
    "process_flow": "clean flat illustration of a process flow, minimalist icons, soft pastel colors, white background",
    "architecture": "clean system architecture diagram, flat design, professional blue-gray palette, white background",
    "comparison": "clean side-by-side comparison infographic, flat minimalist style, white background",
}


def _style_description(style: str) -> str:
    """获取论文插图风格描述。"""

    return _STYLE_MAP.get(
        style,
        "clean flat design illustration, minimalist academic style, muted professional colors, white background",
    )


def _build_academic_image_prompt(description: str, style_desc: str) -> str:
    """生成通用学术插图提示词。"""

    return (
        f"Generate a professional academic illustration for a research paper.\n\n"
        f"Description: {description}\n\n"
        f"Visual Style: {style_desc}\n\n"
        f"CRITICAL RULES:\n"
        f"- If any text labels appear in the image, they MUST be in Simplified Chinese (简体中文). "
        f"NEVER use Traditional Chinese characters.\n"
        f"- Use clean, flat design with generous white space.\n"
        f"- Avoid dark backgrounds, neon colors, or sci-fi aesthetics.\n"
        f"- The illustration should look suitable for an academic paper.\n"
        f"- Use soft, professional colors (light blue, light gray, white, pastel tones)."
    )


class ImageGenerator(ABC):
    """AI 生图模型抽象接口。"""

    @abstractmethod
    async def generate(
        self,
        description: str,
        style: str,
        aspect_ratio: str,
        output_path: str,
    ) -> str:
        """生成图片并保存到 output_path，返回实际路径。"""


class LazyImageGenerator(ImageGenerator):
    """延迟初始化真实图片生成器，避免 Mermaid 成功时触发图片模型配置读取。"""

    def __init__(self, factory: Callable[[], Awaitable[ImageGenerator]]) -> None:
        self._factory = factory
        self._generator: ImageGenerator | None = None
        self._lock = asyncio.Lock()

    async def generate(
        self,
        description: str,
        style: str,
        aspect_ratio: str,
        output_path: str,
    ) -> str:
        """按需创建真实生成器，再转发本次生图请求。"""

        generator = await self._get_generator()
        return await generator.generate(description, style, aspect_ratio, output_path)

    async def _get_generator(self) -> ImageGenerator:
        """返回真实图片生成器，首次使用时创建。"""

        if self._generator is not None:
            return self._generator
        async with self._lock:
            if self._generator is None:
                self._generator = await self._factory()
        return self._generator


class PlaceholderImageGenerator(ImageGenerator):
    """占位实现：生成纯白本地占位图，不暴露提示词。"""

    async def generate(
        self,
        description: str,
        style: str,
        aspect_ratio: str,
        output_path: str,
    ) -> str:
        """生成空白占位图，供未配置图片模型或测试场景使用。"""

        ratios = {
            "16:9": (1024, 576),
            "4:3": (1024, 768),
            "1:1": (1024, 1024),
        }
        width, height = ratios.get(aspect_ratio, (1024, 576))

        image = Image.new("RGB", (width, height), color=(255, 255, 255))
        image.save(output_path)
        return output_path


class GenerateContentImageGenerator(ImageGenerator):
    """通过 Gemini generateContent 协议调用文生图能力。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://generativelanguage.googleapis.com",
        model_config_id: int | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.model_config_id = model_config_id

    async def generate(
        self,
        description: str,
        style: str,
        aspect_ratio: str,
        output_path: str,
    ) -> str:
        """调用 generateContent 图片协议生成论文插图。"""

        prompt = _build_academic_image_prompt(description, _style_description(style))
        real_aspect = aspect_ratio if aspect_ratio in ["1:1", "3:4", "4:3", "9:16", "16:9"] else "16:9"
        started_at = timezone.now()
        started = time.perf_counter()

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {"aspectRatio": real_aspect, "imageSize": "1K"},
            },
        }

        timeout = httpx.Timeout(IMAGE_MODEL_TIMEOUT_SECONDS, connect=10.0)
        async with image_model_slot(), httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.post(self._build_url(), json=payload)
                resp.raise_for_status()
            except httpx.TimeoutException:
                await _record_image_call(
                    provider="gemini-generate-content",
                    model_name=self.model,
                    model_config_id=self.model_config_id,
                    prompt=prompt,
                    status="failed",
                    latency_ms=_elapsed_ms(started),
                    started_at=started_at,
                    error_message=f"图片模型调用超时（超过 {int(IMAGE_MODEL_TIMEOUT_SECONDS)} 秒）",
                )
                raise RuntimeError(f"图片模型调用超时（超过 {int(IMAGE_MODEL_TIMEOUT_SECONDS)} 秒）") from None
            except httpx.HTTPStatusError as exc:
                error_message = self._build_http_error_message(exc.response)
                await _record_image_call(
                    provider="gemini-generate-content",
                    model_name=self.model,
                    model_config_id=self.model_config_id,
                    prompt=prompt,
                    status="failed",
                    latency_ms=_elapsed_ms(started),
                    started_at=started_at,
                    error_message=error_message,
                )
                raise RuntimeError(error_message) from None

            base64_data = self._extract_base64_image(resp.json())
            with open(output_path, "wb") as file:
                file.write(base64.b64decode(base64_data))

        await _record_image_call(
            provider="gemini-generate-content",
            model_name=self.model,
            model_config_id=self.model_config_id,
            prompt=prompt,
            status="success",
            latency_ms=_elapsed_ms(started),
            started_at=started_at,
            response_chars=len(base64_data),
        )
        return output_path

    def _extract_base64_image(self, data: dict) -> str:
        """从 generateContent 响应中提取图片 base64 内容。"""

        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"Image model API returned no candidates. Full response: {data}")

        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            if "inlineData" in part:
                base64_data = part["inlineData"].get("data")
                if base64_data:
                    return str(base64_data)
        raise RuntimeError(f"Image model API returned no image section in parts: {parts}")

    def _build_url(self) -> str:
        """生成 Gemini generateContent 图片请求地址。"""

        api_root = self.base_url if self.base_url.endswith("/v1beta") else f"{self.base_url}/v1beta"
        return f"{api_root}/models/{self.model}:generateContent?key={self.api_key}"

    def _build_safe_url(self) -> str:
        """生成脱敏后的 Gemini generateContent 请求地址，用于日志。"""

        api_root = self.base_url if self.base_url.endswith("/v1beta") else f"{self.base_url}/v1beta"
        return f"{api_root}/models/{self.model}:generateContent?key=***"

    def _build_http_error_message(self, response: httpx.Response) -> str:
        """生成不包含 API Key 的 HTTP 错误信息。"""

        response_text = response.text[:500]
        return (
            f"图片模型 generateContent 调用失败: status={response.status_code}, "
            f"url={self._build_safe_url()}, response={response_text}"
        )


class OpenAIImageGenerator(ImageGenerator):
    """通过 OpenAI Images API 协议调用文生图能力。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com",
        model_config_id: int | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.model_config_id = model_config_id

    async def generate(
        self,
        description: str,
        style: str,
        aspect_ratio: str,
        output_path: str,
    ) -> str:
        """调用 OpenAI Images API 生成论文插图。"""

        prompt = _build_academic_image_prompt(description, _style_description(style))
        started_at = timezone.now()
        started = time.perf_counter()
        payload = {
            "model": self.model,
            "prompt": prompt,
            "size": self._resolve_size(aspect_ratio),
            "n": 1,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        timeout = httpx.Timeout(IMAGE_MODEL_TIMEOUT_SECONDS, connect=10.0)
        async with image_model_slot(), httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.post(self._build_url(), headers=headers, json=payload)
                resp.raise_for_status()
            except httpx.TimeoutException:
                await _record_image_call(
                    provider="openai-image-generations",
                    model_name=self.model,
                    model_config_id=self.model_config_id,
                    prompt=prompt,
                    status="failed",
                    latency_ms=_elapsed_ms(started),
                    started_at=started_at,
                    error_message=f"图片模型调用超时（超过 {int(IMAGE_MODEL_TIMEOUT_SECONDS)} 秒）",
                )
                raise RuntimeError(f"图片模型调用超时（超过 {int(IMAGE_MODEL_TIMEOUT_SECONDS)} 秒）") from None
            except httpx.HTTPStatusError as exc:
                error_message = self._build_http_error_message(exc.response)
                await _record_image_call(
                    provider="openai-image-generations",
                    model_name=self.model,
                    model_config_id=self.model_config_id,
                    prompt=prompt,
                    status="failed",
                    latency_ms=_elapsed_ms(started),
                    started_at=started_at,
                    error_message=error_message,
                )
                raise RuntimeError(error_message) from None

            image_bytes = await self._extract_image_bytes(resp.json(), client)
            with open(output_path, "wb") as file:
                file.write(image_bytes)

        await _record_image_call(
            provider="openai-image-generations",
            model_name=self.model,
            model_config_id=self.model_config_id,
            prompt=prompt,
            status="success",
            latency_ms=_elapsed_ms(started),
            started_at=started_at,
            response_chars=len(image_bytes),
        )
        return output_path

    def _resolve_size(self, aspect_ratio: str) -> str:
        """把论文插图比例映射为 OpenAI Images API 支持的尺寸。"""

        if aspect_ratio in {"9:16", "3:4"}:
            return "1024x1536"
        if aspect_ratio in {"16:9", "4:3"}:
            return "1536x1024"
        return "1024x1024"

    async def _extract_image_bytes(self, data: dict, client: httpx.AsyncClient) -> bytes:
        """从 OpenAI Images API 响应中提取图片内容。"""

        items = data.get("data", [])
        if not items:
            raise RuntimeError(f"Image model API returned no data. Full response: {data}")

        first_item = items[0]
        base64_data = first_item.get("b64_json")
        if base64_data:
            return base64.b64decode(base64_data)

        image_url = first_item.get("url")
        if image_url:
            return await self._download_image_url(str(image_url), client)

        raise RuntimeError(f"Image model API returned no image content. First item: {first_item}")

    async def _download_image_url(self, image_url: str, client: httpx.AsyncClient) -> bytes:
        """下载 Images API 返回的临时图片地址。"""

        try:
            resp = await client.get(image_url)
            resp.raise_for_status()
        except httpx.TimeoutException:
            raise RuntimeError(f"图片下载超时（超过 {int(IMAGE_MODEL_TIMEOUT_SECONDS)} 秒）") from None
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"图片下载失败: status={exc.response.status_code}, url={image_url}") from None
        return resp.content

    def _build_url(self) -> str:
        """生成 OpenAI Images API 请求地址。"""

        api_root = self.base_url if self.base_url.endswith("/v1") else f"{self.base_url}/v1"
        return f"{api_root}/images/generations"

    def _build_safe_url(self) -> str:
        """生成脱敏后的 OpenAI Images API 请求地址，用于日志。"""

        return self._build_url()

    def _build_http_error_message(self, response: httpx.Response) -> str:
        """生成不包含 API Key 的 HTTP 错误信息。"""

        response_text = response.text[:500]
        return (
            f"图片模型 OpenAI Images API 调用失败: status={response.status_code}, "
            f"url={self._build_safe_url()}, response={response_text}"
        )


def _elapsed_ms(started: float) -> int:
    """计算耗时毫秒。"""

    return int((time.perf_counter() - started) * 1000)


async def _record_image_call(
    *,
    provider: str,
    model_name: str,
    model_config_id: int | None,
    prompt: str,
    status: str,
    latency_ms: int,
    started_at: object,
    response_chars: int = 0,
    error_message: str | None = None,
) -> None:
    """记录图片模型调用日志。"""

    await record_model_call(
        config_type="figure",
        call_type="image",
        provider=provider,
        model_name=model_name,
        model_config_id=model_config_id,
        status=status,
        prompt_chars=len(prompt),
        response_chars=response_chars,
        latency_ms=latency_ms,
        error_message=error_message,
        started_at=started_at,
        completed_at=timezone.now(),
    )
