# FAPIHUB MCP Server

An [MCP](https://modelcontextprotocol.io) server that gives AI agents (Claude Code, Claude Desktop, Cursor, VS Code, Windsurf and others) background-removal tools from [FAPIHUB](https://fapihub.com).

Ask your agent things like:

> Remove the background from `assets/product.jpg`
>
> Put every photo in `./team` on a solid `#F5F5F5` background
>
> Blur the background of `portrait.png` and add a soft drop shadow to `logo.png`

The server reads images from your disk, sends them to the FAPIHUB API and saves the results next to the originals.

## Tools

| Tool | What it does | Options |
| --- | --- | --- |
| `remove_background` | Transparent PNG cutout of the subject | `model`: `falcon` (default), `aurora`, `ghost` |
| `create_mask` | Black-and-white subject mask | `model` |
| `blur_background` | Keeps the subject sharp and blurs the background | `radius` (1-50, default 10) |
| `color_background` | Replaces the background with a solid color | `color` |
| `gradient_background` | Replaces the background with a vertical gradient | `top_color`, `bottom_color` |
| `add_shadow` | Cutout with a drop shadow | `shadow_color`, `offset_x`, `offset_y`, `blur_radius` |

Every tool takes `image_path` (JPG, PNG, WEBP, BMP or GIF, 1 KB to 10 MB) and an optional `output_path`. Without `output_path`, the result is saved as `<name>_<operation>.<ext>` beside the input and never overwrites an existing file.

Colors can be hex (`#FF8C00`, `#FF8C0080`) or RGB(A) (`255, 140, 0` or `255, 140, 0, 128`).

Each tool call uses one request from your FAPIHUB plan. Invalid inputs (missing file, wrong format, bad size) are caught locally before anything is sent, so they don't use quota.

## Setup

1. Create an API key in your [FAPIHUB dashboard](https://fapihub.com/dashboard/).
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/), which provides `uvx`.
3. Add the server to your client using one of the configurations below.

### Claude Code

```bash
claude mcp add fapihub -e FAPIHUB_API_KEY=bg_live_sk_... -- uvx --from git+https://github.com/Firdavs-coder/fapihub-mcp fapihub-mcp
```

### Claude Desktop, Cursor, Windsurf and other JSON-configured clients

Add this to your client's MCP config (`claude_desktop_config.json`, `.cursor/mcp.json`, etc.):

```json
{
  "mcpServers": {
    "fapihub": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Firdavs-coder/fapihub-mcp", "fapihub-mcp"],
      "env": {
        "FAPIHUB_API_KEY": "bg_live_sk_..."
      }
    }
  }
}
```

### VS Code

Add this to `.vscode/mcp.json`:

```json
{
  "servers": {
    "fapihub": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Firdavs-coder/fapihub-mcp", "fapihub-mcp"],
      "env": {
        "FAPIHUB_API_KEY": "bg_live_sk_..."
      }
    }
  }
}
```

## Configuration

| Environment variable | Required | Default |
| --- | --- | --- |
| `FAPIHUB_API_KEY` | Yes | |
| `FAPIHUB_BASE_URL` | No | `https://fapihub.com` |
| `FAPIHUB_TIMEOUT` | No | `120` (seconds) |

## Development

```bash
git clone https://github.com/Firdavs-coder/fapihub-mcp
cd fapihub-mcp
uv sync
uv run pytest
```

To try the server against a local FAPIHUB instance:

```bash
FAPIHUB_API_KEY=bg_live_sk_... FAPIHUB_BASE_URL=http://127.0.0.1:8000 uv run fapihub-mcp
```

## License

MIT
