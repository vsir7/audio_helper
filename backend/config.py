"""从 backend/.env 加载配置（不读取操作系统环境变量，仅 .env 文件 + 代码默认值）。"""
from pathlib import Path
from typing import Type, Tuple

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

_BACKEND_DIR = Path(__file__).resolve().parent
# 仓库根目录（backend 的上一级）
_PROJECT_ROOT = _BACKEND_DIR.parent


def _default_storage_dir() -> Path:
    return _PROJECT_ROOT / "Storage"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        # 仅使用：构造参数 + backend/.env，不使用 os.environ 覆盖
        return (init_settings, dotenv_settings)

    # 服务
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS：逗号分隔，如 http://localhost:5173,http://127.0.0.1:5173
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # 接口配置
    process_path: str = "/api/process"
    upload_field_name: str = "audio"

    # 上传文件保存目录（可为绝对路径；默认仓库根目录下 Storage）
    storage_dir: str = ""
    # 上传大小限制（MB）
    max_upload_mb: int = 20

    # 是否允许 GET 读取 Storage 内文件（开发试听；生产建议 false）
    storage_public_read: bool = True

    # 百炼 / DashScope（HTTP 调用，见 docs/百炼_接口文档.md）
    dashscope_api_key: str = ""
    dashscope_chat_completions_url: str = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    asr_model: str = "qwen3-asr-flash"
    asr_enable_itn: bool = False
    asr_timeout_seconds: float = 120.0
    # 官方对 Base64 输入有大小限制，默认按 10MB 控制 Data URL 总长度
    asr_max_payload_bytes: int = 10 * 1024 * 1024

    # DeepSeek（HTTP，见 docs/DeepSeek_接口文档.md）
    deepseek_api_key: str = ""
    deepseek_chat_completions_url: str = "https://api.deepseek.com/v1/chat/completions"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_seconds: float = 90.0
    deepseek_temperature: float = 0.2
    # 整合话术（空则与 DEEPSEEK_MODEL 相同）
    deepseek_compose_model: str = ""
    deepseek_compose_temperature: float = 0.55

    # 百炼 CosyVoice TTS（与 ASR 共用 DASHSCOPE_API_KEY，见 docs/百炼_接口文档.md）
    cosyvoice_tts_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
    )
    tts_model: str = "cosyvoice-v3-flash"
    tts_voice: str = "longanyang"
    tts_format: str = "mp3"
    tts_sample_rate: int = 22050
    tts_timeout_seconds: float = 120.0
    tts_max_characters: int = 1500

    # 返回给前端的可播放链接前缀（需与浏览器访问后端的地址一致）
    backend_public_origin: str = "http://127.0.0.1:8000"

    # 高德 Web 服务（相遇点=几何中点 + 逆地理 + 测距，见 docs/高德_MCP与REST_接口文档.md）
    amap_rest_key: str = ""
    amap_geocode_url: str = "https://restapi.amap.com/v3/geocode/geo"
    amap_regeo_url: str = "https://restapi.amap.com/v3/geocode/regeo"
    amap_distance_url: str = "https://restapi.amap.com/v3/distance"
    # 距离测量 type（高德 v3/distance：0=直线，1=驾车，3=步行≤5km）
    amap_distance_type: int = 0
    amap_timeout_seconds: float = 30.0

    # 日志（相对路径基于项目根目录 audio_helper/）
    log_dir: str = "logs"
    log_filename: str = "audio_helper.log"
    log_level: str = "INFO"
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 5

    @property
    def storage_path(self) -> Path:
        if self.storage_dir.strip():
            return Path(self.storage_dir).expanduser().resolve()
        return _default_storage_dir()

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
