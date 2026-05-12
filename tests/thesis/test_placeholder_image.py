import asyncio
from pathlib import Path

from PIL import Image

from services.thesis.image_renderer import PlaceholderImageGenerator


def test_placeholder_image_is_blank_white(tmp_path: Path) -> None:
    output = tmp_path / "placeholder.png"

    result = asyncio.run(
        PlaceholderImageGenerator().generate(
            description="提示词不应出现在图片里",
            style="concept_illustration",
            aspect_ratio="16:9",
            output_path=str(output),
        )
    )

    assert result == str(output)
    assert output.exists()
    with Image.open(output) as image:
        colors = image.convert("RGB").getcolors(maxcolors=10)
    assert colors == [(1024 * 576, (255, 255, 255))]
