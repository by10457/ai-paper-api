import asyncio
import base64
import json
import logging
import os
import re
import shutil
import tempfile
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import httpx
from PIL import Image

logger = logging.getLogger(__name__)
IMAGE_MODEL_TIMEOUT_SECONDS = 45.0
FIGURE_RENDER_CONCURRENCY = 2


def _mermaid_node_id(prefix: str, index: int) -> str:
    """生成 Mermaid flowchart 安全节点 ID。"""

    return f"{prefix}_{index}"


def _flowchart_label(text: str) -> str:
    """转义 flowchart 节点标签。"""

    return text.replace('"', '\\"')


def _normalize_mermaid_code(mermaid_code: str) -> str:
    """修正当前 Mermaid CLI 不支持的常见图类型。"""

    code = mermaid_code.strip()
    code = re.sub(r"^```(?:mermaid)?\s*", "", code, flags=re.IGNORECASE)
    code = re.sub(r"\s*```$", "", code).strip()
    if code.lower().startswith("usecasediagram"):
        return _convert_usecase_diagram_to_flowchart(code)
    return code


def _convert_usecase_diagram_to_flowchart(mermaid_code: str) -> str:
    """把 usecaseDiagram 转为 mmdc 支持更稳定的 flowchart。"""

    lines = [line.strip() for line in mermaid_code.splitlines() if line.strip()]
    alias_map: dict[str, str] = {}
    output: list[str] = ["flowchart TD"]
    actor_index = 0
    package_index = 0

    for line in lines[1:]:
        if line == "}":
            output.append("end")
            continue

        package_match = re.match(r'package\s+"(.+?)"\s*\{', line)
        if package_match:
            package_index += 1
            package_id = _mermaid_node_id("PKG", package_index)
            output.append(f'    subgraph {package_id}["{_flowchart_label(package_match.group(1))}"]')
            continue

        actor_match = re.match(r"actor\s+(.+?)(?:\s+as\s+([A-Za-z0-9_]+))?$", line)
        if actor_match:
            actor_index += 1
            actor_label = actor_match.group(1).strip().strip('"')
            actor_id = actor_match.group(2) or _mermaid_node_id("ACTOR", actor_index)
            alias_map[actor_label] = actor_id
            alias_map[actor_id] = actor_id
            output.append(f'    {actor_id}["{_flowchart_label(actor_label)}"]')
            continue

        usecase_match = re.match(r'usecase\s+"(.+?)"\s+as\s+([A-Za-z0-9_]+)', line)
        if usecase_match:
            label, alias = usecase_match.groups()
            alias_map[alias] = alias
            output.append(f'    {alias}(["{_flowchart_label(label)}"])')
            continue

        relation_match = re.match(r"(.+?)\s*-->\s*(.+?)(?:\s*:\s*(.+))?$", line)
        if relation_match:
            source, target, label = relation_match.groups()
            source_id = alias_map.get(source.strip().strip('"'), source.strip())
            target_id = alias_map.get(target.strip().strip('"'), target.strip())
            if label:
                output.append(f'    {source_id} -->|"{_flowchart_label(label.strip())}"| {target_id}')
            else:
                output.append(f"    {source_id} --> {target_id}")

    return "\n".join(output)


def _summarize_render_error(exc: Exception) -> str:
    """压缩渲染错误，避免日志输出整段浏览器堆栈。"""

    text = str(exc).strip()
    if not text:
        text = exc.__class__.__name__
    return text.splitlines()[0][:500]


def _summarize_mermaid_stderr(stderr_text: str) -> str:
    """压缩 Mermaid CLI 错误输出。"""

    return stderr_text.strip().splitlines()[0][:500] if stderr_text.strip() else "未知错误"


def _pick_chart_font_family() -> list[str]:
    """返回适合图表中文显示的字体候选列表。"""
    return [
        "Noto Sans CJK SC",
        "WenQuanYi Zen Hei",
        "PingFang SC",
        "Hiragino Sans GB",
        "Microsoft YaHei",
        "SimHei",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]


def _available_chart_fonts() -> list[tuple[str, str]]:
    """返回 matplotlib 当前可见的字体 (family_name, font_path)。"""
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import font_manager

    for font_path in font_manager.findSystemFonts(fontext="ttf"):
        try:
            font_manager.fontManager.addfont(font_path)
        except RuntimeError:
            logger.debug("字体加载失败，跳过: %s", font_path)

    return [
        (str(item.name or "").strip(), str(getattr(item, "fname", "") or "").strip())
        for item in font_manager.fontManager.ttflist
    ]


@lru_cache
def _resolve_chart_font() -> tuple[str, str | None]:
    """解析并锁定一个真实存在的图表字体，优先中文字体。"""
    aliases: dict[str, tuple[str, ...]] = {
        "Noto Sans CJK SC": (
            "noto sans cjk sc",
            "notosanscjk",
            "noto sans cjk",
            "source han sans sc",
            "sourcehansanssc",
        ),
        "WenQuanYi Zen Hei": (
            "wenquanyi zen hei",
            "wqy-zenhei",
            "wqy zen hei",
        ),
        "PingFang SC": ("pingfang sc",),
        "Hiragino Sans GB": ("hiragino sans gb",),
        "Microsoft YaHei": ("microsoft yahei", "msyh"),
        "SimHei": ("simhei",),
        "Arial Unicode MS": ("arial unicode ms",),
        "DejaVu Sans": ("dejavu sans",),
    }

    available_fonts = _available_chart_fonts()
    normalized_entries = [(name, path, name.lower(), path.lower().replace(" ", "")) for name, path in available_fonts]

    for candidate in _pick_chart_font_family():
        candidate_aliases = aliases.get(candidate, (candidate.lower(),))
        for name, path, lowered_name, lowered_path in normalized_entries:
            if lowered_name == candidate.lower():
                logger.info("图表字体已锁定: %s (%s)", name, path)
                return name, path or None
            if any(alias in lowered_name or alias.replace(" ", "") in lowered_path for alias in candidate_aliases):
                logger.info("图表字体已锁定: %s (%s)", name, path)
                return name, path or None

    logger.warning("未找到可用中文图表字体，回退到 DejaVu Sans")
    return "DejaVu Sans", None


def _auto_crop_whitespace_fast(image_path: str, padding: int = 20) -> str:
    """快速裁剪图片四周的纯白留白区域（基于 numpy 加速）。"""
    try:
        import numpy as np
    except ImportError:
        # numpy 不可用时跳过裁剪
        logger.debug("numpy 不可用，跳过白边裁剪")
        return image_path

    with Image.open(image_path) as opened_img:
        img: Image.Image = opened_img if opened_img.mode == "RGB" else opened_img.convert("RGB")

        arr = np.array(img)
        # 非白色像素的掩码（任一通道 < 250 视为非白）
        non_white = np.any(arr < 250, axis=2)

        if not non_white.any():
            return image_path

        rows = np.any(non_white, axis=1)
        cols = np.any(non_white, axis=0)
        rmin, rmax = np.where(rows)[0][[0, -1]]
        cmin, cmax = np.where(cols)[0][[0, -1]]

        # 加 padding
        top = max(0, int(rmin) - padding)
        bottom = min(img.height, int(rmax) + 1 + padding)
        left = max(0, int(cmin) - padding)
        right = min(img.width, int(cmax) + 1 + padding)

        cropped = img.crop((left, top, right, bottom))
        cropped.save(image_path)

    return image_path


async def render_mermaid(mermaid_code: str, output_path: str) -> str:
    """将 Mermaid 代码渲染为 PNG。"""

    if not shutil.which("mmdc"):
        raise RuntimeError("Mermaid CLI 未安装，无法渲染 Mermaid 图，请安装 @mermaid-js/mermaid-cli")

    normalized_code = _normalize_mermaid_code(mermaid_code)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".mmd", delete=False) as temp_file:
        temp_file.write(normalized_code)
        mmd_path = temp_file.name

    puppeteer_config: dict[str, object] = {
        "args": ["--no-sandbox", "--disable-setuid-sandbox"],
    }
    if executable_path := os.getenv("PUPPETEER_EXECUTABLE_PATH"):
        puppeteer_config["executablePath"] = executable_path

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as temp_config:
        json.dump(puppeteer_config, temp_config, ensure_ascii=False)
        pptr_config_path = temp_config.name

    try:
        proc = await asyncio.create_subprocess_exec(
            "mmdc",
            "-i",
            mmd_path,
            "-o",
            output_path,
            "-p",
            pptr_config_path,
            "-b",
            "white",
            "-w",
            "1024",
            "-s",
            "2",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"Mermaid 渲染失败 (exit {proc.returncode}): {_summarize_mermaid_stderr(stderr.decode())}"
            )
    finally:
        Path(mmd_path).unlink(missing_ok=True)
        Path(pptr_config_path).unlink(missing_ok=True)

    # 渲染成功后裁剪白边
    try:
        _auto_crop_whitespace_fast(output_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Mermaid 图白边裁剪失败，使用原图: %s", exc)

    return output_path


def _render_chart_sync(chart_spec: dict, output_path: str) -> str:
    """同步渲染标准数据图。"""
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import font_manager
    from matplotlib import pyplot as plt

    font_name, font_path = _resolve_chart_font()
    font_prop = (
        font_manager.FontProperties(fname=font_path) if font_path else font_manager.FontProperties(family=font_name)
    )

    # 使用 rc_context 代替全局 rcParams，避免多线程并发渲染时的竞态条件
    rc_overrides = {
        "font.family": [font_name],
        "font.sans-serif": [font_name],
        "axes.unicode_minus": False,
    }

    chart_type = chart_spec["chart_type"]
    title = chart_spec.get("title", "")
    x_label = chart_spec.get("x_label", "")
    y_label = chart_spec.get("y_label", "")
    categories = chart_spec.get("categories", [])
    series = chart_spec.get("series", [])

    with plt.rc_context(rc_overrides):
        fig, ax = plt.subplots(figsize=(10.24, 5.76), dpi=150)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")
        ax.grid(True, color="#D9D9D9", linewidth=0.8, alpha=0.8)
        ax.set_axisbelow(True)

        palette = ["#5B8FF9", "#5D7092", "#5AD8A6", "#F6BD16", "#E8684A"]

        if chart_type == "line":
            x_positions = list(range(len(categories)))
            for index, item in enumerate(series):
                ax.plot(
                    x_positions,
                    item["data"],
                    marker="o",
                    linewidth=2.2,
                    markersize=4.5,
                    color=palette[index % len(palette)],
                    label=item["name"],
                )
            ax.set_xticks(x_positions, categories)
        elif chart_type == "bar":
            x_positions = list(range(len(categories)))
            series_count = len(series)
            bar_width = 0.75 / max(series_count, 1)
            for index, item in enumerate(series):
                offsets = [x - 0.375 + bar_width * 0.5 + index * bar_width for x in x_positions]
                ax.bar(
                    offsets,
                    item["data"],
                    width=bar_width,
                    color=palette[index % len(palette)],
                    label=item["name"],
                )
            ax.set_xticks(x_positions, categories)
        elif chart_type == "pie":
            ax.clear()
            ax.grid(False)
            pie_series = series[0]
            colors = [palette[index % len(palette)] for index in range(len(categories))]
            _, pie_texts, pie_autotexts = cast(
                tuple[Any, list[Any], list[Any]],
                ax.pie(
                    pie_series["data"],
                    labels=categories,
                    autopct="%1.1f%%",
                    startangle=90,
                    counterclock=False,
                    colors=colors,
                    wedgeprops={"edgecolor": "white", "linewidth": 1},
                    textprops={"fontsize": 10},
                ),
            )
            for text in [*pie_texts, *pie_autotexts]:
                text.set_fontproperties(font_prop)
            ax.axis("equal")
        else:
            raise ValueError(f"Unsupported chart_type: {chart_type}")

        ax.set_title(title, fontsize=18, pad=18, fontproperties=font_prop)
        if chart_type != "pie":
            ax.set_xlabel(x_label, fontsize=12, fontproperties=font_prop)
            ax.set_ylabel(y_label, fontsize=12, fontproperties=font_prop)
            for label in [*ax.get_xticklabels(), *ax.get_yticklabels()]:
                label.set_fontproperties(font_prop)
            if any(item.get("name") for item in series):
                ax.legend(frameon=False, prop=font_prop)

        fig.tight_layout()
        fig.savefig(output_path, format="png", facecolor="white", bbox_inches="tight")
        plt.close(fig)
    return output_path


async def render_chart(chart_spec: dict, output_path: str) -> str:
    """将结构化图表数据渲染为 PNG。"""
    return await asyncio.to_thread(_render_chart_sync, chart_spec, output_path)


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


class PlaceholderImageGenerator(ImageGenerator):
    """占位实现：生成纯白本地占位图，不暴露提示词。"""

    async def generate(
        self,
        description: str,
        style: str,
        aspect_ratio: str,
        output_path: str,
    ) -> str:
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
    """通过 Google generateContent 兼容接口调用文生图能力。"""

    def __init__(self, api_key: str, model: str, base_url: str = "https://cdn.12ai.org"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    async def generate(
        self,
        description: str,
        style: str,
        aspect_ratio: str,
        output_path: str,
    ) -> str:
        style_map = {
            "concept_illustration": "clean flat design, minimalist concept illustration, soft muted colors, white background",
            "data_visualization": "clean infographic style, flat design data chart, professional color palette, white background",
            "process_flow": "clean flat illustration of a process flow, minimalist icons, soft pastel colors, white background",
            "architecture": "clean system architecture diagram, flat design, professional blue-gray palette, white background",
            "comparison": "clean side-by-side comparison infographic, flat minimalist style, white background",
        }
        style_desc = style_map.get(
            style,
            "clean flat design illustration, minimalist academic style, muted professional colors, white background",
        )

        prompt = (
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

        # generateContent 生图接口通常支持这些常见比例，异常值降级到论文插图常用的 16:9。
        real_aspect = aspect_ratio if aspect_ratio in ["1:1", "3:4", "4:3", "9:16", "16:9"] else "16:9"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {"aspectRatio": real_aspect, "imageSize": "1K"},
            },
        }

        timeout = httpx.Timeout(IMAGE_MODEL_TIMEOUT_SECONDS, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.post(self._build_url(), json=payload)
                resp.raise_for_status()
            except httpx.TimeoutException:
                raise RuntimeError(f"图片模型调用超时（超过 {int(IMAGE_MODEL_TIMEOUT_SECONDS)} 秒）") from None
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(self._build_http_error_message(exc.response)) from None
            data = resp.json()

            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError(f"Image model API returned no candidates. Full response: {data}")

            parts = candidates[0].get("content", {}).get("parts", [])
            base64_data = None
            for part in parts:
                if "inlineData" in part:
                    base64_data = part["inlineData"].get("data")
                    break

            if not base64_data:
                raise RuntimeError(f"Image model API returned no image section in parts: {parts}")

            with open(output_path, "wb") as f:
                f.write(base64.b64decode(base64_data))

        return output_path

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


async def render_all_figures(
    placeholders: list[dict],
    image_generator: ImageGenerator,
    output_dir: str = "public/output/thesis/images",
) -> dict[int, str | None]:
    """并发渲染所有占位符，返回 {index: path_or_none}。"""

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 限制并发数量，避免图片模型或 Chromium 同时占用太多资源。
    semaphore = asyncio.Semaphore(FIGURE_RENDER_CONCURRENCY)

    async def _render_one(placeholder: dict) -> tuple[int, str | None]:
        index = placeholder["index"]
        output_path = f"{output_dir}/fig_{index}.png"
        method = placeholder.get("render_method")

        max_retries = 1 if method in {"ai_image", "mermaid"} else 2
        attempt = 0
        while attempt < max_retries:
            try:
                async with semaphore:
                    if method == "mermaid":
                        rendered_path = await render_mermaid(placeholder["mermaid_code"], output_path)
                        return index, rendered_path
                    elif method == "chart":
                        rendered_path = await render_chart(placeholder, output_path)
                        return index, rendered_path
                    elif method == "ai_image":
                        rendered_path = await image_generator.generate(
                            description=placeholder.get("description", placeholder.get("caption", "学术插图")),
                            style=placeholder.get("style", "concept_illustration"),
                            aspect_ratio=placeholder.get("aspect_ratio", "16:9"),
                            output_path=output_path,
                        )
                        return index, rendered_path
                    elif method == "fallback":
                        logger.warning("占位符 #%d 为 fallback，跳过渲染", index)
                        return index, None
                    else:
                        logger.warning("占位符 #%d 的 render_method 非法: %s", index, method)
                        return index, None

            except Exception as exc:
                if method == "mermaid":
                    # Mermaid 语法错误重试也没用，直接切到 ai_image 兜底
                    logger.warning("占位符 #%d Mermaid 失败，转 ai_image 兜底: %s", index, _summarize_render_error(exc))
                    method = "ai_image"
                    max_retries = 1
                    attempt = 0
                    continue
                else:
                    attempt += 1
                    if attempt < max_retries:
                        logger.warning(
                            "占位符 #%d 渲染出错，重试 %d/%d: %s",
                            index,
                            attempt,
                            max_retries,
                            _summarize_render_error(exc),
                        )
                        await asyncio.sleep(2)
                    else:
                        logger.warning(
                            "占位符 #%d 渲染失败，跳过该图 (已尝试 %d 次): %s",
                            index,
                            max_retries,
                            _summarize_render_error(exc),
                        )
                        return index, None
        return index, None

    pairs = await asyncio.gather(*[_render_one(item) for item in placeholders])
    return dict(pairs)
