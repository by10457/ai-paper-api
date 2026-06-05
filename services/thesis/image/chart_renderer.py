"""matplotlib 图表渲染实现。"""

import asyncio
import logging
from functools import lru_cache
from typing import Any, cast

logger = logging.getLogger(__name__)


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
