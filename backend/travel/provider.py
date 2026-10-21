"""Fail-closed factual adapter over the existing authorized Amap client."""
from __future__ import annotations

import math
from typing import Any

import httpx

from services.amap_client import AmapClient
from travel.schemas import Poi, Point, Segment, Source, TimeConstraintDiagnostics


class TravelFailure(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False, status: int = 502, *, time_constraints: TimeConstraintDiagnostics | None = None):
        super().__init__(message)
        self.code, self.message, self.retryable, self.status = code, message, retryable, status
        self.time_constraints = time_constraints


def number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


class AmapProvider:
    def __init__(self, client: AmapClient | None = None):
        self.client = client or AmapClient()

    def call(self, method: str, **kwargs: Any) -> dict:
        if not self.client.enabled:
            raise TravelFailure("provider_not_configured", "未配置高德 Web 服务 Key；无法查询真实数据", status=503)
        try:
            data = getattr(self.client, method)(**kwargs)
        except httpx.TimeoutException:
            raise TravelFailure("provider_timeout", "高德接口超时", True, 504) from None
        except (httpx.HTTPError, ValueError, TypeError):
            # Never include an upstream URL: its query contains the API key.
            raise TravelFailure("provider_unavailable", "高德接口调用失败", True) from None
        if not isinstance(data, dict) or str(data.get("status")) != "1":
            code = str(data.get("infocode", "unknown")) if isinstance(data, dict) else "unknown"
            raise TravelFailure("provider_rejected", f"高德拒绝请求（错误码 {code}），请检查授权、权限和配额")
        return data

    def normalize(self, record: dict) -> Poi | None:
        try:
            lng, lat = (float(part) for part in str(record.get("location", "")).split(","))
            if not math.isfinite(lng) or not math.isfinite(lat) or not record.get("id") or not record.get("name"):
                return None
            biz = record.get("biz_ext") if isinstance(record.get("biz_ext"), dict) else {}
            rating, spend = number(biz.get("rating")), number(biz.get("cost"))
            if rating is not None and rating > 5:
                rating = None
            hours = text(biz.get("open_time")) or text(record.get("opentime"))
            missing = [key for key, value in {
                "rating": rating, "average_spend": spend, "opening_hours": hours,
                "address": text(record.get("address")), "city": text(record.get("cityname")),
                "category": text(record.get("type")),
            }.items() if value is None]
            return Poi(id=str(record["id"]), name=str(record["name"]), city=text(record.get("cityname")),
                       address=text(record.get("address")), category=text(record.get("type")),
                       longitude=lng, latitude=lat, rating=rating, average_spend=spend,
                       opening_hours=hours, source=Source(provider="amap"), missing_fields=missing)
        except (ValueError, TypeError):
            return None

    def search(self, keyword: str, city: str, limit: int = 20) -> list[Poi]:
        raw = self.call("search_poi", keyword=keyword, city=city, offset=limit)
        records = raw.get("pois")
        if not isinstance(records, list):
            raise TravelFailure("invalid_provider_response", "高德搜索响应缺少 POI 列表")
        items = {poi.id: poi for item in records if isinstance(item, dict) and (poi := self.normalize(item)) is not None}
        return list(items.values())[:limit]

    def detail(self, poi_id: str) -> Poi:
        raw = self.call("poi_detail", poi_id=poi_id)
        for record in raw.get("pois", []) or []:
            poi = self.normalize(record) if isinstance(record, dict) else None
            if poi and poi.id == poi_id:
                return poi
        raise TravelFailure("poi_not_found", "POI 不存在或缺少有效坐标", status=404)

    def route(self, origin: Poi, destination: Poi, mode: str) -> Segment:
        raw = self.call("directions", origin=f"{origin.longitude},{origin.latitude}",
                        destination=f"{destination.longitude},{destination.latitude}", mode=mode)
        route = raw.get("route")
        paths = route.get("paths") if isinstance(route, dict) else None
        if not isinstance(paths, list) or not paths or not isinstance(paths[0], dict):
            raise TravelFailure("route_unavailable", "高德未返回可用路线；不能估算替代交通数据")
        path = paths[0]
        distance, duration = number(path.get("distance")), number(path.get("duration"))
        if distance is None or duration is None:
            raise TravelFailure("route_incomplete", "真实路线缺少距离或时长")
        points: list[Point] = []
        for step in path.get("steps", []) or []:
            for pair in str(step.get("polyline", "")).split(";"):
                try:
                    lng, lat = (float(part) for part in pair.split(","))
                    point = Point(longitude=lng, latitude=lat)
                    if not points or point != points[-1]:
                        points.append(point)
                except (ValueError, TypeError):
                    continue
        if not points:
            raise TravelFailure("route_geometry_missing", "真实路线缺少路网折线")
        return Segment(origin_id=origin.id, destination_id=destination.id, mode=mode,
                       distance_km=distance / 1000, duration_min=math.ceil(duration / 60),
                       tolls=number(path.get("tolls")), polyline=points, source=Source(provider="amap"))
