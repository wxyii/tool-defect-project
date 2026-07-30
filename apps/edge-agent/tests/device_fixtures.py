"""不依赖个人环境的确定性设备文件夹具。"""

from io import BytesIO

from PIL import Image


def png_bytes(*, width: int = 32, height: int = 24, value: int = 127) -> bytes:
    image = Image.new("L", (width, height), color=value)
    output = BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue()


def jpeg_bytes(*, width: int = 32, height: int = 24, value: int = 127) -> bytes:
    image = Image.new("L", (width, height), color=value)
    output = BytesIO()
    image.save(output, format="JPEG", quality=90, optimize=False)
    return output.getvalue()


PNG = png_bytes()
