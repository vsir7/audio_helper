"""百炼 CosyVoice：非流式 HTTP TTS（SpeechSynthesizer），下载音频落盘。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from config import settings
from proxy_util import clear_proxy_environment

log = logging.getLogger("audio_helper.bailian_tts")


async def synthesize_to_storage(
    text: str,
    storage_dir: Path,
    stem: str,
) -> tuple[str | None, dict[str, Any]]:
    """
    调用 CosyVoice，从返回的 audio.url 下载文件到 Storage。
    返回 (保存的文件名如 xxx.tts.mp3, 百炼原始 JSON)；失败时抛出 RuntimeError。
    """
    clear_proxy_environment()

    key = settings.dashscope_api_key.strip()
    if not key:
        raise ValueError("未配置 DASHSCOPE_API_KEY（与 ASR 共用）")

    t = text.strip()
    if not t:
        raise ValueError("TTS 文本为空")

    max_c = settings.tts_max_characters
    if len(t) > max_c:
        log.warning("TTS 文本超长，截断至 %s 字", max_c)
        t = t[:max_c]

    payload: dict[str, Any] = {
        "model": settings.tts_model,
        "input": {
            "text": t,
            "voice": settings.tts_voice,
            "format": settings.tts_format,
            "sample_rate": settings.tts_sample_rate,
        },
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    log.info(
        "百炼 TTS 请求: model=%s voice=%s format=%s text_len=%s",
        settings.tts_model,
        settings.tts_voice,
        settings.tts_format,
        len(t),
    )

    try:
        async with httpx.AsyncClient(
            timeout=settings.tts_timeout_seconds,
            trust_env=False,
        ) as client:
            r = await client.post(
                settings.cosyvoice_tts_url,
                headers=headers,
                json=payload,
            )
    except httpx.HTTPError as e:
        log.exception("百炼 TTS 网络错误")
        raise RuntimeError(f"请求百炼 TTS 失败: {e}") from e

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
        log.error("百炼 TTS HTTP %s: %s", r.status_code, preview)
        raise RuntimeError(f"百炼 TTS HTTP {r.status_code}: {preview}")

    if not isinstance(body, dict):
        raise RuntimeError("TTS 响应不是 JSON 对象")

    output = body.get("output") or {}
    audio = output.get("audio") or {}
    url = audio.get("url")
    if not isinstance(url, str) or not url.strip():
        log.error("TTS 响应无有效 audio.url: %s", str(body)[:800])
        raise RuntimeError("百炼 TTS 未返回可下载的音频 URL")

    ext = settings.tts_format.lower().strip() or "mp3"
    safe_ext = ext if ext in ("mp3", "wav", "pcm", "opus") else "mp3"
    filename = f"{stem}.tts.{safe_ext}"
    dest = storage_dir / filename

    try:
        async with httpx.AsyncClient(
            timeout=settings.tts_timeout_seconds,
            trust_env=False,
        ) as dl:
            ar = await dl.get(url.strip())
    except httpx.HTTPError as e:
        raise RuntimeError(f"下载 TTS 音频失败: {e}") from e

    if ar.status_code >= 400:
        raise RuntimeError(f"下载 TTS 音频 HTTP {ar.status_code}")

    dest.write_bytes(ar.content)
    log.info("TTS 已保存: %s (%s bytes)", filename, len(ar.content))
    return filename, body
