"""One typed provider gateway for REST, workers, Function Calling and MCP.

This layer contains no Agent loop, local data loading or business algorithms.
"""
from pydantic import ValidationError

from travel.provider import AmapProvider, TravelFailure
from travel.schemas import Poi, PoiDetail, PoiList, PoiSearch, RouteQuery, Source


class TravelTools:
    definitions = {
        "search_pois": (PoiSearch, "查询授权高德 POI；缺失字段保持 null"),
        "get_poi": (PoiDetail, "获取授权高德 POI 详情，不生成评论或价格"),
        "get_route": (RouteQuery, "查询真实路线、距离和耗时，不由 LLM 估算"),
    }

    def __init__(self, provider=None):
        self.provider = provider or AmapProvider()

    def search(self, keyword, city, limit=20):
        try:
            query = PoiSearch(keyword=keyword, city=city, limit=limit)
        except ValidationError:
            raise TravelFailure("invalid_tool_arguments", "城市、关键词或数量不符合契约", status=422) from None
        return self.provider.search(query.keyword, query.city, query.limit)

    def detail(self, poi_id):
        try:
            query = PoiDetail(poi_id=poi_id)
        except ValidationError:
            raise TravelFailure("invalid_tool_arguments", "POI ID 不符合契约", status=422) from None
        return self.provider.detail(query.poi_id)

    def route(self, origin, destination, mode):
        return self.provider.route(origin, destination, mode)

    def route_query(self, query: RouteQuery):
        def endpoint(point, identifier):
            return Poi(id=identifier, name=identifier, longitude=point.longitude,
                       latitude=point.latitude, source=Source(provider="user_input"))
        return self.route(endpoint(query.origin, "origin"), endpoint(query.destination, "destination"), query.mode)

    @classmethod
    def function_definitions(cls):
        return [{"type": "function", "function": {"name": name, "description": description,
                 "parameters": model.model_json_schema()}} for name, (model, description) in cls.definitions.items()]

    def invoke(self, name: str, arguments: dict) -> dict:
        """Dispatch an allowlisted call. Invalid/unavailable calls never fabricate data."""
        if name not in self.definitions:
            raise TravelFailure("unknown_tool", "未授权的旅行工具", status=422)
        try:
            query = self.definitions[name][0].model_validate(arguments)
        except ValidationError:
            raise TravelFailure("invalid_tool_arguments", "旅行工具参数不符合契约", status=422) from None
        if name == "search_pois":
            result = PoiList(items=self.search(query.keyword, query.city, query.limit))
        elif name == "get_poi":
            result = self.detail(query.poi_id)
        else:
            result = self.route_query(query)
        return result.model_dump(mode="json")
