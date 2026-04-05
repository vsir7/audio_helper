"""高德地图 Web 服务：地理编码、中点相遇、逆地理编码、到相遇点距离（无 POI 偏好）。"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from config import settings
from mcp_dump import MCPJsonRecorder
from proxy_util import clear_proxy_environment

log = logging.getLogger("audio_helper.amap")


def _midpoint(loc_a: str, loc_b: str) -> str:
    lng1, lat1 = map(float, loc_a.split(","))
    lng2, lat2 = map(float, loc_b.split(","))
    return f"{(lng1 + lng2) / 2:.6f},{(lat1 + lat2) / 2:.6f}"


async def geocode_address(address: str, city: str | None = None) -> tuple[str, dict[str, Any]]:
    """返回 (location 如 "lng,lat", 原始 JSON)。"""
    clear_proxy_environment()
    key = settings.amap_rest_key.strip()
    if not key:
        raise ValueError("未配置 AMAP_REST_KEY，请在 backend/.env 中填写")

    params: dict[str, str] = {"key": key, "address": address}
    if city and city.strip():
        params["city"] = city.strip()

    log.info("高德 地理编码: address=%r", address[:120])

    try:
        async with httpx.AsyncClient(
            timeout=settings.amap_timeout_seconds,
            trust_env=False,
        ) as client:
            r = await client.get(settings.amap_geocode_url, params=params)
    except httpx.HTTPError as e:
        log.exception("高德地理编码网络错误")
        raise RuntimeError(f"高德地理编码请求失败: {e}") from e

    try:
        data = r.json()
    except json.JSONDecodeError:
        data = {"raw": r.text}

    if r.status_code >= 400:
        log.error("高德地理编码 HTTP %s: %s", r.status_code, str(data)[:800])
        raise RuntimeError(f"高德地理编码 HTTP {r.status_code}")

    status = str(data.get("status", ""))
    if status != "1":
        infocode = data.get("infocode", "")
        info = data.get("info", "")
        log.error("高德地理编码失败 status=%s infocode=%s info=%s", status, infocode, info)
        raise RuntimeError(f"高德地理编码失败: {info or infocode or status}")

    geocodes = data.get("geocodes") or []
    if not geocodes:
        log.error("高德地理编码无结果: %r", address[:120])
        raise RuntimeError(f"无法解析地址: {address!r}")

    loc = geocodes[0].get("location", "")
    if not loc or "," not in loc:
        raise RuntimeError("高德返回 location 无效")
    log.info("高德 地理编码成功: location=%s", loc)
    return loc, data


async def regeo_location(location: str) -> dict[str, Any]:
    """逆地理编码：经纬度 → 结构化地址与 formatted_address。"""
    clear_proxy_environment()
    key = settings.amap_rest_key.strip()
    if not key:
        raise ValueError("未配置 AMAP_REST_KEY")

    params = {
        "key": key,
        "location": location,
        "extensions": "base",
        "radius": "300",
    }

    log.info("高德 逆地理编码: location=%s", location)

    try:
        async with httpx.AsyncClient(
            timeout=settings.amap_timeout_seconds,
            trust_env=False,
        ) as client:
            r = await client.get(settings.amap_regeo_url, params=params)
    except httpx.HTTPError as e:
        log.exception("高德逆地理编码网络错误")
        raise RuntimeError(f"高德逆地理编码请求失败: {e}") from e

    try:
        data = r.json()
    except json.JSONDecodeError:
        data = {"raw": r.text}

    if r.status_code >= 400:
        raise RuntimeError(f"高德逆地理编码 HTTP {r.status_code}")

    status = str(data.get("status", ""))
    if status != "1":
        log.error(
            "高德逆地理编码失败 status=%s info=%s",
            status,
            data.get("info"),
        )
        raise RuntimeError(f"高德逆地理编码失败: {data.get('info', status)}")

    log.info("高德 逆地理编码成功")
    return data


async def distance_batch_to_destination(
    origins_pipe: str,
    destination: str,
) -> dict[str, Any]:
    """
    批量测距：origins 为 lng,lat|lng,lat，destination 为相遇点。
    type 见配置 AMAP_DISTANCE_TYPE（高德：0 直线 / 1 驾车 / 3 步行）。
    """
    clear_proxy_environment()
    key = settings.amap_rest_key.strip()
    if not key:
        raise ValueError("未配置 AMAP_REST_KEY")

    params = {
        "key": key,
        "origins": origins_pipe,
        "destination": destination,
        "type": str(settings.amap_distance_type),
        "output": "JSON",
    }

    log.info(
        "高德 距离测量: type=%s origins=%s -> dest=%s",
        settings.amap_distance_type,
        origins_pipe,
        destination,
    )

    try:
        async with httpx.AsyncClient(
            timeout=settings.amap_timeout_seconds,
            trust_env=False,
        ) as client:
            r = await client.get(settings.amap_distance_url, params=params)
    except httpx.HTTPError as e:
        log.exception("高德距离测量网络错误")
        raise RuntimeError(f"高德距离测量请求失败: {e}") from e

    try:
        data = r.json()
    except json.JSONDecodeError:
        data = {"raw": r.text}

    if r.status_code >= 400:
        raise RuntimeError(f"高德距离测量 HTTP {r.status_code}")

    status = str(data.get("status", ""))
    if status != "1":
        log.error(
            "高德距离测量失败 status=%s info=%s",
            status,
            data.get("info"),
        )
        raise RuntimeError(f"高德距离测量失败: {data.get('info', status)}")

    return data


def _parse_distance_results(
    raw: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """按 origins 顺序解析两段路程（第一人、第二人到相遇点）。"""
    results = raw.get("results") or []
    if not results:
        return None, None

    def one(idx: int) -> dict[str, Any] | None:
        if idx >= len(results):
            return None
        row = results[idx]
        if not isinstance(row, dict):
            return None
        dist = row.get("distance", "")
        dur = row.get("duration", "")
        out: dict[str, Any] = {
            "distance_meters": int(dist) if str(dist).isdigit() else dist,
        }
        if dur != "" and str(dur).isdigit():
            out["duration_seconds"] = int(dur)
        return out

    return one(0), one(1)


def _summarize_regeo(data: dict[str, Any]) -> dict[str, Any]:
    regeocode = data.get("regeocode") or {}
    formatted = str(regeocode.get("formatted_address", "")).strip()
    comp = regeocode.get("addressComponent") or {}
    if not isinstance(comp, dict):
        comp = {}
    province = comp.get("province", "")
    city = comp.get("city", "")
    district = comp.get("district", "")
    township = comp.get("township", "")
    parts = [p for p in (province, city, district, township) if p]
    short = "".join(parts) if parts else formatted
    return {
        "formatted_address": formatted,
        "short_region": short,
        "address_component": comp,
    }


async def meetup_recommend(
    address_a: str,
    address_b: str,
    *,
    mcp_recorder: MCPJsonRecorder | None = None,
) -> dict[str, Any]:
    """
    两人地址 → 各自坐标 → 几何中点作为「推荐相遇坐标」
    → 逆地理编码得到可读位置说明
    → 测量两人各自到相遇点的距离（无 POI/品类偏好）。
    若传入 mcp_recorder，每次高德 HTTP 往返会写入 Storage：{stem}_MCP01.json …
    """
    if not address_a or not address_b:
        raise ValueError("两个地址均不能为空，请检查 DeepSeek 抽取结果")

    loc_a, raw_a = await geocode_address(address_a)
    if mcp_recorder:
        mcp_recorder.write(
            "geocode_person_a",
            "amap_geocode_geo",
            {
                "method": "GET",
                "url": settings.amap_geocode_url,
                "query": {"address": address_a, "key": settings.amap_rest_key},
            },
            raw_a,
        )

    loc_b, raw_b = await geocode_address(address_b)
    if mcp_recorder:
        mcp_recorder.write(
            "geocode_person_b",
            "amap_geocode_geo",
            {
                "method": "GET",
                "url": settings.amap_geocode_url,
                "query": {"address": address_b, "key": settings.amap_rest_key},
            },
            raw_b,
        )

    mid = _midpoint(loc_a, loc_b)

    raw_regeo = await regeo_location(mid)
    if mcp_recorder:
        mcp_recorder.write(
            "regeo_meetup_midpoint",
            "amap_geocode_regeo",
            {
                "method": "GET",
                "url": settings.amap_regeo_url,
                "query": {
                    "location": mid,
                    "extensions": "base",
                    "radius": "300",
                    "key": settings.amap_rest_key,
                },
            },
            raw_regeo,
        )
    regeo_summary = _summarize_regeo(raw_regeo)

    origins_pipe = f"{loc_a}|{loc_b}"
    raw_distance = await distance_batch_to_destination(origins_pipe, mid)
    if mcp_recorder:
        mcp_recorder.write(
            "distance_both_to_meetup",
            "amap_distance",
            {
                "method": "GET",
                "url": settings.amap_distance_url,
                "query": {
                    "origins": origins_pipe,
                    "destination": mid,
                    "type": str(settings.amap_distance_type),
                    "output": "JSON",
                    "key": settings.amap_rest_key,
                },
            },
            raw_distance,
        )
    leg_a, leg_b = _parse_distance_results(raw_distance)

    return {
        "strategy": "midpoint_no_poi_preference",
        "address_a": address_a,
        "address_b": address_b,
        "location_a": loc_a,
        "location_b": loc_b,
        "midpoint": mid,
        "meetup_location": {
            "coordinate": mid,
            "description": regeo_summary.get("formatted_address")
            or regeo_summary.get("short_region")
            or mid,
            "formatted_address": regeo_summary.get("formatted_address", ""),
            "short_region": regeo_summary.get("short_region", ""),
        },
        "travel_to_meetup": {
            "from_person_a": leg_a,
            "from_person_b": leg_b,
            "distance_measure_type": settings.amap_distance_type,
        },
        "raw_geocode_a": raw_a,
        "raw_geocode_b": raw_b,
        "raw_regeo": raw_regeo,
        "raw_distance": raw_distance,
        "mcp_json_files": list(mcp_recorder.filenames) if mcp_recorder else [],
    }
