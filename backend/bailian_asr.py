"""百炼 Qwen-ASR：OpenAI 兼容 HTTP，Data URL 传本地文件（无 SDK）。"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from config import settings
from proxy_util import clear_proxy_environment

log = logging.getLogger("audio_helper.bailian")


def _suffix_to_audio_mime(suffix: str) -> str:
    s = suffix.lower()
    return {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".webm": "video/webm",
        ".mp4": "video/mp4",
        ".flac": "audio/flac",
        ".opus": "audio/opus",
        ".bin": "application/octet-stream",
    }.get(s, "application/octet-stream")


def build_audio_data_uri(file_path: Path) -> str:
    raw = file_path.read_bytes()
    mime = _suffix_to_audio_mime(file_path.suffix)
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def extract_transcript_from_completion(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts).strip()
    return ""


async def transcribe_file(file_path: Path) -> tuple[str, dict[str, Any]]:
    """
    调用百炼 OpenAI 兼容 chat/completions 完成识别。
    返回 (识别文本, 完整响应 JSON)。
    """
    clear_proxy_environment()

    key = settings.dashscope_api_key.strip()
    if not key:
        raise ValueError("未配置 DASHSCOPE_API_KEY，请在 backend/.env 中填写")

    data_uri = build_audio_data_uri(file_path)
    if len(data_uri) > settings.asr_max_payload_bytes:
        raise ValueError(
            f"音频 Base64（Data URL）超过 ASR_MAX_PAYLOAD_BYTES="
            f"{settings.asr_max_payload_bytes}，请缩短录音"
        )

    payload: dict[str, Any] = {
        "model": settings.asr_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data_uri},
                    }
                ],
            }
        ],
        "stream": False,
        "asr_options": {
            "enable_itn": settings.asr_enable_itn,
        },
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    log.info(
        "百炼 ASR 请求: url=%s model=%s data_uri_len=%s",
        settings.dashscope_chat_completions_url,
        settings.asr_model,
        len(data_uri),
    )

    try:
        async with httpx.AsyncClient(
            timeout=settings.asr_timeout_seconds,
            trust_env=False,
        ) as client:
            r = await client.post(
                settings.dashscope_chat_completions_url,
                headers=headers,
                json=payload,
            )
    except httpx.HTTPError as e:
        raise RuntimeError(f"请求百炼接口失败: {e}") from e

    try:
        body = r.json()
    except json.JSONDecodeError:
        body = {"_parse_error": True, "raw_text": r.text}

    if r.status_code >= 400:
        err_preview = (
            json.dumps(body, ensure_ascii=False)[:2000]
            if isinstance(body, dict)
            else str(body)[:2000]
        )
        log.error("百炼 ASR HTTP %s: %s", r.status_code, err_preview[:500])
        raise RuntimeError(f"DashScope HTTP {r.status_code}: {err_preview}")

    if not isinstance(body, dict):
        raise RuntimeError("响应不是 JSON 对象")

    text = extract_transcript_from_completion(body)
    log.info("百炼 ASR 完成: transcript_len=%s", len(text))
    return text, body


def save_asr_result_json(
    storage_dir: Path,
    audio_filename: str,
    transcript: str,
    raw_response: dict[str, Any],
) -> str:
    """写入 Storage：<音频主名>.asr.json。返回写入的文件名。"""
    stem = Path(audio_filename).stem
    out_name = f"{stem}.asr.json"
    out_path = storage_dir / out_name
    record = {
        "source_audio": audio_filename,
        "model": settings.asr_model,
        "transcript": transcript,
        "raw_response": raw_response,
    }
    out_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_name
