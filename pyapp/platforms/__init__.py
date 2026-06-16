"""平台注册机制"""

from .base import BasePlatform, BuildResult
from .android import AndroidPlatform
from .windows import WindowsPlatform
from .linux import LinuxPlatform

# 平台注册表
PLATFORMS: dict = {
    "android": AndroidPlatform(),
    "windows": WindowsPlatform(),
    "linux": LinuxPlatform(),
}


def get_platform(name: str) -> BasePlatform:
    """获取平台实例"""
    if name not in PLATFORMS:
        raise ValueError(f"Unknown platform: {name}. Available: {', '.join(PLATFORMS.keys())}")
    return PLATFORMS[name]


def get_all_platforms() -> list:
    """获取所有平台实例"""
    return list(PLATFORMS.values())
