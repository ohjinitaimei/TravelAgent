"""Real MCP stdio handshake and fail-closed calls; no network quota used."""
import json
import os
from pathlib import Path
import sys
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


class McpTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_gateway_errors_and_schema(self):
        environment = {**os.environ, "AMAP_KEY":"", "AMAP_WEB_KEY":"", "PYTHONIOENCODING":"utf-8"}
        parameters = StdioServerParameters(command=sys.executable, args=["-m","travel.mcp_server"], cwd=str(ROOT/"backend"), env=environment)
        async with stdio_client(parameters) as (reader, writer), ClientSession(reader, writer) as session:
            await session.initialize()
            listing = await session.list_tools()
            self.assertEqual({tool.name for tool in listing.tools}, {"search_pois","get_poi","get_route"})
            for name, arguments in [("search_pois", {"keyword":"公园","city":"北京"}), ("get_poi", {"poi_id":"test-only-id"}), ("get_route", {"origin":{"longitude":116.1,"latitude":39.9},"destination":{"longitude":116.2,"latitude":39.9}})]:
                result = await session.call_tool(name, arguments)
                self.assertTrue(result.isError)
                self.assertEqual(result.structuredContent["error"]["code"], "provider_not_configured")
                self.assertNotIn("key=", json.dumps(result.structuredContent))
            invalid=await session.call_tool("get_route", {"origin":{},"destination":{}})
            self.assertTrue(invalid.isError)
            self.assertEqual(invalid.structuredContent["error"]["code"],"invalid_tool_arguments")


if __name__ == "__main__":
    unittest.main()
