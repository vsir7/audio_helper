"""将「地图侧」HTTP 交互（高德 Web 服务，与 MCP 能力对应）按次写入 Storage，文件名 {stem}_MCP01.json …"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("audio_helper.mcp_dump")


def _redact_secrets(obj: Any) -> Any:
    """递归脱敏常见密钥字段（如 query 里的 key）。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in ("key", "api_key", "apikey", "authorization", "secret"):
                out[k] = "[REDACTED]"
            else:
                out[k] = _redact_secrets(v)
        return out
    if isinstance(obj, list):
        return [_redact_secrets(x) for x in obj]
    return obj


class MCPJsonRecorder:
    """单次流水线内递增 MCP01、MCP02…，与同 stem 的 asr/pipeline 文件同目录。"""

    def __init__(self, storage_dir: Path, stem: str) -> None:
        self.storage_dir = storage_dir
        self.stem = stem
        self._seq = 0
        self.filenames: list[str] = []

    def write(
        self,
        label: str,
        service: str,
        request_meta: dict[str, Any],
        response_body: dict[str, Any],
    ) -> str:
        self._seq += 1
        fname = f"{self.stem}_MCP{self._seq:02d}.json"
        path = self.storage_dir / fname
        doc = {
            "schema": "audio_helper_mcp_traffic_v1",
            "note": (
                "记录后端与高德开放平台 Web 服务 API 的一次 HTTP 往返；"
                "能力上与高德 MCP 文档中的地理/逆地理/测距等对应，但并非 MCP JSON-RPC 协议报文。"
            ),
            "label": label,
            "service": service,
            "saved_at_utc": datetime.now(timezone.utc).isoformat(),
            "request": _redact_secrets(request_meta),
            "response": response_body,
        }
        path.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.filenames.append(fname)
        log.info("已写入 MCP 通信 JSON: %s (%s)", fname, label)
        return fname
