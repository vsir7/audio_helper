"""DeepSeek：把 ASR + 地址 + 高德相遇结果整合成面向用户的自然语言答复。"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from config import settings
from proxy_util import clear_proxy_environment

log = logging.getLogger("audio_helper.deepseek_compose")

_SYSTEM_PROMPT = """你是口语化的出行助手。根据下面给出的「语音识别原文」「两人地点」和「地图计算的相遇点与路程」，写一段直接念给用户听的中文答复。
要求：2～6 句，自然流畅；说明推荐在哪里碰头、大概方位或地标；若有两人到相遇点的距离信息可顺带提一下；不要 Markdown、不要列表符号、不要 JSON。"""


def _meetup_summary_for_llm(meetup: dict[str, Any]) -> dict[str, Any]:
    """去掉 raw_* 等大字段，仅保留整合话术需要的结构。"""
    return {
        "strategy": meetup.get("strategy"),
        "midpoint_coordinate": meetup.get("midpoint"),
        "meetup_location": meetup.get("meetup_location"),
        "travel_to_meetup": meetup.get("travel_to_meetup"),
    }


def _message_content(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    c = msg.get("content")
    return c.strip() if isinstance(c, str) else ""


async def compose_meetup_reply(
    transcript: str,
    addresses: dict[str, Any],
    meetup: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """返回 (整合后的纯文本, DeepSeek 原始 completion JSON)。"""
    clear_proxy_environment()

    key = settings.deepseek_api_key.strip()
    if not key:
        raise ValueError("未配置 DEEPSEEK_API_KEY，请在 backend/.env 中填写")

    payload_user = {
        "用户语音识别原文": transcript,
        "抽取的两地": {
            "第一人": addresses.get("address_a", ""),
            "第二人": addresses.get("address_b", ""),
            "备注": addresses.get("notes", ""),
        },
        "地图服务返回的相遇推荐": _meetup_summary_for_llm(meetup),
    }
    user_text = json.dumps(payload_user, ensure_ascii=False, indent=2)

    model = settings.deepseek_compose_model.strip() or settings.deepseek_model
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "temperature": settings.deepseek_compose_temperature,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    log.info(
        "DeepSeek 整合话术: model=%s user_json_len=%s",
        model,
        len(user_text),
    )

    try:
        async with httpx.AsyncClient(
            timeout=settings.deepseek_timeout_seconds,
            trust_env=False,
        ) as client:
            r = await client.post(
                settings.deepseek_chat_completions_url,
                headers=headers,
                json=payload,
            )
    except httpx.HTTPError as e:
        log.exception("DeepSeek 整合请求网络错误")
        raise RuntimeError(f"请求 DeepSeek 失败: {e}") from e

    try:
        body = r.json()
    except json.JSONDecodeError:
        body = {"_parse_error": True, "raw_text": r.text}

    if r.status_code >= 400:
        preview = (
            json.dumps(body, ensure_ascii=False)[:1500]
            if isinstance(body, dict)
            else str(body)[:1500]
        )
        log.error("DeepSeek 整合 HTTP %s: %s", r.status_code, preview)
        raise RuntimeError(f"DeepSeek HTTP {r.status_code}: {preview}")

    if not isinstance(body, dict):
        raise RuntimeError("DeepSeek 响应不是 JSON 对象")

    out = _message_content(body)
    if not out:
        raise RuntimeError("DeepSeek 整合结果为空")

    log.info("DeepSeek 整合完成: reply_len=%s", len(out))
    return out, body
