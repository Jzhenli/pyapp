"""pyapp create 命令 - 创建平台项目结构"""

from pathlib import Path
from typing import List

import click

from ..core.config import load_config
from ..core.logger import get_logger
from ..core.errors import ConfigError
from ..platforms import get_platform, get_all_platforms, PLATFORMS


def create_platform(platform: str, project_dir: Path = None, arch: str = None):
    """
    创建平台项目结构

    Args:
        platform: 平台名称 (android/windows/linux/all)
        project_dir: 项目目录，默认为当前目录
        arch: 目标架构
            - Android: arm64-v8a, armeabi-v7a, x86_64 (多个用逗号分隔)
    """
    logger = get_logger()

    if project_dir is None:
        project_dir = Path.cwd()

    # 加载配置
    try:
        config = load_config(project_dir)
        config_dict = config.to_dict()
    except FileNotFoundError:
        raise click.ClickException(
            "pyproject.toml not found. Run 'pyapp init' to create a new project."
        )
    except ValueError as e:
        raise click.ClickException(f"Configuration error: {e}")

    # 解析架构参数
    android_archs = None
    if arch and platform == "android":
        android_archs = [a.strip() for a in arch.split(",")]
        valid_android_archs = ["arm64-v8a", "armeabi-v7a", "x86_64"]
        for a in android_archs:
            if a not in valid_android_archs:
                raise click.ClickException(
                    f"Invalid Android architecture: {a}. Valid options: {', '.join(valid_android_archs)}"
                )

    # 确定要创建的平台
    if platform == "all":
        platforms = list(PLATFORMS.keys())
    else:
        platforms = [platform]

    for plat in platforms:
        logger.info(f"Creating {plat} project structure...")
        try:
            platform_instance = get_platform(plat)
            if plat == "android" and android_archs:
                platform_instance.create(project_dir, config_dict, arch=android_archs)
            else:
                platform_instance.create(project_dir, config_dict)
            logger.success(f"{plat} project created successfully")
        except ValueError as e:
            raise click.ClickException(str(e))
        except Exception as e:
            logger.error(f"Failed to create {plat} project: {e}")
            raise click.ClickException(f"Failed to create {plat} project: {e}")
