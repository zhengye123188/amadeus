"""Optional, offline MCP stdio example. Never log ordinary text to stdout."""

from mcp.server.fastmcp import FastMCP

server = FastMCP("research-demo")


@server.tool()
def experiment_checklist(topic: str) -> dict:
    """Return a small review checklist for the supplied research topic."""
    return {
        "topic": topic,
        "checklist": [
            "Freeze data split",
            "Record seed and code hash",
            "Report baseline and negative results",
        ],
    }


if __name__ == "__main__":
    server.run(transport="stdio")
