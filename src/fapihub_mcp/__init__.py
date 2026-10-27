"""FAPIHUB MCP server: background removal tools for AI agents."""

__version__ = "0.1.0"


def main() -> None:
    from fapihub_mcp.server import mcp

    mcp.run()
