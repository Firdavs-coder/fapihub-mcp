import httpx
import pytest
from mcp import Client

from fapihub_mcp.client import FapihubClient, Settings
from fapihub_mcp.server import mcp, parse_color, set_client

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 2048


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 4096)
    return path


@pytest.fixture
def api(request):
    """Install a fake FAPIHUB API; returns the list of captured requests."""
    handler = getattr(request, "param", None) or (
        lambda req: httpx.Response(200, content=PNG_BYTES, headers={"Content-Type": "image/png"})
    )
    captured = []

    def record(req):
        captured.append(req)
        return handler(req)

    set_client(FapihubClient(Settings(api_key="bg_live_sk_test"), transport=httpx.MockTransport(record)))
    yield captured
    set_client(None)


async def call(name, args):
    async with Client(mcp) as client:
        return await client.call_tool(name, args)


def text(result):
    return result.content[0].text


async def test_lists_all_tools():
    async with Client(mcp) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert names == {
        "remove_background",
        "create_mask",
        "blur_background",
        "color_background",
        "gradient_background",
        "add_shadow",
    }


async def test_remove_background_saves_next_to_input(api, image):
    result = await call("remove_background", {"image_path": str(image)})

    assert not result.is_error, text(result)
    output = image.with_name("photo_nobg.png")
    assert output.read_bytes() == PNG_BYTES
    assert str(output) in text(result)

    req = api[0]
    assert str(req.url) == "https://fapihub.com/v2/rembg/"
    assert req.headers["ApiKey"] == "bg_live_sk_test"
    assert req.headers["User-Agent"].startswith("fapihub-mcp/")
    body = req.content.decode("latin-1")
    assert 'name="model"\r\n\r\nfalcon' in body
    assert 'name="image"; filename="photo.jpg"' in body
    assert "Content-Type: image/jpeg" in body


async def test_does_not_overwrite_previous_results(api, image):
    await call("remove_background", {"image_path": str(image)})
    await call("remove_background", {"image_path": str(image)})
    assert image.with_name("photo_nobg_1.png").exists()


async def test_explicit_output_path(api, image, tmp_path):
    target = tmp_path / "out" / "cutout.png"
    result = await call("remove_background", {"image_path": str(image), "output_path": str(target)})
    assert not result.is_error
    assert target.read_bytes() == PNG_BYTES


@pytest.mark.parametrize(
    ("tool", "args", "path", "fields"),
    [
        ("create_mask", {"model": "aurora"}, "/v2/rembg/mask/", {"model": "aurora"}),
        ("blur_background", {"radius": 20}, "/v2/rembg/blur/", {"radius": "20"}),
        ("color_background", {"color": "#FF8C00"}, "/v2/rembg/color/", {"bgcolor": "(255, 140, 0, 255)"}),
        (
            "gradient_background",
            {"top_color": "255,140,0", "bottom_color": "#E52E71"},
            "/v2/rembg/gradient/",
            {"top_color": "(255, 140, 0, 255)", "bottom_color": "(229, 46, 113, 255)"},
        ),
        (
            "add_shadow",
            {},
            "/v2/rembg/shadow/",
            {"shadow_color": "(0, 0, 0, 150)", "offset": "(10, 10)", "blur_radius": "15"},
        ),
    ],
)
async def test_endpoints_and_fields(api, image, tool, args, path, fields):
    result = await call(tool, {"image_path": str(image), **args})

    assert not result.is_error, text(result)
    assert api[0].url.path == path
    body = api[0].content.decode("latin-1")
    for key, value in fields.items():
        assert f'name="{key}"\r\n\r\n{value}' in body


async def test_invalid_model_is_rejected_before_calling_api(api, image):
    result = await call("remove_background", {"image_path": str(image), "model": "nope"})
    assert result.is_error
    assert api == []


async def test_blur_radius_limit(api, image):
    result = await call("blur_background", {"image_path": str(image), "radius": 99})
    assert result.is_error
    assert api == []


async def test_missing_file(api, tmp_path):
    result = await call("remove_background", {"image_path": str(tmp_path / "missing.png")})
    assert result.is_error
    assert "not found" in text(result)
    assert api == []


async def test_unsupported_extension(api, tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"\x00" * 4096)
    result = await call("remove_background", {"image_path": str(path)})
    assert result.is_error
    assert "Unsupported image type" in text(result)
    assert api == []


async def test_too_small_file(api, tmp_path):
    path = tmp_path / "tiny.png"
    path.write_bytes(b"\x00" * 10)
    result = await call("remove_background", {"image_path": str(path)})
    assert result.is_error
    assert "minimum is 1 KB" in text(result)
    assert api == []


def _error(status, message, headers=None):
    return lambda req: httpx.Response(
        status, json={"error": {"code": "x", "message": message}}, headers=headers or {}
    )


@pytest.mark.parametrize(
    ("api", "expected"),
    [
        (_error(401, "The provided API key is invalid or inactive"), "Check FAPIHUB_API_KEY"),
        (_error(403, "Monthly request limit reached."), "https://fapihub.com/billing/"),
        (_error(429, "Too many requests", {"Retry-After": "12"}), "Retry after 12 seconds"),
        (_error(502, "upstream down"), "FAPIHUB API error (502): upstream down"),
    ],
    indirect=["api"],
)
async def test_api_errors_become_tool_errors(api, image, expected):
    result = await call("remove_background", {"image_path": str(image)})
    assert result.is_error
    assert expected in text(result)
    assert not image.with_name("photo_nobg.png").exists()


def test_parse_color():
    assert parse_color("#ff8c00") == "(255, 140, 0, 255)"
    assert parse_color("#FF8C0080") == "(255, 140, 0, 128)"
    assert parse_color("rgba(1, 2, 3, 4)") == "(1, 2, 3, 4)"
    assert parse_color("(0, 0, 0, 150)") == "(0, 0, 0, 150)"


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("FAPIHUB_API_KEY", raising=False)
    with pytest.raises(Exception, match="FAPIHUB_API_KEY is not set"):
        Settings.from_env()
