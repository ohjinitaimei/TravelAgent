"""Optional local stdio transport. All data calls go through TravelTools.

Launch: python -m travel.mcp_server (working directory backend).
No HTTP port, Agent loop, itinerary store or replacement planner is created.
"""
from typing import Any, Literal
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from dotenv import dotenv_values
import json
import os

# Standalone launches load only the authorized provider's settings. Never load
# model, GitHub or user session credentials into this data-only tool process.
for env_path in (Path(__file__).resolve().parents[1]/".env",Path(__file__).resolve().parents[2]/".env"):
    for key,value in dotenv_values(env_path).items():
        if key in {"AMAP_KEY","AMAP_WEB_KEY","AMAP_WEB_BASE_URL","AMAP_WEB_TIMEOUT_SECONDS"} and value is not None:
            os.environ.setdefault(key,value)

from travel.provider import TravelFailure
from travel.tools import TravelTools

server = FastMCP("TravelAgent real data tools")
READ_ONLY=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=True)


def call(name, arguments):
    try:
        return {"data": TravelTools().invoke(name, arguments)}
    except TravelFailure as error:
        # Return the same sanitized error envelope as REST. It never contains
        # an upstream URL, API key, synthetic success or guessed route.
        envelope = {"error": {"code": error.code, "message": error.message, "retryable": error.retryable}}
        return CallToolResult(isError=True, content=[TextContent(type="text", text=json.dumps(envelope, ensure_ascii=False))], structuredContent=envelope)


@server.tool(annotations=READ_ONLY)
def search_pois(keyword: str, city: str, limit: int = 20) -> dict[str, Any]:
    """Search real authorized POIs. Missing data remains null."""
    return call("search_pois", {"keyword": keyword, "city": city, "limit": limit})


@server.tool(annotations=READ_ONLY)
def get_poi(poi_id: str) -> dict[str, Any]:
    """Read real POI detail. Does not invent tickets or reviews."""
    return call("get_poi", {"poi_id": poi_id})


@server.tool(annotations=READ_ONLY)
def get_route(origin: dict, destination: dict, mode: Literal["walking", "driving"] = "walking") -> dict[str, Any]:
    """Read provider road geometry and travel time; never let an LLM estimate."""
    return call("get_route", {"origin": origin, "destination": destination, "mode": mode})


if __name__ == "__main__":
    server.run(transport="stdio")
