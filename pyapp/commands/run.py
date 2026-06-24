"""pyapp run 命令 - 安装并运行应用"""

import re
from pathlib import Path

import click

from ..core.config import load_config
from ..core.logger import get_logger
from ..platforms import get_platform, PLATFORMS


def _sync_frontend_env(project_dir: Path, port: int) -> None:
    """同步 frontend/.env.development 的 VITE_API_PORT（从 dev.py 迁移）

    Args:
        project_dir: 项目目录
        port: 后端端口（从 pyproject.toml 读取）
    """
    logger = get_logger()
    env_file = project_dir / "frontend" / ".env.development"

    if not env_file.exists():
        # 创建 .env.development
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_content = (
            "# Backend API port for development\n"
            "# Auto-synced from pyproject.toml\n"
            f"VITE_API_PORT={port}\n"
        )
        try:
            env_file.write_text(env_content, encoding="utf-8")
        except (PermissionError, OSError, IOError) as e:
            logger.warning(f"Failed to create frontend .env.development: {e}")
        return

    # 更新已存在的 .env.development
    content = env_file.read_text(encoding="utf-8")

    # 更新 VITE_API_PORT 值（支持带引号、空格等格式）
    new_content = re.sub(
        r"(VITE_API_PORT\s*=\s*)['\"]?\d+['\"]?",
        f"\\g<1>{port}",
        content,
    )

    if new_content != content:
        try:
            env_file.write_text(new_content, encoding="utf-8")
            logger.info(f"Synced frontend port to {port}")
        except (PermissionError, OSError, IOError) as e:
            logger.warning(f"Failed to sync frontend .env.development: {e}")


def run_platform(platform: str, project_dir: Path = None,
                 update: bool = False, rebuild: bool = False):
    """
    运行应用

    Args:
        platform: 平台名称 (android/windows/linux)
        project_dir: 项目目录，默认为当前目录
        update: 仅更新应用源码（不更新依赖）
        rebuild: 重新安装依赖（包含源码更新）
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

    if platform == "all":
        raise click.ClickException(
            "'run' command does not support 'all' platform. Specify a single platform."
        )

    # 同步前端环境（从 dev.py 迁移）
    port = config_dict.get("tool", {}).get("pyapp", {}).get("port", 18080)
    _sync_frontend_env(project_dir, port)

    try:
        platform_instance = get_platform(platform)
        bundle_dir = project_dir / "bundles" / platform

        # 如果 bundles 不存在或 -r，先执行完整 build
        if not bundle_dir.exists() or rebuild:
            logger.info(f"Building {platform} first...")
            from .commands.build import build_platform
            build_platform(platform, build_type="debug", project_dir=project_dir)
        elif update:
            # 仅更新源码，不重新安装依赖
            logger.info(f"Updating source code for {platform}...")
            platform_instance.sync_source_code(project_dir, platform, config_dict)
            platform_instance.sync_frontend_dist(project_dir, platform, config_dict)

        # 运行
        platform_instance.run(project_dir, config_dict)
    except ValueError as e:
        raise click.ClickException(str(e))
    except click.ClickException:
        raise
    except Exception as e:
        logger.error(f"Failed to run {platform} app: {e}")
        raise click.ClickException(f"Failed to run {platform} app: {e}")
