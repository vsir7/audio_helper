"""调用外网 API 前清理代理环境变量，避免 httpx/requests 误走系统代理。"""
import os

_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


def clear_proxy_environment() -> None:
    for k in _PROXY_ENV_KEYS:
        os.environ.pop(k, None)
