"""DeepSeek：从 ASR 文本抽取两人位置（地址/地标），HTTP OpenAI 兼容接口。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from config import settings
from proxy_util import clear_proxy_environment

log = logging.getLogger("audio_helper.deepseek")

_SYSTEM_PROMPT = """你是地址抽取助手。用户语音经识别后的文本里，通常包含两个人各自所在位置（城市、区、地标、POI 等）。
请从中抽取两个位置字符串，分别对应「第一人」和「第二人」。若某一方未提及，用空字符串。
只输出一个 JSON 对象，不要 Markdown 代码块，不要其它说明。字段固定为：
{"address_a":"","address_b":"","notes":""}
address_a 为第一人位置，address_b 为第二人位置；notes 可简短说明不确定之处。"""


def _parse_json_content(text: str) -> dict[str, Any]:
    t = text.strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)```$", t, re.IGNORECASE)
    if fence:
        t = fence.group(1).strip()
    return json.loads(t)


async def extract_two_addresses(transcript: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    返回 (结构化结果, DeepSeek 原始 completion JSON)。
    结构化结果含 address_a, address_b, notes。
    """
    clear_proxy_environment()

    key = settings.deepseek_api_key.strip()
    if not key:
        raise ValueError("未配置 DEEPSEEK_API_KEY，请在 backend/.env 中填写")

    payload: dict[str, Any] = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"识别文本如下：\n{transcript}",
            },
        ],
        "temperature": settings.deepseek_temperature,
        "stream": False,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    log.info(
        "DeepSeek 请求: url=%s model=%s transcript_len=%s",
        settings.deepseek_chat_completions_url,
        settings.deepseek_model,
        len(transcript),
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
        log.exception("DeepSeek 网络错误")
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
        log.error("DeepSeek HTTP %s: %s", r.status_code, preview)
        raise RuntimeError(f"DeepSeek HTTP {r.status_code}: {preview}")

    if not isinstance(body, dict):
        raise RuntimeError("DeepSeek 响应不是 JSON 对象")

    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("DeepSeek 响应无 choices")
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if not isinstance(content, str):
        raise RuntimeError("DeepSeek message.content 非字符串")

    log.debug("DeepSeek 原始 content 长度=%s", len(content))

    try:
        parsed = _parse_json_content(content)
    except json.JSONDecodeError as e:
        log.error("DeepSeek JSON 解析失败: %s", content[:500])
        raise RuntimeError(f"DeepSeek 返回非合法 JSON: {e}") from e

    address_a = str(parsed.get("address_a", "")).strip()
    address_b = str(parsed.get("address_b", "")).strip()
    notes = str(parsed.get("notes", "")).strip()

    result = {
        "address_a": address_a,
        "address_b": address_b,
        "notes": notes,
    }
    log.info(
        "DeepSeek 抽取完成: address_a=%r address_b=%r",
        address_a[:80],
        address_b[:80],
    )
    return result, body
