import base64
from io import BytesIO
from pathlib import Path

from PIL import Image


def _image_to_data_uri(image_path: str, output_format: str = "JPEG") -> str:
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    image = Image.open(path)

    if output_format.upper() == "JPEG":
        if image.mode in ("RGBA", "LA"):
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        elif image.mode == "P":
            image = image.convert("RGB")

    buffer = BytesIO()
    image.save(buffer, format=output_format)
    base64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/{output_format.lower()};base64,{base64_str}"
