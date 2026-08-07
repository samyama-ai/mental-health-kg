"""MCP server exposing the Mental Health KG. Run: python -m mcp_server.server"""
from fastmcp import FastMCP
mcp = FastMCP("mental-health-kg")

@mcp.tool()
def treatments_for_condition(condition: str) -> list[dict]:
    """Treatments indicated for a given condition."""
    return []  # TODO: TREATED_BY / TREATS traversal

@mcp.tool()
def symptoms_of(condition: str) -> list[dict]:
    """Symptoms associated with a given condition."""
    return []  # TODO: HAS_SYMPTOM traversal

if __name__ == "__main__":
    mcp.run()
