"""FastAPI：上传音频 → 百炼 ASR → DeepSeek 抽地址 → 高德 REST 相遇推荐。"""
from __future__ import annotations

import json
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# 支持从仓库根目录运行：`uvicorn backend.main:app`
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from amap_client import meetup_recommend
from bailian_asr import save_asr_result_json, transcribe_file
from bailian_tts import synthesize_to_storage
from config import settings
from deepseek_compose import compose_meetup_reply
from deepseek_extract import extract_two_addresses
from logging_setup import setup_logging

log = logging.getLogger("audio_helper.api")


def _storage_file_path(filename: str) -> Path:
    """仅允许单层文件名，且解析后必须落在 storage 目录内。"""
    name = Path(filename).name
    if not name or filename != name:
        raise HTTPException(status_code=400, detail="非法文件名")
    base = settings.storage_path.resolve()
    path = (base / name).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法路径") from None
    return path


def _guess_media_type(suffix: str) -> str:
    s = suffix.lower()
    return {
        ".webm": "video/webm",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
        ".bin": "application/octet-stream",
    }.get(s, "application/octet-stream")


def _format_leg(label: str, leg: dict | None) -> str:
    if not leg:
        return f"{label}：距离数据暂缺"
    d = leg.get("distance_meters")
    t = leg.get("duration_seconds")
    if isinstance(d, int):
        ds = f"{d} 米"
    else:
        ds = str(d) if d else "未知"
    if isinstance(t, int):
        return f"{label}：约 {ds}，预估耗时约 {t // 60} 分钟"
    return f"{label}：约 {ds}"


def _build_reply_text(
    transcript: str,
    addresses: dict,
    meetup: dict,
) -> str:
    lines = [
        f"【识别】{transcript}",
        f"【地点一】{addresses.get('address_a', '')}",
        f"【地点二】{addresses.get('address_b', '')}",
    ]
    notes = addresses.get("notes")
    if notes:
        lines.append(f"【备注】{notes}")

    ml = meetup.get("meetup_location") or {}
    coord = ml.get("coordinate") or meetup.get("midpoint", "")
    desc = ml.get("description") or ml.get("formatted_address") or coord
    lines.append("【推荐相遇点】按两地坐标计算的几何中点（无特定场所偏好）")
    lines.append(f"坐标：{coord}")
    lines.append(f"位置说明：{desc}")

    tv = meetup.get("travel_to_meetup") or {}
    lines.append("【各自到相遇点】（测距方式见配置 AMAP_DISTANCE_TYPE）")
    lines.append(_format_leg("第一人", tv.get("from_person_a")))
    lines.append(_format_leg("第二人", tv.get("from_person_b")))

    return "\n".join(lines)


def _save_pipeline_json(
    storage: Path,
    stem: str,
    payload: dict,
) -> str:
    name = f"{stem}.pipeline.json"
    path = storage / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return name


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log.info(
        "FastAPI 启动，流水线：上传 → ASR → DeepSeek抽址 → 高德中点 → DeepSeek整合 → 百炼TTS"
    )
    yield
    log.info("FastAPI 关闭")


app = FastAPI(title="audio-helper", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/storage/{filename}")
async def listen_storage_file(filename: str):
    """
    在浏览器中试听 Storage 内已保存的音频（VS Code 内置预览常无法播放 WebM）。
    示例：http://localhost:8000/api/storage/20260405T033314_8b9da722.webm
    """
    if not settings.storage_public_read:
        raise HTTPException(status_code=404, detail="未开启公开读取")
    path = _storage_file_path(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(
        path,
        media_type=_guess_media_type(path.suffix),
        filename=path.name,
    )


@app.post(settings.process_path)
async def process_audio(
    audio: UploadFile = File(..., alias=settings.upload_field_name, description="浏览器录制的音频文件"),
):
    """
    multipart 字段名由 .env 的 UPLOAD_FIELD_NAME 指定（默认 audio）。
    节点日志见项目根目录 logs/audio_helper.log（及控制台）。
    """
    rid = uuid4().hex[:12]
    log.info("[%s] ========== 新请求：接收上传 ==========", rid)

    if not audio.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    storage = settings.storage_path
    storage.mkdir(parents=True, exist_ok=True)

    suffix = Path(audio.filename).suffix
    if not suffix or len(suffix) > 10:
        suffix = ".bin"

    safe_name = (
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_"
        f"{uuid4().hex[:8]}{suffix}"
    )
    dest = storage / safe_name
    stem = dest.stem

    total_size = 0
    chunk_size = 1024 * 1024
    try:
        with dest.open("wb") as f:
            while True:
                chunk = await audio.read(chunk_size)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件过大，超过限制 {settings.max_upload_mb}MB",
                    )
                f.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except OSError as e:
        raise HTTPException(
            status_code=500, detail=f"写入文件失败: {e}"
        ) from e
    finally:
        await audio.close()

    if total_size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="上传文件为空")

    log.info("[%s] 已保存音频: %s (%s bytes)", rid, safe_name, total_size)

    try:
        transcript, raw_asr = await transcribe_file(dest)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "百炼 ASR 调用失败",
                "saved_as": safe_name,
                "error": str(e),
            },
        ) from e
    except OSError as e:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "读取已保存音频失败",
                "saved_as": safe_name,
                "error": str(e),
            },
        ) from e

    asr_json_name = save_asr_result_json(storage, safe_name, transcript, raw_asr)
    log.info("[%s] ASR 结果已写入: %s", rid, asr_json_name)

    try:
        addresses, raw_deepseek = await extract_two_addresses(transcript)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "DeepSeek 调用失败",
                "saved_as": safe_name,
                "asr_saved_as": asr_json_name,
                "error": str(e),
            },
        ) from e

    if not addresses.get("address_a") or not addresses.get("address_b"):
        log.warning(
            "[%s] DeepSeek 未抽出完整双地址: %s",
            rid,
            addresses,
        )
        raise HTTPException(
            status_code=422,
            detail={
                "message": "未能从识别文本中抽取两个有效地址，请换更明确的表述",
                "saved_as": safe_name,
                "asr_saved_as": asr_json_name,
                "addresses": addresses,
            },
        )

    try:
        meetup = await meetup_recommend(
            addresses["address_a"],
            addresses["address_b"],
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "高德接口调用失败",
                "saved_as": safe_name,
                "asr_saved_as": asr_json_name,
                "addresses": addresses,
                "error": str(e),
            },
        ) from e

    structured_reply = _build_reply_text(transcript, addresses, meetup)

    try:
        composed_reply, raw_compose = await compose_meetup_reply(
            transcript, addresses, meetup
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "DeepSeek 整合话术失败",
                "saved_as": safe_name,
                "asr_saved_as": asr_json_name,
                "error": str(e),
            },
        ) from e

    log.info("[%s] DeepSeek 整合话术完成 len=%s", rid, len(composed_reply))

    tts_saved_as: str | None = None
    tts_raw: dict | None = None
    audio_url: str | None = None
    try:
        tts_saved_as, tts_raw = await synthesize_to_storage(
            composed_reply, storage, stem
        )
        if tts_saved_as and settings.storage_public_read:
            origin = settings.backend_public_origin.rstrip("/")
            audio_url = f"{origin}/api/storage/{tts_saved_as}"
        log.info("[%s] TTS 完成: %s", rid, tts_saved_as)
    except ValueError as e:
        log.warning("[%s] TTS 跳过: %s", rid, e)
    except RuntimeError as e:
        log.warning("[%s] TTS 失败（仍返回文本）: %s", rid, e)

    pipeline_name = _save_pipeline_json(
        storage,
        stem,
        {
            "request_id": rid,
            "saved_audio": safe_name,
            "transcript": transcript,
            "asr_saved_as": asr_json_name,
            "deepseek_addresses": addresses,
            "deepseek_extract_raw_completion": raw_deepseek,
            "amap_meetup_recommend": meetup,
            "structured_reply_fallback": structured_reply,
            "deepseek_composed_reply": composed_reply,
            "deepseek_compose_raw_completion": raw_compose,
            "tts_saved_as": tts_saved_as,
            "tts_raw_response": tts_raw,
        },
    )
    log.info("[%s] 流水线完成，已写入: %s", rid, pipeline_name)

    out: dict = {
        "ok": True,
        "message": "pipeline_ok",
        "request_id": rid,
        "saved_as": safe_name,
        "asr_saved_as": asr_json_name,
        "pipeline_saved_as": pipeline_name,
        "storage_path": str(dest),
        "size_bytes": total_size,
        "transcript": transcript,
        "text": composed_reply,
        "reply_text": composed_reply,
        "structured_reply": structured_reply,
        "addresses": addresses,
        "amap": {
            "strategy": meetup.get("strategy"),
            "midpoint": meetup.get("midpoint"),
            "location_a": meetup.get("location_a"),
            "location_b": meetup.get("location_b"),
            "meetup_location": meetup.get("meetup_location"),
            "travel_to_meetup": meetup.get("travel_to_meetup"),
        },
    }
    if tts_saved_as:
        out["tts_saved_as"] = tts_saved_as
    if audio_url:
        out["audio_url"] = audio_url
        out["audioUrl"] = audio_url
    return out


if __name__ == "__main__":
    import uvicorn

    app_target = f"{__package__}.main:app" if __package__ else "main:app"
    uvicorn.run(
        app_target,
        host=settings.host,
        port=settings.port,
        reload=True,
    )
