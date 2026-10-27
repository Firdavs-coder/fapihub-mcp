"""MCP server exposing FAPIHUB image tools."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from fapihub_mcp import __version__
from fapihub_mcp.client import FapihubClient, FapihubError, Settings, validate_image_path

mcp = MCPServer(
    name="fapihub",
    title="FAPIHUB Background Removal",
    version=__version__,
    website_url="https://fapihub.com",
    instructions=(
        "Image tools backed by the FAPIHUB API. Each tool reads a local image file, "
        "writes the result next to it (or to output_path) and returns the saved path. "
        "Every call uses one request from the user's FAPIHUB quota."
    ),
)

# Tools write a new file and call a paid external API.
WRITE_TOOL = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)

ImagePath = Annotated[str, Field(description="Path to a local JPG, PNG, WEBP, BMP or GIF image (1 KB to 10 MB).")]
OutputPath = Annotated[
    str | None,
    Field(description="Where to save the result. Defaults to '<name>_<operation>.<ext>' next to the input image."),
]
Model = Annotated[
    Literal["falcon", "aurora", "ghost"],
    Field(description="Segmentation model. 'falcon' is the default and works well for most images."),
]
Color = Annotated[str, Field(description="Color as hex ('#FF8C00', '#FF8C0080') or RGB(A) ('255, 140, 0' or '255, 140, 0, 255').")]

EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}

_client: FapihubClient | None = None


def get_client() -> FapihubClient:
    global _client
    if _client is None:
        _client = FapihubClient(Settings.from_env())
    return _client


def set_client(client: FapihubClient | None) -> None:
    global _client
    _client = client


def parse_color(value: str) -> str:
    """Normalize a color to the '(r, g, b, a)' form the API expects."""
    text = value.strip()
    hex_match = re.fullmatch(r"#?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", text)
    if hex_match:
        rgb, alpha = hex_match.groups()
        channels = [int(rgb[i : i + 2], 16) for i in (0, 2, 4)]
        channels.append(int(alpha, 16) if alpha else 255)
    else:
        inner = re.sub(r"^rgba?", "", text, flags=re.IGNORECASE).strip("()[] ")
        parts = [p for p in re.split(r"[\s,]+", inner) if p]
        if len(parts) not in (3, 4) or not all(p.isdigit() for p in parts):
            raise ToolError(f"Invalid color '{value}'. Use hex like '#FF8C00' or RGB(A) like '255, 140, 0, 255'.")
        channels = [int(p) for p in parts] + ([255] if len(parts) == 3 else [])
        if any(c > 255 for c in channels):
            raise ToolError(f"Invalid color '{value}'. Channel values must be between 0 and 255.")
    return "({}, {}, {}, {})".format(*channels)


def _default_output_path(source: Path, operation: str, extension: str) -> Path:
    candidate = source.with_name(f"{source.stem}_{operation}{extension}")
    counter = 1
    while candidate.exists():
        candidate = source.with_name(f"{source.stem}_{operation}_{counter}{extension}")
        counter += 1
    return candidate


async def _run(endpoint: str, operation: str, image_path: str, output_path: str | None, fields: dict[str, str]) -> str:
    try:
        source = validate_image_path(image_path)
        result = await get_client().process(endpoint, source, fields)
    except FapihubError as e:
        raise ToolError(str(e)) from e

    extension = EXTENSIONS.get(result.content_type, ".png")
    if output_path:
        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        target = _default_output_path(source, operation, extension)

    target.write_bytes(result.content)
    return f"Saved {result.content_type} ({len(result.content) / 1024:.0f} KB) to {target}"


@mcp.tool(annotations=WRITE_TOOL)
async def remove_background(image_path: ImagePath, model: Model = "falcon", output_path: OutputPath = None) -> str:
    """Remove the background from an image, producing a transparent PNG cutout of the subject."""
    return await _run("", "nobg", image_path, output_path, {"model": model})


@mcp.tool(annotations=WRITE_TOOL)
async def create_mask(image_path: ImagePath, model: Model = "falcon", output_path: OutputPath = None) -> str:
    """Create a black-and-white subject mask (white = subject, black = background) for an image."""
    return await _run("mask/", "mask", image_path, output_path, {"model": model})


@mcp.tool(annotations=WRITE_TOOL)
async def blur_background(
    image_path: ImagePath,
    radius: Annotated[int, Field(ge=1, le=50, description="Blur strength, 1-50.")] = 10,
    output_path: OutputPath = None,
) -> str:
    """Keep the subject sharp and blur the background (portrait-style bokeh)."""
    return await _run("blur/", "blur", image_path, output_path, {"radius": str(radius)})


@mcp.tool(annotations=WRITE_TOOL)
async def color_background(image_path: ImagePath, color: Color, output_path: OutputPath = None) -> str:
    """Replace the background with a solid color."""
    return await _run("color/", "color", image_path, output_path, {"bgcolor": parse_color(color)})


@mcp.tool(annotations=WRITE_TOOL)
async def gradient_background(
    image_path: ImagePath,
    top_color: Color,
    bottom_color: Color,
    output_path: OutputPath = None,
) -> str:
    """Replace the background with a vertical gradient from top_color to bottom_color."""
    fields = {"top_color": parse_color(top_color), "bottom_color": parse_color(bottom_color)}
    return await _run("gradient/", "gradient", image_path, output_path, fields)


@mcp.tool(annotations=WRITE_TOOL)
async def add_shadow(
    image_path: ImagePath,
    shadow_color: Color = "0, 0, 0, 150",
    offset_x: Annotated[int, Field(description="Horizontal shadow offset in pixels.")] = 10,
    offset_y: Annotated[int, Field(description="Vertical shadow offset in pixels.")] = 10,
    blur_radius: Annotated[int, Field(ge=0, description="Shadow softness in pixels.")] = 15,
    output_path: OutputPath = None,
) -> str:
    """Cut out the subject and add a drop shadow behind it on a transparent background."""
    fields = {
        "shadow_color": parse_color(shadow_color),
        "offset": f"({offset_x}, {offset_y})",
        "blur_radius": str(blur_radius),
    }
    return await _run("shadow/", "shadow", image_path, output_path, fields)
