"""Optional local stdio transport. All data calls go through TravelTools.

Launch: python -m travel.mcp_server (working directory backend).
No HTTP port, Agent loop, itinerary store or replacement planner is created.
"""
from typing import Literal
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from dotenv import load_dotenv
import json

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from travel.provider import TravelFailure
from travel.tools import TravelTools

server = FastMCP("TravelAgent real data tools")


def call(name, arguments):
    try:
        return {"data": TravelTools().invoke(name, arguments)}
    except TravelFailure as error:
        # Return the same sanitized error envelope as REST. It never contains
        # an upstream URL, API key, synthetic success or guessed route.
        envelope = {"error": {"code": error.code, "message": error.message, "retryable": error.retryable}}
        return CallToolResult(isError=True, content=[TextContent(type="text", text=json.dumps(envelope, ensure_ascii=False))], structuredContent=envelope)


@server.tool()
def search_pois(keyword: str, city: str, limit: int = 20) -> dict:
    """Search real authorized POIs. Missing data remains null."""
    return call("search_pois", {"keyword": keyword, "city": city, "limit": limit})


@server.tool()
def get_poi(poi_id: str) -> dict:
    """Read real POI detail. Does not invent tickets or reviews."""
    return call("get_poi", {"poi_id": poi_id})


@server.tool()
def get_route(origin: dict, destination: dict, mode: Literal["walking", "driving"] = "walking") -> dict:
    """Read provider road geometry and travel time; never let an LLM estimate."""
    return call("get_route", {"origin": origin, "destination": destination, "mode": mode})


if __name__ == "__main__":
    server.run(transport="stdio")
