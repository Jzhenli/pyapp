"""pyapp build 命令 - 构建平台安装包"""

from pathlib import Path
from typing import Optional

import click

from ..core.config import load_config
from ..core.logger import get_logger
from ..core.errors import ConfigError, BuildError
from ..platforms import get_platform, PLATFORMS


def build_platform(platform: str, build_type: str = "debug", project_dir: Path = None,
                   no_create: bool = False, arch: str = None):
    """
    构建平台安装包

    Args:
        platform: 平台名称 (android/windows/linux/all)
        build_type: 构建类型 (debug/release)
        project_dir: 项目目录，默认为当前目录
        no_create: 不自动创建平台项目结构
        arch: 目标架构
            - Linux: x86_64, aarch64, armv7l
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

    # 验证配置
    validate_before_build(project_dir, platform)

    # 解析架构参数
    android_archs = None
    linux_arch = None
    
    if arch:
        if platform == "android" or platform == "all":
            # Android 架构：逗号分隔
            android_archs = [a.strip() for a in arch.split(",")]
            valid_android_archs = ["arm64-v8a", "armeabi-v7a", "x86_64"]
            for a in android_archs:
                if a not in valid_android_archs:
                    raise click.ClickException(
                        f"Invalid Android architecture: {a}. Valid options: {', '.join(valid_android_archs)}"
                    )
        
        if platform == "linux" or platform == "all":
            # Linux 架构：单个值
            linux_arch = arch.split(",")[0].strip() if "," in arch else arch
            valid_linux_archs = ["x86_64", "aarch64", "armv7l"]
            if linux_arch not in valid_linux_archs:
                raise click.ClickException(
                    f"Invalid Linux architecture: {linux_arch}. Valid options: {', '.join(valid_linux_archs)}"
                )

    # 确定要构建的平台
    if platform == "all":
        platforms = list(PLATFORMS.keys())
    else:
        platforms = [platform]

    results = []
    for plat in platforms:
        arch_info = ""
        if plat == "android" and android_archs:
            arch_info = "/" + ",".join(android_archs)
        elif plat == "linux" and linux_arch:
            arch_info = "/" + linux_arch
        
        logger.info(f"Building {plat}{arch_info}...")
        try:
            platform_instance = get_platform(plat)

            # 自动创建缺失的平台项目结构
            if not no_create:
                bundle_dir = project_dir / "bundles" / plat
                if not bundle_dir.exists():
                    logger.info(f"Creating {plat} project structure...")
                    if plat == "android" and android_archs:
                        platform_instance.create(project_dir, config_dict, arch=android_archs)
                    else:
                        platform_instance.create(project_dir, config_dict)

            # 传递架构参数
            if plat == "linux" and linux_arch:
                result = platform_instance.build(project_dir, config_dict, build_type, arch=linux_arch)
            elif plat == "android" and android_archs:
                result = platform_instance.build(project_dir, config_dict, build_type, arch=android_archs)
            else:
                result = platform_instance.build(project_dir, config_dict, build_type)
            results.append((plat, result))

            if result.success:
                logger.success(f"{plat} build succeeded: {result.output_path}")
            else:
                logger.error(f"{plat} build failed: {result.error_message}")

        except ValueError as e:
            raise click.ClickException(str(e))
        except Exception as e:
            logger.error(f"{plat} build failed: {e}")
            from ..platforms.base import BuildResult
            results.append((plat, BuildResult(success=False, error_message=str(e))))

    # 汇总结果
    logger.info("")
    logger.info("Build Summary:")
    for plat, result in results:
        if result.success:
            logger.success(f"  {plat}: {result.output_path}")
        else:
            logger.error(f"  {plat}: {result.error_message}")

    # 如果有任何平台构建失败，返回非零退出码
    failed = [plat for plat, result in results if not result.success]
    if failed:
        raise click.ClickException(f"Build failed for: {', '.join(failed)}")


def validate_before_build(project_dir: Path, platform: str) -> None:
    """构建前验证"""
    logger = get_logger()

    # 验证前端资源（可选）
    frontend_dist = project_dir / "frontend" / "dist"
    if not frontend_dist.exists():
        logger.warning("frontend/dist/ not found, frontend will not be included")

    logger.debug("Configuration validated successfully")
