"""论文图片渲染通用工具。"""

import logging

from PIL import Image

logger = logging.getLogger(__name__)


def summarize_render_error(exc: Exception) -> str:
    """压缩渲染错误，避免日志输出整段浏览器堆栈。"""

    text = str(exc).strip()
    if not text:
        text = exc.__class__.__name__
    return text.splitlines()[0][:500]


def auto_crop_whitespace_fast(image_path: str, padding: int = 20) -> str:
    """快速裁剪图片四周的纯白留白区域（基于 numpy 加速）。"""

    try:
        import numpy as np
    except ImportError:
        logger.debug("numpy 不可用，跳过白边裁剪")
        return image_path

    with Image.open(image_path) as opened_img:
        img: Image.Image = opened_img if opened_img.mode == "RGB" else opened_img.convert("RGB")

        arr = np.array(img)
        non_white = np.any(arr < 250, axis=2)
        if not non_white.any():
            return image_path

        rows = np.any(non_white, axis=1)
        cols = np.any(non_white, axis=0)
        rmin, rmax = np.where(rows)[0][[0, -1]]
        cmin, cmax = np.where(cols)[0][[0, -1]]

        top = max(0, int(rmin) - padding)
        bottom = min(img.height, int(rmax) + 1 + padding)
        left = max(0, int(cmin) - padding)
        right = min(img.width, int(cmax) + 1 + padding)

        cropped = img.crop((left, top, right, bottom))
        cropped.save(image_path)

    return image_path
