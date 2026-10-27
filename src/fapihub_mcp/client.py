"""HTTP client for the FAPIHUB background removal API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import httpx

from fapihub_mcp import __version__

DEFAULT_BASE_URL = "https://fapihub.com"
DEFAULT_TIMEOUT = 120.0

# Mirrors the server-side validation. Checking locally first matters because
# the API counts 4xx responses against the user's quota.
CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
}
MAX_FILE_SIZE = 10 * 1024 * 1024
MIN_FILE_SIZE = 1024


class FapihubError(Exception):
    """An error with a message meant to be shown to the model."""


@dataclass
class ProcessedImage:
    content: bytes
    content_type: str


@dataclass
class Settings:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls) -> Settings:
        api_key = os.environ.get("FAPIHUB_API_KEY", "").strip()
        if not api_key:
            raise FapihubError(
                "FAPIHUB_API_KEY is not set. Create an API key at "
                "https://fapihub.com/dashboard/ and pass it to the MCP server "
                "as the FAPIHUB_API_KEY environment variable."
            )
        return cls(
            api_key=api_key,
            base_url=os.environ.get("FAPIHUB_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            timeout=float(os.environ.get("FAPIHUB_TIMEOUT", DEFAULT_TIMEOUT)),
        )


def validate_image_path(image_path: str) -> Path:
    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise FapihubError(f"Image file not found: {path}")

    if path.suffix.lower() not in CONTENT_TYPES:
        allowed = ", ".join(sorted(CONTENT_TYPES))
        raise FapihubError(f"Unsupported image type '{path.suffix}'. Allowed: {allowed}")

    size = path.stat().st_size
    if size > MAX_FILE_SIZE:
        raise FapihubError(f"Image is {size / 1024 / 1024:.1f} MB; the maximum is 10 MB.")
    if size < MIN_FILE_SIZE:
        raise FapihubError(f"Image is {size} bytes; the minimum is 1 KB.")

    return path


class FapihubClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._transport = transport

    async def process(self, endpoint: str, image_path: Path, fields: dict[str, str]) -> ProcessedImage:
        """POST an image to /v2/rembg/<endpoint> and return the resulting image."""
        files = {
            "image": (image_path.name, image_path.read_bytes(), CONTENT_TYPES[image_path.suffix.lower()]),
        }
        response = await self._request("POST", f"/v2/rembg/{endpoint}", files=files, data=fields)
        _raise_for_status(response)
        return ProcessedImage(
            content=response.content,
            content_type=response.headers.get("Content-Type", "image/png").split(";")[0].strip(),
        )

    async def get_usage(self) -> dict:
        """Plan, limits and current usage. Free: not counted against quota."""
        response = await self._request("GET", "/v2/account/usage/")
        if response.status_code == 404:
            # Older self-hosted deployments predate this endpoint
            raise FapihubError(
                f"{self.settings.base_url} doesn't support usage lookups. Check your usage in the FAPIHUB dashboard."
            )
        _raise_for_status(response)
        return response.json()["data"]

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {
            "ApiKey": self.settings.api_key,
            "User-Agent": f"fapihub-mcp/{__version__}",
        }
        async with httpx.AsyncClient(timeout=self.settings.timeout, transport=self._transport) as http:
            try:
                response = await http.request(method, f"{self.settings.base_url}{path}", headers=headers, **kwargs)
            except httpx.TimeoutException:
                raise FapihubError("The FAPIHUB API timed out. Try again in a moment.")
            except httpx.HTTPError as e:
                raise FapihubError(f"Could not reach the FAPIHUB API at {self.settings.base_url}: {e}")
        return response


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code != 200:
        raise FapihubError(_describe_error(response))


def _describe_error(response: httpx.Response) -> str:
    message = response.text.strip() or response.reason_phrase
    try:
        error = response.json().get("error")
        if isinstance(error, dict) and error.get("message"):
            message = error["message"]
    except ValueError:
        pass
    message = message.rstrip(".") + "."

    status = response.status_code
    if status == 401:
        return f"Authentication failed: {message} Check FAPIHUB_API_KEY."
    if status in (402, 403):
        return f"{message} Manage your plan at https://fapihub.com/billing/"
    if status == 429:
        retry_after = response.headers.get("Retry-After")
        hint = f" Retry after {retry_after} seconds." if retry_after else ""
        return f"Rate limit exceeded.{hint}"
    return f"FAPIHUB API error ({status}): {message}"
