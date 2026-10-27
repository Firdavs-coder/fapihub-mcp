"""FAPIHUB MCP server: background removal tools for AI agents."""

__version__ = "0.2.0"


def main() -> None:
    from fapihub_mcp.server import mcp

    mcp.run()
